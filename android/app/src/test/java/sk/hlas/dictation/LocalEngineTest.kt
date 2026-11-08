package sk.hlas.dictation

import org.junit.Assume.assumeTrue
import org.junit.Test
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder

/** Runs only when the models and the desktop sherpa-onnx JNI library are available (see build.gradle.kts). */
class LocalEngineTest {
    private fun readWav16k(f: File): ShortArray {
        val b = ByteBuffer.wrap(f.readBytes()).order(ByteOrder.LITTLE_ENDIAN)
        val rate = b.getInt(24)
        require(rate == 16000) { "${f.name}: need 16 kHz" }
        val data = ShortArray((f.length().toInt() - 44) / 2)
        b.position(44)
        b.asShortBuffer().get(data)
        return data
    }

    @Test fun transcribesRealAudio() {
        val models = System.getenv("HLAS_MODELS_DIR")?.let(::File)
        val wavs = System.getenv("HLAS_TEST_WAVS")?.let(::File)
        assumeTrue(models != null && wavs != null && Models.ready(models))
        for (f in wavs!!.listFiles { x -> x.name.endsWith(".wav") }!!.sortedBy { it.name }) {
            val x = AudioUtil.trimSilence(readWav16k(f))
            val t = System.nanoTime()
            val (text, langs) = LocalEngine.transcribe(models!!, x, "auto")
            println("${f.name} $langs ${(System.nanoTime() - t) / 1_000_000} ms | $text")
        }
    }
}
