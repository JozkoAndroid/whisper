package sk.hlas.dictation

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.inputmethodservice.InputMethodService
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.view.HapticFeedbackConstants
import android.view.KeyEvent
import android.view.MotionEvent
import android.view.View
import android.view.inputmethod.EditorInfo
import android.view.inputmethod.InputMethodManager
import android.widget.TextView
import java.util.concurrent.Executors

/**
 * Voice keyboard. Tap the mic to start/stop (hands-free), or hold it and
 * release to finish. Tap the language chip while talking to switch language
 * from that point on.
 */
class HlasIme : InputMethodService() {
    private lateinit var prefs: Prefs
    private val recorder = Recorder()
    private val main = Handler(Looper.getMainLooper())
    private val worker = Executors.newSingleThreadExecutor()
    private var lang = "auto"
    private var coding = false
    private var downAt = 0L
    private var startedOnThisTouch = false
    private var busy = false

    private var micView: View? = null
    private var langView: TextView? = null
    private var statusView: TextView? = null

    override fun onCreate() {
        super.onCreate()
        prefs = Prefs(this)
        lang = prefs.language
    }

    override fun onCreateInputView(): View {
        val v = layoutInflater.inflate(R.layout.keyboard, null)
        micView = v.findViewById(R.id.mic)
        langView = v.findViewById(R.id.lang)
        statusView = v.findViewById(R.id.status)

        langView!!.setOnClickListener { cycleLanguage() }
        v.findViewById<View>(R.id.settings).setOnClickListener { openSettings() }
        micView!!.setOnTouchListener { view, e -> onMicTouch(view, e) }
        v.findViewById<View>(R.id.space).setOnClickListener { currentInputConnection?.commitText(" ", 1) }
        v.findViewById<View>(R.id.enter).setOnClickListener { enter() }
        v.findViewById<View>(R.id.next_ime).setOnClickListener { nextKeyboard() }
        v.findViewById<View>(R.id.next_ime).setOnLongClickListener {
            (getSystemService(Context.INPUT_METHOD_SERVICE) as InputMethodManager).showInputMethodPicker(); true
        }
        setupBackspace(v.findViewById(R.id.backspace))
        refresh()
        return v
    }

    override fun onStartInputView(info: EditorInfo?, restarting: Boolean) {
        super.onStartInputView(info, restarting)
        prefs = Prefs(this)
        coding = info?.packageName in CODING_APPS
        if (!recorder.recording) lang = prefs.language
        refresh()
    }

    override fun onFinishInputView(finishingInput: Boolean) {
        if (recorder.recording) {
            recorder.cancel()
            status("Cancelled")
        }
        super.onFinishInputView(finishingInput)
    }

    // --- mic -------------------------------------------------------------

