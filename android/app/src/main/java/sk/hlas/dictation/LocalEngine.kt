package sk.hlas.dictation

import java.io.File
import com.k2fsa.sherpa.onnx.OfflineModelConfig
import com.k2fsa.sherpa.onnx.OfflineRecognizer
import com.k2fsa.sherpa.onnx.OfflineRecognizerConfig
import com.k2fsa.sherpa.onnx.OfflineTransducerModelConfig
import java.util.concurrent.Callable
import java.util.concurrent.Executors

/**
 * Free, offline speech recognition. Same design as desktop/hlas/local.py:
 * Parakeet v3 (good English/German) + KInIT's Slovak fine-tune, both run on
 * each phrase, and the output that reads right wins.
 */
object LocalEngine {
    private val recognizers = mutableMapOf<String, OfflineRecognizer>()
    private val pool = Executors.newFixedThreadPool(2)

    @Synchronized
    private fun recognizer(root: File, name: String): OfflineRecognizer {
        recognizers[name]?.let { return it }
        if (!Models.ready(root)) throw SttException("Download the offline models in Hlas settings")
        val d = Models.dir(root, name).path
        val threads = maxOf(1, minOf(4, Runtime.getRuntime().availableProcessors() / 2))
        val config = OfflineRecognizerConfig(
            modelConfig = OfflineModelConfig(
                transducer = OfflineTransducerModelConfig(
                    encoder = "$d/encoder.int8.onnx", decoder = "$d/decoder.int8.onnx", joiner = "$d/joiner.int8.onnx"),
                tokens = "$d/tokens.txt",
                numThreads = threads,
                modelType = "nemo_transducer",
            ),
            decodingMethod = "greedy_search",
        )
        return OfflineRecognizer(null, config).also { recognizers[name] = it }
    }

    fun preload(root: File) {
        Models.NAMES.forEach { recognizer(root, it) }
    }

    @Synchronized
    fun release() {
        recognizers.values.forEach { it.release() }
        recognizers.clear()
    }

    private fun decode(root: File, name: String, x: ShortArray): String {
        val rec = recognizer(root, name)
        val samples = FloatArray(x.size) { x[it] / 32768f }
        synchronized(rec) {
            val stream = rec.createStream()
            try {
                stream.acceptWaveform(samples, AudioUtil.RATE)
                rec.decode(stream)
                return rec.getResult(stream).text.trim()
            } finally {
                stream.release()
            }
        }
    }

    /** Returns (text, languages). lang: auto/sk/de/en. */
    fun transcribe(root: File, x: ShortArray, lang: String): Pair<String, List<String>> {
        if (lang == "sk") return decode(root, "sk", x) to listOf("sk")
        if (lang == "de" || lang == "en") return decode(root, "base", x) to listOf(lang)
        val texts = mutableListOf<String>()
        val langs = mutableListOf<String>()
        for (phrase in AudioUtil.splitPhrases(x)) {
            val sk = pool.submit(Callable { decode(root, "sk", phrase) })
            val base = decode(root, "base", phrase)
            val skText = sk.get()
            val (text, guess) = if (LangId.pick(base, skText) == "sk") skText to "sk" else base to LangId.guess(base)
            val clean = text.replace("<unk>", "").trim()
            if (clean.isNotEmpty()) texts.add(clean)
            if (guess.isNotEmpty() && guess !in langs) langs.add(guess)
        }
        return texts.joinToString(" ") to langs
    }
}
