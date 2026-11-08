package sk.hlas.dictation

import android.content.Context
import okhttp3.Request
import java.io.File
import java.io.FileOutputStream

/** The two offline speech models (~1.3 GB), downloaded once. See models/README.md. */
object Models {
    const val RELEASE = "https://github.com/JozkoAndroid/whisper/releases/download/models-v1/"
    val FILES = listOf("encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx", "tokens.txt")
    val NAMES = listOf("base", "sk")

    fun root(context: Context) = File(context.filesDir, "models")
    fun dir(root: File, name: String) = File(root, "parakeet-$name")

    fun ready(context: Context) = ready(root(context))
    fun ready(root: File) = NAMES.all { n -> FILES.all { File(dir(root, n), it).isFile } }

    /** Blocking. Resumes partial downloads. progress(0..100). */
    fun download(context: Context, progress: (Int) -> Unit) {
        val root = root(context)
        val todo = NAMES.flatMap { n -> FILES.map { n to it } }.filter { (n, f) -> !File(dir(root, n), f).isFile }
        val sizes = todo.associateWith { (n, f) ->
            Stt.http.newCall(Request.Builder().url(RELEASE + "parakeet-$n-$f").head().build()).execute()
                .use { it.header("Content-Length")?.toLongOrNull() ?: 0L }
        }
        val total = maxOf(1L, sizes.values.sum())
        var done = 0L
        for ((n, f) in todo) {
            val dest = File(dir(root, n), f)
            dest.parentFile?.mkdirs()
            val part = File(dest.path + ".part")
            val have = if (part.exists()) part.length() else 0L
            done += have
            val req = Request.Builder().url(RELEASE + "parakeet-$n-$f")
                .apply { if (have > 0) header("Range", "bytes=$have-") }.build()
            Stt.http.newCall(req).execute().use { resp ->
                if (!resp.isSuccessful) throw SttException("Download failed: HTTP ${resp.code}")
                val append = resp.code == 206
                if (!append) done -= have
                val body = resp.body ?: throw SttException("Download failed")
                FileOutputStream(part, append).use { out ->
                    val buf = ByteArray(1 shl 16)
                    val input = body.byteStream()
                    var last = -1
                    while (true) {
                        val r = input.read(buf)
                        if (r < 0) break
                        out.write(buf, 0, r)
                        done += r
                        val pct = (done * 100 / total).toInt()
                        if (pct != last) { last = pct; progress(pct) }
                    }
                }
            }
            val expected = sizes[n to f] ?: 0L
            if (expected > 0 && part.length() != expected) {
                part.delete()
                throw SttException("Download of $f was incomplete, try again")
            }
            part.renameTo(dest)
        }
        progress(100)
    }
}