    private fun onMicTouch(view: View, e: MotionEvent): Boolean {
        when (e.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                downAt = SystemClock.uptimeMillis()
                startedOnThisTouch = false
                if (!recorder.recording && !busy) {
                    startedOnThisTouch = startRecording()
                }
                view.performHapticFeedback(HapticFeedbackConstants.KEYBOARD_TAP)
            }
            MotionEvent.ACTION_UP -> {
                val held = SystemClock.uptimeMillis() - downAt
                // Hold-to-talk: release ends it. Short tap: keep recording until the next tap.
                if (recorder.recording && (!startedOnThisTouch || held >= 450)) stopRecording()
                else if (recorder.recording) status("Listening… tap to finish")
            }
            MotionEvent.ACTION_CANCEL -> if (recorder.recording && startedOnThisTouch) stopRecording()
        }
        return true
    }

    private fun startRecording(): Boolean {
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            status("Allow the microphone in Hlas settings")
            openSettings()
            return false
        }
        if (prefs.sttKey().isEmpty()) {
            status("Add an API key in settings")
            openSettings()
            return false
        }
        return try {
            recorder.start(lang)
            micView?.setBackgroundResource(R.drawable.mic_rec)
            tick()
            true
        } catch (e: Exception) {
            status(e.message ?: "Microphone error")
            false
        }
    }

    private fun tick() {
        if (!recorder.recording) return
        val s = recorder.seconds.toInt()
        status("${Prefs.label(lang)}  ${s / 60}:${"%02d".format(s % 60)}")
        val scale = 1f + 0.18f * recorder.level
        micView?.scaleX = scale
        micView?.scaleY = scale
        main.postDelayed({ tick() }, 50)
    }

    private fun stopRecording() {
        val segments = recorder.stop()
        micView?.apply { setBackgroundResource(R.drawable.mic_idle); scaleX = 1f; scaleY = 1f }
        micView?.performHapticFeedback(HapticFeedbackConstants.KEYBOARD_TAP)
        if (segments.sumOf { it.first.size } < AudioUtil.RATE * 3 / 10) {
            status("")
            return
        }
        busy = true
        status("Transcribing…")
        val p = prefs
        val c = coding
        worker.execute {
            val result = runCatching { Pipeline.run(segments, p, c) }
            main.post {
                busy = false
                result.onSuccess { text ->
                    if (text.isEmpty()) status("No speech") else { insert(text); status("") }
                }.onFailure { status(it.message ?: "Error") }
            }
        }
    }

    private fun insert(text: String) {
        val ic = currentInputConnection ?: return
        val before = ic.getTextBeforeCursor(1, 0)?.toString().orEmpty()
        val needsSpace = before.isNotEmpty() && !before.last().isWhitespace() &&
            text.firstOrNull()?.let { it.isLetterOrDigit() } == true
        ic.commitText((if (needsSpace) " " else "") + text, 1)
    }

    // --- other keys --------------------------------------------------------

    private fun cycleLanguage() {
        val i = Prefs.LANGS.indexOf(lang)
        lang = Prefs.LANGS[(i + 1) % Prefs.LANGS.size]
        if (recorder.recording) recorder.mark(lang) else prefs.language = lang
        refresh()
    }

    private fun enter() {
        val ic = currentInputConnection ?: return
        val info = currentInputEditorInfo
        val action = (info?.imeOptions ?: 0) and EditorInfo.IME_MASK_ACTION
        val noAction = ((info?.imeOptions ?: 0) and EditorInfo.IME_FLAG_NO_ENTER_ACTION) != 0
        if (!noAction && action != EditorInfo.IME_ACTION_NONE && action != EditorInfo.IME_ACTION_UNSPECIFIED) {
            ic.performEditorAction(action)
        } else {
            ic.sendKeyEvent(KeyEvent(KeyEvent.ACTION_DOWN, KeyEvent.KEYCODE_ENTER))
            ic.sendKeyEvent(KeyEvent(KeyEvent.ACTION_UP, KeyEvent.KEYCODE_ENTER))
        }
    }

    private fun setupBackspace(v: View) {
        val repeat = object : Runnable {
            override fun run() { deleteOne(); main.postDelayed(this, 60) }
        }
        v.setOnTouchListener { view, e ->
            when (e.actionMasked) {
                MotionEvent.ACTION_DOWN -> {
                    deleteOne(); view.performHapticFeedback(HapticFeedbackConstants.KEYBOARD_TAP)
                    main.postDelayed(repeat, 400)
                }
                MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> main.removeCallbacks(repeat)
            }
            true
        }
    }

    private fun deleteOne() {
        val ic = currentInputConnection ?: return
        val selected = ic.getSelectedText(0)
        if (!selected.isNullOrEmpty()) ic.commitText("", 1)
        else {
            ic.sendKeyEvent(KeyEvent(KeyEvent.ACTION_DOWN, KeyEvent.KEYCODE_DEL))
            ic.sendKeyEvent(KeyEvent(KeyEvent.ACTION_UP, KeyEvent.KEYCODE_DEL))
        }
    }

    @Suppress("DEPRECATION")
    private fun nextKeyboard() {
        if (Build.VERSION.SDK_INT >= 28) {
            if (!switchToNextInputMethod(false)) {
                (getSystemService(Context.INPUT_METHOD_SERVICE) as InputMethodManager).showInputMethodPicker()
            }
        } else {
            val imm = getSystemService(Context.INPUT_METHOD_SERVICE) as InputMethodManager
            val token = window?.window?.attributes?.token
            if (token == null || !imm.switchToNextInputMethod(token, false)) imm.showInputMethodPicker()
        }
    }

    private fun openSettings() {
        startActivity(Intent(this, SettingsActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    }

    private fun refresh() {
        langView?.text = Prefs.label(lang)
        if (!recorder.recording && !busy) {
            status(if (prefs.sttKey().isEmpty()) "Add an API key in settings" else "Tap or hold to talk")
        }
    }

    private fun status(text: String) { statusView?.text = text }

    companion object {
        /** Apps where the cleanup uses coding style. */
        val CODING_APPS = setOf(
            "com.termux", "com.server.auditor.ssh.client", "org.connectbot", "com.github.android",
            "com.anthropic.claude", "com.foxdebug.acodefree", "com.foxdebug.acode", "com.rhmsoft.code",
        )
    }
}
