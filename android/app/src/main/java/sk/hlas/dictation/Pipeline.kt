package sk.hlas.dictation

import java.util.concurrent.Callable
import java.util.concurrent.Executors

/** segments -> speech-to-text (in parallel) -> cleanup -> text. */
object Pipeline {
    private val pool = Executors.newFixedThreadPool(4)

    fun run(segments: List<Pair<ShortArray, String>>, prefs: Prefs, coding: Boolean): String {
        val jobs = segments.map { (audio, lang) -> AudioUtil.trimSilence(audio) to lang }
            .filter { !AudioUtil.isSilent(it.first) }
        if (jobs.isEmpty()) return ""
        val futures = jobs.map { (audio, lang) -> pool.submit(Callable { Stt.transcribe(AudioUtil.toWav(audio), lang, prefs) }) }
        val raw = futures.map {
            try { it.get().first } catch (e: java.util.concurrent.ExecutionException) { throw e.cause ?: e }
        }.filter { it.isNotBlank() }.joinToString(" ")
        return Cleanup.clean(raw, prefs, coding)
    }
}
