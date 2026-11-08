package sk.hlas.dictation

import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.util.concurrent.TimeUnit

class SttException(message: String) : Exception(message)

/** Speech-to-text providers. Mirrors desktop/hlas/stt.py. */
object Stt {
    val http: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(90, TimeUnit.SECONDS)
        .writeTimeout(90, TimeUnit.SECONDS)
        .build()

    private const val PROMPT = "Dictated text. The speaker may switch between Slovak, German and English, " +
        "even mid-sentence. Write every word in the language it was spoken in, with correct diacritics " +
        "(á, ä, č, ď, é, í, ĺ, ľ, ň, ó, ô, ŕ, š, ť, ú, ý, ž, ö, ü, ß). Never translate."

    private val NEAREST = mapOf(
        "czech" to "sk", "polish" to "sk", "slovenian" to "sk", "croatian" to "sk", "serbian" to "sk",
        "ukrainian" to "sk", "russian" to "sk", "dutch" to "de", "luxembourgish" to "de",
        "danish" to "de", "swedish" to "de", "norwegian" to "de", "afrikaans" to "de",
    )
    private val NAMES = mapOf("slovak" to "sk", "german" to "de", "english" to "en")

    fun cleanTerms(terms: List<String>, limit: Int): List<String> =
        terms.map { it.replace(Regex("[<>\\r\\n]"), " ").trim().take(100) }.filter { it.isNotEmpty() }.distinct().take(limit)

    private fun post(url: String, headers: Map<String, String>, form: MultipartBody, provider: String): JSONObject {
        val req = Request.Builder().url(url).post(form).apply { headers.forEach { (k, v) -> header(k, v) } }.build()
        try {
            http.newCall(req).execute().use { resp ->
                val body = resp.body?.string().orEmpty()
                when {
                    resp.code == 401 -> throw SttException("$provider: invalid API key")
                    resp.code == 429 -> throw SttException("$provider: rate limited or out of credit")
                    resp.code >= 400 -> throw SttException("$provider: HTTP ${resp.code}")
                }
                return JSONObject(body)
            }
        } catch (e: java.io.IOException) {
            throw SttException("$provider: network error")
        }
    }

    private fun form(wav: ByteArray, fields: List<Pair<String, String>>): MultipartBody {
        val b = MultipartBody.Builder().setType(MultipartBody.FORM)
        for ((k, v) in fields) b.addFormDataPart(k, v)
        b.addFormDataPart("file", "audio.wav", wav.toRequestBody("audio/wav".toMediaType()))
        return b.build()
    }

    /** Returns (text, detected language). */
    fun transcribe(wav: ByteArray, lang: String, prefs: Prefs): Pair<String, String> {
        val key = prefs.sttKey()
        if (key.isEmpty()) throw SttException("Add an API key in Hlas settings")
        return when (prefs.provider) {
            "local" -> throw SttException("offline mode does not upload audio")
            "elevenlabs" -> elevenlabs(wav, lang, key, prefs)
            "groq" -> groq(wav, lang, key, prefs)
            else -> openai(wav, lang, key, prefs)
        }
    }

    private fun openai(wav: ByteArray, lang: String, key: String, prefs: Prefs): Pair<String, String> {
        val f = mutableListOf("model" to "gpt-transcribe", "prompt" to PROMPT)
        (if (lang == "auto") prefs.languages else listOf(lang)).forEach { f.add("languages[]" to it) }
        cleanTerms(prefs.vocabulary, 100).forEach { f.add("keywords[]" to it) }
        val j = post("https://api.openai.com/v1/audio/transcriptions", mapOf("Authorization" to "Bearer $key"),
            form(wav, f), "OpenAI")
        val langs = j.optJSONArray("languages")
        val detected = if (lang == "auto" && langs != null && langs.length() > 0) langs.getJSONObject(0).optString("code", lang) else lang
        return j.optString("text").trim() to detected
    }

    private fun elevenlabs(wav: ByteArray, lang: String, key: String, prefs: Prefs): Pair<String, String> {
        val f = mutableListOf("model_id" to "scribe_v2", "tag_audio_events" to "false", "timestamps_granularity" to "none")
        if (lang != "auto") f.add("language_code" to lang)
        cleanTerms(prefs.vocabulary, 100).forEach { f.add("keyterms" to it) }
        val j = post("https://api.elevenlabs.io/v1/speech-to-text", mapOf("xi-api-key" to key), form(wav, f), "ElevenLabs")
        val code = j.optString("language_code", lang).let { mapOf("slk" to "sk", "deu" to "de", "eng" to "en")[it] ?: it }
        return j.optString("text").trim() to code
    }

    private fun groq(wav: ByteArray, lang: String, key: String, prefs: Prefs): Pair<String, String> {
        fun call(language: String?): JSONObject {
            val vocab = cleanTerms(prefs.vocabulary, 40).joinToString(", ")
            val f = mutableListOf("model" to "whisper-large-v3", "response_format" to "verbose_json",
                "temperature" to "0", "prompt" to ("Slovenčina, Deutsch, English. " + if (vocab.isEmpty()) "" else "$vocab.").trim())
            if (language != null) f.add("language" to language)
            return post("https://api.groq.com/openai/v1/audio/transcriptions", mapOf("Authorization" to "Bearer $key"),
                form(wav, f), "Groq")
        }
        var j = call(if (lang == "auto") null else lang)
        val name = j.optString("language").lowercase()
        var detected = NAMES[name] ?: name
        if (lang == "auto" && detected !in prefs.languages) {
            detected = NEAREST[name] ?: "en"
            j = call(detected)
        }
        return j.optString("text").trim() to detected
    }
}
