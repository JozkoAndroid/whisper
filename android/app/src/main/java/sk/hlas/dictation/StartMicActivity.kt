package sk.hlas.dictation

import android.app.Activity
import android.os.Bundle

/** Invisible: starts MicService (which needs Hlas to be on screen for a moment) and closes. */
class StartMicActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        MicService.start(this)
        finish()
        overridePendingTransition(0, 0)
    }
}
