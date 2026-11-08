package sk.hlas.dictation

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Handler
import android.os.Looper
import java.util.concurrent.Executors

/** Recording state shared by the bubble. */
object Dictation {
    enum class State { IDLE, STARTING, RECORDING, BUSY }

    interface Listener {
        fun onState(state: State, message: String)
        fun onText(text: String)
    }

    private val main = Handler(Looper.getMainLooper())
    private val worker = Executors.newSingleThreadExecutor()
    private val recorder = Recorder()
    var listener: Listener? = null
    var state = State.IDLE
        private set
    var lang = "auto"
    var coding = false
    val level get() = recorder.level
    val seconds get() = recorder.seconds
    private var pendingStart = false

    private fun set(s: State, msg: String = "") {
        state = s
        main.post { listener?.onState(s, msg) }
    }

    fun notReadyReason(context: Context, prefs: Prefs): String? = when {
        context.checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED ->
            "Open Hlas and allow the microphone"
        prefs.provider == "local" && !Models.ready(context) -> "Open Hlas and download the offline models"
        prefs.sttKey().isEmpty() -> "Open Hlas and add your API key"
        else -> null
    }

    fun toggle(context: Context) {
        when (state) {
            State.IDLE -> start(context)
            State.RECORDING -> stop(context)
            else -> Unit
        }
    }

    fun start(context: Context) {
        val prefs = Prefs(context)
        notReadyReason(context, prefs)?.let { set(State.IDLE, it); return }
        if (!MicService.running) {
            // After a reboot the mic service is gone; bring it back through a one-frame invisible screen.
            pendingStart = true
            set(State.STARTING, "Starting…")
            context.startActivity(Intent(context, StartMicActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_NO_ANIMATION))
            main.postDelayed({
                if (pendingStart) { pendingStart = false; set(State.IDLE, "Open Hlas once to enable the microphone") }
            }, 3000)
            return
        }
        try {
            recorder.start(lang)
            set(State.RECORDING)
        } catch (e: Exception) {
            set(State.IDLE, e.message ?: "Microphone error")
        }
    }

    fun onMicReady(context: Context) {
        if (pendingStart) {
            pendingStart = false
            main.postDelayed({ start(context) }, 150)
        }
    }

    fun markLanguage(l: String) {
        lang = l
        if (state == State.RECORDING) recorder.mark(l)
    }

    fun cancel() {
        if (state == State.RECORDING) recorder.cancel()
        set(State.IDLE)
    }

    fun stop(context: Context) {
        if (state != State.RECORDING) return
        val segments = recorder.stop()
        if (segments.sumOf { it.first.size } < AudioUtil.RATE * 3 / 10) { set(State.IDLE); return }
        set(State.BUSY)
        val prefs = Prefs(context)
        val c = coding
        val app = context.applicationContext
        worker.execute {
            val result = runCatching { Pipeline.run(app, segments, prefs, c) }
            main.post {
                result.onSuccess { text ->
                    if (text.isBlank()) set(State.IDLE, "No speech") else { listener?.onText(text); set(State.IDLE) }
                }.onFailure { set(State.IDLE, it.message ?: "Error") }
            }
        }
    }
}
