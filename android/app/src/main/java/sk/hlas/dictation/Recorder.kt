package sk.hlas.dictation

import android.annotation.SuppressLint
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder

/** Microphone capture with language markers (tap the language chip while talking). */
class Recorder {
    private var record: AudioRecord? = null
    private var thread: Thread? = null
    @Volatile private var running = false
    private val lock = Any()
    private var buffer = ShortArray(AudioUtil.RATE * 60)
    private var count = 0
    private val marks = mutableListOf<Pair<Int, String>>()
    @Volatile var level = 0f
        private set

    val recording get() = running
    val seconds: Double get() = synchronized(lock) { count.toDouble() / AudioUtil.RATE }

    @SuppressLint("MissingPermission") // checked by the caller
    fun start(lang: String) {
        val min = AudioRecord.getMinBufferSize(AudioUtil.RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
        val rec = AudioRecord(MediaRecorder.AudioSource.VOICE_RECOGNITION, AudioUtil.RATE,
            AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, maxOf(min, AudioUtil.RATE))
        if (rec.state != AudioRecord.STATE_INITIALIZED) {
            rec.release()
            throw IllegalStateException("Microphone unavailable")
        }
        synchronized(lock) { count = 0; marks.clear(); marks.add(0 to lang) }
        record = rec
        running = true
        rec.startRecording()
        thread = Thread {
            val chunk = ShortArray(AudioUtil.RATE / 20)
            while (running) {
                val n = rec.read(chunk, 0, chunk.size)
                if (n <= 0) continue
                synchronized(lock) {
                    if (count + n > buffer.size) buffer = buffer.copyOf(buffer.size * 2)
                    System.arraycopy(chunk, 0, buffer, count, n)
                    count += n
                }
                level = AudioUtil.rmsLevel(chunk, n)
            }
        }.apply { name = "hlas-recorder"; start() }
    }

    fun mark(lang: String) = synchronized(lock) { marks.add(count to lang) }

    /** Stop and return the segments (audio, language). */
    fun stop(): List<Pair<ShortArray, String>> {
        running = false
        thread?.join(500)
        thread = null
        record?.let { runCatching { it.stop() }; it.release() }
        record = null
        level = 0f
        val (audio, m) = synchronized(lock) { buffer.copyOf(count) to marks.toList() }
        return AudioUtil.segments(audio, m)
    }

    fun cancel() { stop() }
}
