package sk.hlas.dictation

import android.accessibilityservice.AccessibilityService
import android.content.ClipData
import android.content.ClipboardManager
import android.graphics.Color
import android.graphics.PixelFormat
import android.graphics.Rect
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.util.TypedValue
import android.view.Gravity
import android.view.HapticFeedbackConstants
import android.view.MotionEvent
import android.view.View
import android.view.ViewConfiguration
import android.view.WindowManager
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import android.view.accessibility.AccessibilityWindowInfo
import android.widget.LinearLayout
import android.widget.TextView
import kotlin.math.abs

/**
 * Floating mic bubble that appears above whatever keyboard you use (Samsung,
 * Gboard...) when a text field is focused, like Wispr Flow on Android.
 * Tap to talk, tap again to finish (or hold and release). Tap the language
 * chip to switch language. The text is typed into the focused field.
 */
class BubbleService : AccessibilityService(), Dictation.Listener {
    private val main = Handler(Looper.getMainLooper())
    private lateinit var wm: WindowManager
    private var root: LinearLayout? = null
    private var bubble: BubbleView? = null
    private var chip: TextView? = null
    private var params: WindowManager.LayoutParams? = null
    private var shown = false
    private var message: String? = null
    private var target: AccessibilityNodeInfo? = null
    private val prefs by lazy { Prefs(this) }

