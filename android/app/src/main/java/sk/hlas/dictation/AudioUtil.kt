package sk.hlas.dictation

import java.io.ByteArrayOutputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.math.sqrt

/** Same rules as the desktop app (desktop/hlas/audio.py). 16 kHz mono PCM16. */
object AudioUtil {
    const val RATE = 16_000
    private const val THRESHOLD = 120.0
    private const val FRAME = RATE / 50 // 20 ms

    fun toWav(samples: ShortArray): ByteArray {
        val dataLen = samples.size * 2
        val header = ByteBuffer.allocate(44).order(ByteOrder.LITTLE_ENDIAN).apply {
            put("RIFF".toByteArray()); putInt(36 + dataLen); put("WAVE".toByteArray())
            put("fmt ".toByteArray()); putInt(16); putShort(1); putShort(1)
            putInt(RATE); putInt(RATE * 2); putShort(2); putShort(16)
            put("data".toByteArray()); putInt(dataLen)
        }
        val body = ByteBuffer.allocate(dataLen).order(ByteOrder.LITTLE_ENDIAN)
        for (s in samples) body.putShort(s)
        return ByteArrayOutputStream(44 + dataLen).apply { write(header.array()); write(body.array()) }.toByteArray()
    }

    private fun frameEnergies(x: ShortArray): DoubleArray {
        val n = x.size / FRAME
        return DoubleArray(n) { f ->
            var sum = 0.0
            for (i in f * FRAME until (f + 1) * FRAME) sum += x[i].toDouble() * x[i]
            sqrt(sum / FRAME)
        }
    }

    fun rmsLevel(x: ShortArray, len: Int = x.size): Float {
        if (len == 0) return 0f
        var sum = 0.0
        for (i in 0 until len) sum += x[i].toDouble() * x[i]
        return (sqrt(sum / len) / 4000.0).coerceIn(0.0, 1.0).toFloat()
    }

    /** No real speech: skip it (Whisper-style models hallucinate on silence). */
    fun isSilent(x: ShortArray): Boolean {
        if (x.size < RATE / 4) return true
        return frameEnergies(x).count { it > THRESHOLD * 2.5 } < 8
    }

    fun trimSilence(x: ShortArray, padSeconds: Double = 0.25): ShortArray {
        val e = frameEnergies(x)
        val first = e.indexOfFirst { it > THRESHOLD * 2.5 }
        if (first < 0) return ShortArray(0)
        val last = e.indexOfLast { it > THRESHOLD * 2.5 }
        val pad = (padSeconds * RATE).toInt()
        val start = maxOf(0, first * FRAME - pad)
        val end = minOf(x.size, (last + 1) * FRAME + pad)
        return x.copyOfRange(start, end)
    }

    /** Split [audio] at language marks; marks closer than 0.5 s merge (last wins). */
    fun segments(audio: ShortArray, marks: List<Pair<Int, String>>): List<Pair<ShortArray, String>> {
        val cleaned = mutableListOf<Pair<Int, String>>()
        for ((idx, lang) in marks.sortedBy { it.first }) {
            if (cleaned.isNotEmpty() && idx - cleaned.last().first < RATE / 2) {
                cleaned[cleaned.size - 1] = cleaned.last().first to lang
            } else cleaned.add(idx to lang)
        }
        if (cleaned.isEmpty()) cleaned.add(0 to "auto")
        cleaned[0] = 0 to cleaned[0].second
        return cleaned.mapIndexedNotNull { i, (start, lang) ->
            val end = if (i + 1 < cleaned.size) cleaned[i + 1].first else audio.size
            if (end > start) audio.copyOfRange(start, end) to lang else null
        }
    }

    /** Cut at pauses (>= 0.45 s) so each phrase can go to the right language model. */
    fun splitPhrases(x: ShortArray, minPause: Double = 0.45, minPhrase: Double = 1.5): List<ShortArray> {
        val e = frameEnergies(x)
        if (e.isEmpty()) return listOf(x)
        val cuts = mutableListOf<Int>()
        var runStart = -1
        for (i in e.indices) {
            val quiet = e[i] < THRESHOLD * 2.5
            if (quiet && runStart < 0) runStart = i
            else if (!quiet && runStart >= 0) {
                if ((i - runStart) * FRAME >= minPause * RATE) cuts.add(((runStart + i) / 2) * FRAME)
                runStart = -1
            }
        }
        val bounds = listOf(0) + cuts + listOf(x.size)
        val merged = mutableListOf<ShortArray>()
        for (k in 0 until bounds.size - 1) {
            val p = x.copyOfRange(bounds[k], bounds[k + 1])
            if (p.isEmpty()) continue
            if (merged.isNotEmpty() && p.size < minPhrase * RATE) merged[merged.size - 1] = merged.last() + p
            else merged.add(p)
        }
        if (merged.size > 1 && merged[0].size < minPhrase * RATE) {
            merged[1] = merged[0] + merged[1]
            merged.removeAt(0)
        }
        return merged
    }
}
