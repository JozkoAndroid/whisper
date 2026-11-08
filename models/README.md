# Speech models

The apps download these files from the `models-v1` release of this repository
(made by `.github/workflows/models.yml`):

| Files | Model | License |
|---|---|---|
| `parakeet-base-*` | [NVIDIA Parakeet TDT 0.6B v3](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3), 25 European languages | CC-BY-4.0 |
| `parakeet-sk-*` | [KInIT Slovak fine-tune](https://huggingface.co/kinit/parakeet-tdt-0.6b-v3-sk) of the same model | CC-BY-4.0 |

Each is converted with `export_parakeet.py` to int8 ONNX for [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx)
(`encoder.int8.onnx`, `decoder.int8.onnx`, `joiner.int8.onnx`, `tokens.txt`, `bpe.vocab`).
`generate_bpe_vocab.py` is from sherpa-onnx (Apache-2.0).

To convert by hand: `pip install torch nemo_toolkit[asr] onnx onnxruntime`, then
`python export_parakeet.py MODEL.nemo OUT_DIR`.
