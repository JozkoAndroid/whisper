package sk.hlas.dictation

import android.Manifest
import android.app.Activity
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import android.provider.Settings
import android.view.inputmethod.InputMethodManager
import android.widget.ArrayAdapter
import android.widget.Button
import android.widget.CheckBox
import android.widget.EditText
import android.widget.Spinner
import android.widget.Toast

class SettingsActivity : Activity() {
    private lateinit var prefs: Prefs

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.settings)
        prefs = Prefs(this)

        val provider = findViewById<Spinner>(R.id.provider)
        provider.adapter = ArrayAdapter(this, android.R.layout.simple_spinner_dropdown_item,
            listOf("OpenAI gpt-transcribe (best for mixing)", "ElevenLabs Scribe v2", "Groq Whisper (fastest)"))
        provider.setSelection(Prefs.PROVIDERS.indexOf(prefs.provider).coerceAtLeast(0))

        val language = findViewById<Spinner>(R.id.language)
        language.adapter = ArrayAdapter(this, android.R.layout.simple_spinner_dropdown_item,
            listOf("Auto: Slovak / German / English", "Slovak", "German", "English"))
        language.setSelection(Prefs.LANGS.indexOf(prefs.language).coerceAtLeast(0))

        val openai = findViewById<EditText>(R.id.openai_key).apply { setText(prefs.openaiKey) }
        val eleven = findViewById<EditText>(R.id.elevenlabs_key).apply { setText(prefs.elevenlabsKey) }
        val groq = findViewById<EditText>(R.id.groq_key).apply { setText(prefs.groqKey) }
        val anthropic = findViewById<EditText>(R.id.anthropic_key).apply { setText(prefs.anthropicKey) }
        val model = findViewById<EditText>(R.id.cleanup_model).apply { setText(prefs.cleanupModel) }
        val cleanup = findViewById<CheckBox>(R.id.cleanup).apply { isChecked = prefs.cleanup }
        val vocab = findViewById<EditText>(R.id.vocabulary).apply { setText(prefs.vocabulary.joinToString("\n")) }

        findViewById<Button>(R.id.btn_mic).setOnClickListener {
            requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO), 1)
        }
        findViewById<Button>(R.id.btn_enable).setOnClickListener {
            startActivity(Intent(Settings.ACTION_INPUT_METHOD_SETTINGS))
        }
        findViewById<Button>(R.id.btn_pick).setOnClickListener {
            (getSystemService(Context.INPUT_METHOD_SERVICE) as InputMethodManager).showInputMethodPicker()
        }
        findViewById<Button>(R.id.btn_save).setOnClickListener {
            prefs.provider = Prefs.PROVIDERS[provider.selectedItemPosition]
            prefs.language = Prefs.LANGS[language.selectedItemPosition]
            prefs.openaiKey = openai.text.toString()
            prefs.elevenlabsKey = eleven.text.toString()
            prefs.groqKey = groq.text.toString()
            prefs.anthropicKey = anthropic.text.toString()
            prefs.cleanupModel = model.text.toString().ifBlank { "claude-opus-5-5" }
            prefs.cleanup = cleanup.isChecked
            prefs.vocabulary = vocab.text.toString().lines()
            Toast.makeText(this, "Saved", Toast.LENGTH_SHORT).show()
        }
        updateMicButton()
    }

    override fun onResume() {
        super.onResume()
        updateMicButton()
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        updateMicButton()
    }

    private fun updateMicButton() {
        val granted = checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED
        findViewById<Button>(R.id.btn_mic).apply {
            text = if (granted) "1. Microphone allowed ✓" else "1. Allow microphone"
            isEnabled = !granted
        }
    }
}
