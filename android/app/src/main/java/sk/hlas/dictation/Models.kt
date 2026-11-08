package sk.hlas.dictation

import android.content.Context
import okhttp3.Request
import java.io.File
import java.io.FileOutputStream

/** The two offline speech models (~1.3 GB), downloaded once. See models/README.md. */
object Models {
    const val RELEASE = "https://github.com/JozkoAndroid/whisper/releases/download/models-v1/"
    /** Second source for the base model (same NVIDIA model, converted by the sherpa-onnx author). */
    const val BASE_MIRROR = "https://huggingface.co/csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8/resolve/main/"

    /** GitHub release asset ids of models-v1 (the API address is far more reliable than releases/download). */
    private val ASSET_IDS = mapOf(
        ("base" to "decoder.int8.onnx") to 723428492L, ("base" to "encoder.int8.onnx") to 723428493L,
        ("base" to "joiner.int8.onnx") to 723428494L, ("base" to "tokens.txt") to 723428496L,
        ("sk" to "decoder.int8.onnx") to 723428508L, ("sk" to "encoder.int8.onnx") to 723428512L,
        ("sk" to "joiner.int8.onnx") to 723428518L, ("sk" to "tokens.txt") to 723428516L,
    )
    private const val API_ASSET = "https://api.github.com/repos/JozkoAndroid/whisper/releases/assets/"

    /** Sources in order of preference: Hugging Face (base), GitHub API, GitHub release page. */
    fun urls(name: String, file: String): List<String> {
        val out = mutableListOf<String>()
        if (name == "base") out.add(BASE_MIRROR + file)
        ASSET_IDS[name to file]?.let { out.add(API_ASSET + it) }
        out.add(RELEASE + "parakeet-$name-$file")
        return out
    }
    val FILES = listOf("encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx", "tokens.txt")
    val NAMES = listOf("base", "sk")

    fun root(context: Context) = File(context.filesDir, "models")
    fun dir(root: File, name: String) = File(root, "parakeet-$name")

    fun ready(context: Context) = ready(root(context))
    fun ready(root: File) = NAMES.all { n -> FILES.all { File(dir(root, n), it).isFile } }

    private const val TOTAL_BYTES = 1_341_000_000L  // approximate, for the progress display

    /**
     * Blocking. Resumes partial downloads and retries on errors. progress(0..100).
     * No HEAD request: GitHub's signed download links only allow GET.
     */
    fun download(context: Context, progress: (Int) -> Unit) {
        val root = root(context)
        val all = NAMES.flatMap { n -> FILES.map { n to it } }
        var done = all.sumOf { (n, f) ->
            val d = File(dir(root, n), f)
            val p = File(d.path + ".part")
            if (d.isFile) d.length() else if (p.isFile) p.length() else 0L
        }
        var lastPct = -1
        fun report(delta: Long) {
            done += delta
            val pct = minOf(99, (done * 100 / TOTAL_BYTES).toInt())
            if (pct != lastPct) { lastPct = pct; progress(pct) }
        }
        for ((n, f) in all) {
            val dest = File(dir(root, n), f)
            if (dest.isFile) continue
            dest.parentFile?.mkdirs()
            var error: Exception? = null
            for (url in urls(n, f)) {
                try { fetch(url, dest, ::report); error = null; break } catch (e: Exception) { error = e }
            }
            error?.let { throw it }
        }
        progress(100)
    }

    internal fun fetch(url: String, dest: File, onBytes: (Long) -> Unit) {
        val part = File(dest.path + ".part")
        var lastError: Exception? = null
        for (attempt in 0 until 8) {
            val have = if (part.exists()) part.length() else 0L
            val req = Request.Builder().url(url).header("Accept", "application/octet-stream")
                .apply { if (have > 0) header("Range", "bytes=$have-") }.build()
            try {
                Stt.http.newCall(req).execute().use { resp ->
                    if (resp.code == 416 && have > 0) { onBytes(-have); part.delete(); throw java.io.IOException("restart") }
                    if (resp.code in 400..499 && resp.code != 429) throw SttException("Download failed: HTTP ${resp.code}")
                    if (!resp.isSuccessful) throw java.io.IOException("HTTP ${resp.code}")
                    val resumed = resp.code == 206
                    if (!resumed && have > 0) onBytes(-have)
                    val body = resp.body ?: throw java.io.IOException("empty response")
                    val length = body.contentLength()
                    val expected = if (length > 0) (if (resumed) have else 0L) + length else -1L
                    FileOutputStream(part, resumed).use { out ->
                        val buf = ByteArray(1 shl 16)
                        val input = body.byteStream()
                        while (true) {
                            val r = input.read(buf)
                            if (r < 0) break
                            out.write(buf, 0, r)
                            onBytes(r.toLong())
                        }
                    }
                    if (expected > 0 && part.length() != expected) throw java.io.IOException("connection closed early")
                }
                if (!part.renameTo(dest)) throw java.io.IOException("could not save ${dest.name}")
                return
            } catch (e: SttException) {
                throw e
            } catch (e: Exception) {
                lastError = e
                Thread.sleep(minOf(10_000L, 1000L * (attempt + 1)))  // GitHub often answers 504 once, then works
            }
        }
        throw SttException("Download failed after several tries (${lastError?.message}). Tap to resume.")
    }
}
