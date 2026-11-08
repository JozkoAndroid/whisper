package sk.hlas.dictation

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.math.PI
import kotlin.math.sin

class AudioUtilTest {
    private val r = AudioUtil.RATE
    private fun tone(sec: Double) = ShortArray((sec * r).toInt()) { (3000 * sin(2 * PI * 220 * it / r)).toInt().toShort() }
    private fun silence(sec: Double) = ShortArray((sec * r).toInt())

    @Test fun wavHeader() {
        val wav = AudioUtil.toWav(ShortArray(100))
        assertEquals(244, wav.size)
        assertEquals("RIFF", String(wav, 0, 4))
        assertEquals("WAVE", String(wav, 8, 4))
    }

    @Test fun silence() {
        assertTrue(AudioUtil.isSilent(silence(2.0)))
        assertFalse(AudioUtil.isSilent(silence(1.0) + tone(0.5) + silence(1.0)))
    }

    @Test fun trim() {
        val y = AudioUtil.trimSilence(silence(2.0) + tone(1.0) + silence(2.0))
        assertTrue(y.size / r.toDouble() in 1.0..1.6)
    }

    @Test fun segments() {
        val audio = ShortArray(r * 10)
        val segs = AudioUtil.segments(audio, listOf(0 to "auto", r * 4 to "de", r * 4 + 100 to "en"))
        assertEquals(listOf("auto", "en"), segs.map { it.second })
        assertEquals(r * 4, segs[0].first.size)
    }

    @Test fun plausible() {
        assertTrue(Cleanup.plausible("ahoj ako sa mas", "Ahoj, ako sa máš?"))
        assertFalse(Cleanup.plausible("napíš email", "Samozrejme! " + "x".repeat(200)))
    }

    @Test fun cleanTerms() {
        assertEquals(listOf("bad term", "Hlas"), Stt.cleanTerms(listOf("bad<term>", "Hlas", "Hlas", " "), 10))
    }
}
