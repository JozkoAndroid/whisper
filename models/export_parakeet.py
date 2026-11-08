#!/usr/bin/env python3
"""Convert a NeMo Parakeet TDT model (.nemo) into the int8 ONNX files that
sherpa-onnx runs (desktop and Android). Based on the sherpa-onnx export
script by Fangjun Kuang (Xiaomi Corp., Apache-2.0).

    python export_parakeet.py MODEL.nemo OUTPUT_DIR [SOURCE_URL]

Output: encoder.int8.onnx, decoder.int8.onnx, joiner.int8.onnx, tokens.txt, bpe.vocab
"""

import gc
import os
import subprocess
import sys
from pathlib import Path

import nemo.collections.asr as nemo_asr
import onnx
import torch
from onnxruntime.quantization import QuantType, quantize_dynamic

sys.path.insert(0, str(Path(__file__).parent))
from generate_bpe_vocab import generate_bpe_vocab_from_model  # noqa: E402


def set_meta(path: Path, meta: dict) -> None:
    model = onnx.load(str(path))
    while len(model.metadata_props):
        model.metadata_props.pop()
    for k, v in meta.items():
        p = model.metadata_props.add()
        p.key, p.value = k, str(v)
    onnx.save(model, str(path))


@torch.no_grad()
def main() -> None:
    src, out = sys.argv[1], Path(sys.argv[2]).resolve()
    url = sys.argv[3] if len(sys.argv) > 3 else "https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3"
    # sherpa-onnx recognizes a TDT model by "tdt" in this url; without it decoding fails.
    if "tdt" not in url.lower():
        raise SystemExit("the source url must contain 'tdt' (sherpa-onnx uses it to detect TDT models)")
    out.mkdir(parents=True, exist_ok=True)
    model = nemo_asr.models.ASRModel.restore_from(restore_path=src, map_location="cpu")
    model.eval()
    os.chdir(out)

    with open("tokens.txt", "w", encoding="utf-8") as f:
        for i, s in enumerate(model.joint.vocabulary):
            f.write(f"{s} {i}\n")
        f.write(f"<blk> {i + 1}\n")
    generate_bpe_vocab_from_model(asr_model=model, output_path="./bpe.vocab")

    model.encoder.export("encoder.onnx")
    model.decoder.export("decoder.onnx")
    model.joint.export("joiner.onnx")

    normalize = model.cfg.preprocessor.normalize
    meta = {
        "vocab_size": model.decoder.vocab_size,
        "normalize_type": "" if normalize == "NA" else normalize,
        "pred_rnn_layers": model.decoder.pred_rnn_layers,
        "pred_hidden": model.decoder.pred_hidden,
        "subsampling_factor": 8,
        "model_type": "EncDecRNNTBPEModel",
        "version": "2",
        "model_author": "NeMo",
        "url": url,
        "comment": "Only the transducer branch is exported",
        "feat_dim": 128,
    }
    Path("meta.txt").write_text("\n".join(f"{k}\t{v}" for k, v in meta.items()), encoding="utf-8")
    # Quantize in a fresh process so the NeMo model's memory is gone (CI runners have ~7 GB).
    del model
    gc.collect()
    subprocess.run([sys.executable, os.path.abspath(__file__), "--quantize", "."], check=True)


def quantize(out: Path) -> None:
    os.chdir(out)
    meta = dict(line.split("\t", 1) for line in Path("meta.txt").read_text(encoding="utf-8").splitlines())
    for m in ("encoder", "decoder", "joiner"):
        quantize_dynamic(model_input=f"{m}.onnx", model_output=f"{m}.int8.onnx",
                         weight_type=QuantType.QUInt8 if m == "encoder" else QuantType.QInt8)
        gc.collect()
    set_meta(Path("encoder.int8.onnx"), meta)
    for f in Path(".").iterdir():
        if f.name not in {"encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx", "tokens.txt", "bpe.vocab"}:
            f.unlink()
    os.system("ls -lh")


if __name__ == "__main__":
    if sys.argv[1] == "--quantize":
        quantize(Path(sys.argv[2]))
    else:
        main()
