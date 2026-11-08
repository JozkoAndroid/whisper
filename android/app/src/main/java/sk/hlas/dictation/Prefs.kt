package sk.hlas.dictation

import android.content.Context

/** Settings, stored in the app's private SharedPreferences. */
class Prefs(context: Context) {
    private val p = context.getSharedPreferences("hlas", Context.MODE_PRIVATE)

    var provider: String
        get() = p.getString("provider", "openai") ?: "openai"
        set(v) = p.edit().putString("provider", v).apply()
    var openaiKey: String
        get() = p.getString("openai_key", "") ?: ""
        set(v) = p.edit().putString("openai_key", v.trim()).apply()
    var elevenlabsKey: String
        get() = p.getString("elevenlabs_key", "") ?: ""
        set(v) = p.edit().putString("elevenlabs_key", v.trim()).apply()
    var groqKey: String
        get() = p.getString("groq_key", "") ?: ""
        set(v) = p.edit().putString("groq_key", v.trim()).apply()
    var anthropicKey: String
        get() = p.getString("anthropic_key", "") ?: ""
        set(v) = p.edit().putString("anthropic_key", v.trim()).apply()
    var cleanup: Boolean
        get() = p.getBoolean("cleanup", true)
        set(v) = p.edit().putBoolean("cleanup", v).apply()
    var cleanupModel: String
        get() = p.getString("cleanup_model", "claude-opus-5-5") ?: "claude-opus-5-5"
        set(v) = p.edit().putString("cleanup_model", v.trim()).apply()
    var language: String
        get() = p.getString("language", "auto") ?: "auto"
        set(v) = p.edit().putString("language", v).apply()
    var vocabulary: List<String>
        get() = (p.getString("vocabulary", "") ?: "").lines().map { it.trim() }.filter { it.isNotEmpty() }
        set(v) = p.edit().putString("vocabulary", v.joinToString("\n")).apply()

    val languages: List<String> get() = listOf("sk", "de", "en")

    fun sttKey(): String = when (provider) {
        "elevenlabs" -> elevenlabsKey
        "groq" -> groqKey
        else -> openaiKey
    }

    companion object {
        val LANGS = listOf("auto", "sk", "de", "en")
        val PROVIDERS = listOf("openai", "elevenlabs", "groq")
        fun label(lang: String) = if (lang == "auto") "SK·DE·EN" else lang.uppercase()
    }
}
