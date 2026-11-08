package sk.hlas.dictation

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Path
import android.graphics.RectF
import android.view.View

/** Round mic button drawn in code: dark when idle, red with a level ring while recording, amber when busy. */
class BubbleView(context: Context) : View(context) {
    var state = Dictation.State.IDLE
        set(v) { field = v; invalidate() }
    var level = 0f
        set(v) { field = v; invalidate() }
    var spin = 0f
        set(v) { field = v; invalidate() }

    private val fill = Paint(Paint.ANTI_ALIAS_FLAG)
    private val glyph = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.WHITE; style = Paint.Style.FILL }
    private val stroke = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.WHITE; style = Paint.Style.STROKE }
    private val ring = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.STROKE }

    override fun onDraw(canvas: Canvas) {
        val w = width.toFloat()
        val cx = w / 2
        val cy = height / 2f
        val r = minOf(width, height) / 2f * 0.82f
        fill.color = when (state) {
            Dictation.State.RECORDING -> Color.parseColor("#EF4444")
            Dictation.State.BUSY, Dictation.State.STARTING -> Color.parseColor("#F59E0B")
            else -> Color.parseColor("#E616161A")
        }
        if (state == Dictation.State.RECORDING) {
            ring.color = Color.parseColor("#66EF4444")
            ring.strokeWidth = r * 0.12f
            canvas.drawCircle(cx, cy, r + r * 0.1f + r * 0.08f * level * 2, ring)
        }
        canvas.drawCircle(cx, cy, r, fill)
        if (state == Dictation.State.BUSY || state == Dictation.State.STARTING) {
            stroke.strokeWidth = r * 0.12f
            val o = RectF(cx - r * 0.5f, cy - r * 0.5f, cx + r * 0.5f, cy + r * 0.5f)
            canvas.drawArc(o, spin, 270f, false, stroke)
            return
        }
        // microphone glyph
        val s = r / 24f
        canvas.drawRoundRect(RectF(cx - 5 * s, cy - 13 * s, cx + 5 * s, cy + 3 * s), 5 * s, 5 * s, glyph)
        stroke.strokeWidth = 2.6f * s
        val arc = Path().apply { addArc(RectF(cx - 9 * s, cy - 8 * s, cx + 9 * s, cy + 9 * s), 0f, 180f) }
        canvas.drawPath(arc, stroke)
        canvas.drawLine(cx, cy + 9 * s, cx, cy + 14 * s, stroke)
    }
}
