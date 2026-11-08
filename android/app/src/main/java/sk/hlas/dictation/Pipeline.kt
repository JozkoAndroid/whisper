package sk.hlas.dictation

import java.util.concurrent.Callable
import java.util.concurrent.Executors

/** segments -> speech-to-text (offline, or online in parallel) -> cleanup -> text. */
object Pipeline {
    private val pool = Executors.newFixedThreadPool(4)

    fun run(context: android.content.Context, segments: List<Pair<ShortArray, String>>, prefs: Prefs,
            coding: Boolean): String {
        val jobs = segments.map { (audio, lang) -> AudioUtil.trimSilence(audio) to lang }
            .filter { !AudioUtil.isSilent(it.first) }
        if (jobs.isEmpty()) return ""
        if (prefs.provider == "local") {
            val raw = jobs.map { (audio, lang) -> LocalEngine.transcribe(Models.root(context), audio, lang).first }
                .filter { it.isNotBlank() }.joinToString(" ")
            return Cleanup.clean(raw, prefs, coding)
        }
        val futures = jobs.map { (audio, lang) -> pool.submit(Callable { Stt.transcribe(AudioUtil.toWav(audio), lang, prefs) }) }
        val raw = futures.map {
            try { it.get().first } catch (e: java.util.concurrent.ExecutionException) { throw e.cause ?: e }
        }.filter { it.isNotBlank() }.joinToString(" ")
        return Cleanup.clean(raw, prefs, coding)
    }
}
