package sk.hlas.dictation

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assume.assumeTrue
import org.junit.Test
import java.io.File

/** Network test against the real release; runs only with HLAS_DOWNLOAD_TEST=1. */
class ModelsDownloadTest {
    @Test fun downloadsAndResumes() {
        assumeTrue(System.getenv("HLAS_DOWNLOAD_TEST") == "1")
        val dir = kotlin.io.path.createTempDirectory("hlas").toFile()
        val url = Models.RELEASE + "parakeet-sk-decoder.int8.onnx"
        val full = File(dir, "a.onnx")
        var bytes = 0L
        Models.fetch(url, full) { bytes += it }
        assertEquals(11845274L, full.length())
        assertEquals(full.length(), bytes)

        // Resume: start from a partial file
        val resumed = File(dir, "b.onnx")
        File(resumed.path + ".part").writeBytes(full.readBytes().copyOf(1_000_000))
        var more = 0L
        Models.fetch(url, resumed) { more += it }
        assertEquals(full.length() - 1_000_000, more)
        assertArrayEquals(full.readBytes(), resumed.readBytes())
        dir.deleteRecursively()
    }
}
