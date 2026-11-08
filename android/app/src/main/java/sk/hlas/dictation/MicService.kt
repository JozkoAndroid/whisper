package sk.hlas.dictation

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder

/**
 * Android only lets an app use the microphone while you're in another app if
 * it runs a "microphone" foreground service that was started while Hlas was on
 * screen. This service does nothing else; it just keeps that access alive and
 * shows a quiet notification. Recording itself happens only when you tap the bubble.
 */
class MicService : Service() {
    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        try {
            val n = notification()
            if (Build.VERSION.SDK_INT >= 30) startForeground(ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE)
            else startForeground(ID, n)
            running = true
            Dictation.onMicReady(applicationContext)
        } catch (e: Exception) {
            // Started from the background (e.g. after the system killed us): not allowed to hold the mic.
            running = false
            stopSelf()
        }
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        running = false
        super.onDestroy()
    }

    private fun notification(): Notification {
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel(CHANNEL, "Hlas ready", NotificationManager.IMPORTANCE_MIN).apply {
            description = "Keeps the dictation bubble able to use the microphone"
            setShowBadge(false)
        })
        val open = PendingIntent.getActivity(this, 0, Intent(this, SettingsActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE)
        return Notification.Builder(this, CHANNEL)
            .setSmallIcon(R.drawable.ic_mic)
            .setContentTitle("Hlas is ready")
            .setContentText("Tap the mic bubble in any text field to dictate")
            .setContentIntent(open)
            .setOngoing(true)
            .build()
    }

    companion object {
        private const val ID = 7
        private const val CHANNEL = "hlas_ready"
        @Volatile var running = false

        /** Call only while Hlas has a visible screen (an Activity). */
        fun start(context: Context) {
            if (running) return
            if (context.checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) return
            try {
                context.startForegroundService(Intent(context, MicService::class.java))
            } catch (e: Exception) {
                // not allowed right now; the bubble will retry through StartMicActivity
            }
        }
    }
}
