package sk.hlas.dictation

import org.junit.Assert.assertEquals
import org.junit.Test
import kotlin.math.PI
import kotlin.math.sin

class LangIdTest {
    @Test fun guess() {
        assertEquals("de", LangId.guess("Können wir das Meeting bitte auf Donnerstag verschieben?"))
        assertEquals("en", LangId.guess("Ask not what your country can do for you"))
        assertEquals("sk", LangId.guess("Potrzebujem, aby si my do piatku posał tu zmluvu"))
        assertEquals("", LangId.guess(""))
    }

    @Test fun pick() {
        assertEquals("sk", LangId.pick("Ahoy Peter. Posse meeting report.", "Pošli mi ten report."))
        assertEquals("base", LangId.pick("Ask not what your country can do for you.", "ask noty k do fory. ask Watt<unk> do fory"))
        assertEquals("base", LangId.pick("Können wir das Meeting bitte auf Donnerstag verschieben?", "Körönvít a métingét autonósták Fesében,"))
    }

    @Test fun splitPhrases() {
        val r = AudioUtil.RATE
        fun tone(sec: Double) = ShortArray((sec * r).toInt()) { (3000 * sin(2 * PI * 220 * it / r)).toInt().toShort() }
        fun gap(sec: Double) = ShortArray((sec * r).toInt())
        val x = tone(3.0) + gap(0.7) + tone(2.0) + gap(0.2) + tone(2.0) + gap(0.7) + tone(0.5)
        val parts = AudioUtil.splitPhrases(x)
        assertEquals(2, parts.size)
        assertEquals(x.size, parts.sumOf { it.size })
    }
}