    private fun dp(v: Float) = TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, v, resources.displayMetrics).toInt()

    override fun onServiceConnected() {
        super.onServiceConnected()
        wm = getSystemService(WINDOW_SERVICE) as WindowManager
        Dictation.listener = this
        Dictation.lang = prefs.language
        buildOverlay()
        // Warm up the offline models so the first dictation is quick.
        if (prefs.provider == "local" && Models.ready(this)) {
            Thread { runCatching { LocalEngine.preload(Models.root(this)) } }.start()
        }
    }

    override fun onDestroy() {
        if (Dictation.listener === this) Dictation.listener = null
        root?.let { runCatching { wm.removeView(it) } }
        super.onDestroy()
    }

    override fun onInterrupt() {}

    // --- overlay -------------------------------------------------------------

    private fun buildOverlay() {
        val size = dp(52f)
        val b = BubbleView(this)
        val c = TextView(this).apply {
            setTextColor(Color.WHITE)
            textSize = 12f
            setPadding(dp(10f), dp(5f), dp(10f), dp(5f))
            maxWidth = dp(220f)
            background = GradientDrawable().apply { cornerRadius = dp(14f).toFloat(); setColor(Color.parseColor("#E616161A")) }
            setOnClickListener { cycleLanguage() }
        }
        val layout = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            addView(c, LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT)
                .apply { rightMargin = dp(6f) })
            addView(b, LinearLayout.LayoutParams(size, size))
        }
        b.setOnTouchListener(BubbleTouch())
        params = WindowManager.LayoutParams(
            WindowManager.LayoutParams.WRAP_CONTENT, WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
            PixelFormat.TRANSLUCENT,
        ).apply { gravity = Gravity.TOP or Gravity.START }
        layout.visibility = View.GONE
        wm.addView(layout, params)
        root = layout
        bubble = b
        chip = c
        refreshChip()
    }

    private fun show(x: Int, y: Int) {
        val p = params ?: return
        val r = root ?: return
        if (p.x != x || p.y != y) { p.x = x; p.y = y; runCatching { wm.updateViewLayout(r, p) } }
        if (!shown) { r.visibility = View.VISIBLE; shown = true }
    }

    private fun hide() {
        if (shown && Dictation.state == Dictation.State.IDLE) { root?.visibility = View.GONE; shown = false }
    }

    private fun refreshChip() {
        chip?.text = message ?: when (Dictation.state) {
            Dictation.State.RECORDING -> {
                val s = Dictation.seconds.toInt()
                "${Prefs.label(Dictation.lang)}  ${s / 60}:${"%02d".format(s % 60)}"
            }
            Dictation.State.BUSY -> "Writing…"
            else -> Prefs.label(Dictation.lang)
        }
    }

    private fun cycleLanguage() {
        val i = Prefs.LANGS.indexOf(Dictation.lang)
        val next = Prefs.LANGS[(i + 1) % Prefs.LANGS.size]
        Dictation.markLanguage(next)
        if (Dictation.state == Dictation.State.IDLE) prefs.language = next
        refreshChip()
    }

    private val tick = object : Runnable {
        var spin = 0f
        override fun run() {
            val st = Dictation.state
            bubble?.state = st
            if (st == Dictation.State.RECORDING) bubble?.level = Dictation.level
            if (st == Dictation.State.BUSY || st == Dictation.State.STARTING) { spin = (spin + 18f) % 360f; bubble?.spin = spin }
            refreshChip()
            if (st != Dictation.State.IDLE) main.postDelayed(this, 50)
        }
    }

    // --- Dictation.Listener -----------------------------------------------------

    override fun onState(state: Dictation.State, message: String) {
        bubble?.state = state
        if (message.isNotEmpty()) {
            this.message = message
            main.postDelayed({ this.message = null; refreshChip() }, 3000)
        }
        main.removeCallbacks(tick)
        main.post(tick)
        if (state == Dictation.State.IDLE) main.postDelayed({ update() }, 300)
    }

    override fun onText(text: String) {
        val ok = insert(text)
        if (!ok) {
            (getSystemService(CLIPBOARD_SERVICE) as ClipboardManager).setPrimaryClip(ClipData.newPlainText("Hlas", text))
            message = "Copied: paste it"
            main.postDelayed({ message = null; refreshChip() }, 3000)
        }
    }

    // --- touches on the bubble -----------------------------------------------------

    private inner class BubbleTouch : View.OnTouchListener {
        private var downX = 0f
        private var downY = 0f
        private var startX = 0
        private var startY = 0
        private var downAt = 0L
        private var dragging = false
        private var startedHere = false
        private val slop = ViewConfiguration.get(this@BubbleService).scaledTouchSlop

        override fun onTouch(v: View, e: MotionEvent): Boolean {
            val p = params ?: return false
            when (e.actionMasked) {
                MotionEvent.ACTION_DOWN -> {
                    downX = e.rawX; downY = e.rawY; startX = p.x; startY = p.y
                    downAt = SystemClock.uptimeMillis(); dragging = false; startedHere = false
                    if (Dictation.state == Dictation.State.IDLE) {
                        target = focusedEditable()
                        Dictation.coding = target?.packageName?.toString() in HlasIme.CODING_APPS
                        Dictation.start(this@BubbleService)
                        startedHere = true
                    }
                    v.performHapticFeedback(HapticFeedbackConstants.KEYBOARD_TAP)
                }
                MotionEvent.ACTION_MOVE -> {
                    val dx = e.rawX - downX
                    val dy = e.rawY - downY
                    if (!dragging && (abs(dx) > slop * 2 || abs(dy) > slop * 2)) {
                        dragging = true
                        if (startedHere) Dictation.cancel()  // it was a drag, not a tap
                    }
                    if (dragging) {
                        p.x = (startX + dx).toInt(); p.y = (startY + dy).toInt()
                        runCatching { wm.updateViewLayout(root, p) }
                    }
                }
                MotionEvent.ACTION_UP -> {
                    if (dragging) {
                        saveOffset(p.x, p.y)
                    } else {
                        val held = SystemClock.uptimeMillis() - downAt
                        // Tap: start (keeps recording) / stop. Hold and release: push-to-talk.
                        if (!startedHere || held >= 450) Dictation.stop(this@BubbleService)
                    }
                }
                MotionEvent.ACTION_CANCEL -> if (startedHere && !dragging) Dictation.stop(this@BubbleService)
            }
            return true
        }
    }

    // Position: the bubble sits above the keyboard on the right; dragging stores an offset.
    private var lastIme = Rect()

    private fun saveOffset(x: Int, y: Int) {
        val screen = resources.displayMetrics
        val r = root ?: return
        val fromRight = screen.widthPixels - x - r.width
        val aboveIme = (if (lastIme.isEmpty) screen.heightPixels else lastIme.top) - y - r.height
        getSharedPreferences("hlas", MODE_PRIVATE).edit()
            .putInt("bubble_right", fromRight).putInt("bubble_above", aboveIme).apply()
    }

    // --- when to show ------------------------------------------------------------------

    private val updateRunnable = Runnable { update() }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        if (event?.packageName == packageName) return
        main.removeCallbacks(updateRunnable)
        main.postDelayed(updateRunnable, 120)
    }

    private fun imeBounds(): Rect? {
        val ime = runCatching { windows }.getOrNull()?.firstOrNull { it.type == AccessibilityWindowInfo.TYPE_INPUT_METHOD }
            ?: return null
        return Rect().also { ime.getBoundsInScreen(it) }
    }

    private fun focusedEditable(): AccessibilityNodeInfo? {
        val node = runCatching { findFocus(AccessibilityNodeInfo.FOCUS_INPUT) }.getOrNull() ?: return null
        if (node.packageName == packageName) return null
        return if (node.isEditable && !node.isPassword) node else null
    }

    private fun update() {
        if (root == null) return
        val busy = Dictation.state != Dictation.State.IDLE
        val ime = imeBounds()
        val field = focusedEditable()
        if (!busy && (ime == null || field == null)) { hide(); return }
        val screen = resources.displayMetrics
        val r = root!!
        r.measure(View.MeasureSpec.UNSPECIFIED, View.MeasureSpec.UNSPECIFIED)
        val w = r.measuredWidth
        val h = r.measuredHeight
        if (ime != null) lastIme = ime
        val sp = getSharedPreferences("hlas", MODE_PRIVATE)
        val fromRight = sp.getInt("bubble_right", dp(10f))
        val above = sp.getInt("bubble_above", dp(8f))
        val bottom = if (lastIme.isEmpty) screen.heightPixels - dp(80f) else lastIme.top
        val x = (screen.widthPixels - w - fromRight).coerceIn(0, maxOf(0, screen.widthPixels - w))
        val y = (bottom - h - above).coerceIn(0, maxOf(0, screen.heightPixels - h))
        show(x, y)
    }

    // --- typing the text into the field ------------------------------------------------------

    private fun insert(text: String): Boolean {
        val node = focusedEditable() ?: target?.takeIf { it.refresh() && it.isEditable } ?: return false
        node.refresh()
        val showingHint = Build.VERSION.SDK_INT >= 26 && node.isShowingHintText
        val current = if (showingHint) "" else node.text?.toString().orEmpty()
        var s = node.textSelectionStart
        var e = node.textSelectionEnd
        if (s < 0 || e < 0 || s > current.length || e > current.length) { s = current.length; e = current.length }
        if (s > e) { val t = s; s = e; e = t }
        val needsSpace = s > 0 && !current[s - 1].isWhitespace() && text.firstOrNull()?.isLetterOrDigit() == true
        val piece = (if (needsSpace) " " else "") + text
        val isPlainEditText = node.className?.toString()?.contains("EditText") == true
        if (isPlainEditText) {
            val args = Bundle().apply {
                putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE,
                    current.substring(0, s) + piece + current.substring(e))
            }
            if (node.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args)) {
                val cursor = s + piece.length
                node.performAction(AccessibilityNodeInfo.ACTION_SET_SELECTION, Bundle().apply {
                    putInt(AccessibilityNodeInfo.ACTION_ARGUMENT_SELECTION_START_INT, cursor)
                    putInt(AccessibilityNodeInfo.ACTION_ARGUMENT_SELECTION_END_INT, cursor)
                })
                return true
            }
        }
        // Web pages and custom editors: paste at the cursor.
        (getSystemService(CLIPBOARD_SERVICE) as ClipboardManager).setPrimaryClip(ClipData.newPlainText("Hlas", piece))
        return node.performAction(AccessibilityNodeInfo.ACTION_PASTE)
    }
}
