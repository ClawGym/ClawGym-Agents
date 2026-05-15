package com.example

import android.content.Context
import android.widget.Toast
import android.util.Log

object StatusNotifier {
    fun showStatus(context: Context, message: String) {
        // TODO: Replace this Toast with a non-intrusive alternative
        Toast.makeText(context, message, Toast.LENGTH_SHORT).show()
    }

    fun notifyError(context: Context, message: String) {
        Toast.makeText(context, "Error: $message", Toast.LENGTH_LONG).show()
    }
}
