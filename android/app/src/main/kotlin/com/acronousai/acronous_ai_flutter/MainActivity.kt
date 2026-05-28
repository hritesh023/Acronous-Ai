package com.acronousai.acronous_ai_flutter

import android.content.Context
import android.content.Intent
import android.graphics.Color
import android.graphics.PixelFormat
import android.net.Uri
import android.os.Build
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.WindowManager
import android.widget.ImageView
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

class MainActivity : FlutterActivity() {
    private val CHANNEL = "acronous_ai/overlay"
    private var overlayView: View? = null
    private var overlayParams: WindowManager.LayoutParams? = null
    private var initialX = 0
    private var initialY = 0
    private var initialTouchX = 0f
    private var initialTouchY = 0f

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, CHANNEL).setMethodCallHandler { call, result ->
            when (call.method) {
                "requestOverlayPermission" -> {
                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                        if (!Settings.canDrawOverlays(this)) {
                            val intent = Intent(
                                Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                                Uri.parse("package:$packageName")
                            )
                            startActivity(intent)
                        }
                    }
                    result.success(Settings.canDrawOverlays(this))
                }
                "checkOverlayPermission" -> {
                    val granted = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                        Settings.canDrawOverlays(this)
                    } else true
                    result.success(granted)
                }
                "showOverlay" -> {
                    showOverlayIcon()
                    result.success(true)
                }
                "hideOverlay" -> {
                    hideOverlayIcon()
                    result.success(true)
                }
                else -> result.notImplemented()
            }
        }
    }

    private fun showOverlayIcon() {
        if (overlayView != null) return
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M && !Settings.canDrawOverlays(this)) return

        val wm = getSystemService(Context.WINDOW_SERVICE) as WindowManager
        val icon = ImageView(this).apply {
            setImageResource(android.R.drawable.ic_btn_speak_now)
            setColorFilter(Color.argb(220, 99, 102, 241))
            setPadding(12, 12, 12, 12)
            scaleType = ImageView.ScaleType.FIT_CENTER
            background = android.graphics.drawable.GradientDrawable().apply {
                shape = android.graphics.drawable.GradientDrawable.OVAL
                setSize(56, 56)
                setColor(Color.WHITE)
                setStroke(2, Color.argb(60, 99, 102, 241))
            }
            setOnClickListener {
                val launchIntent = packageManager.getLaunchIntentForPackage(packageName)
                if (launchIntent != null) {
                    launchIntent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP)
                    startActivity(launchIntent)
                }
            }
        }

        val layoutFlag = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
        } else {
            WindowManager.LayoutParams.TYPE_PHONE
        }

        overlayParams = WindowManager.LayoutParams(
            56,
            56,
            layoutFlag,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL,
            PixelFormat.TRANSLUCENT
        ).apply {
            gravity = Gravity.TOP or Gravity.START
            x = 16
            y = 200
        }

        icon.setOnTouchListener { _, event ->
            val params = overlayParams ?: return@setOnTouchListener false
            when (event.action) {
                MotionEvent.ACTION_DOWN -> {
                    initialX = params.x
                    initialY = params.y
                    initialTouchX = event.rawX
                    initialTouchY = event.rawY
                    false
                }
                MotionEvent.ACTION_MOVE -> {
                    params.x = initialX + (event.rawX - initialTouchX).toInt()
                    params.y = initialY + (event.rawY - initialTouchY).toInt()
                    wm.updateViewLayout(icon, params)
                    true
                }
                else -> false
            }
        }

        overlayView = icon
        wm.addView(icon, overlayParams)
    }

    private fun hideOverlayIcon() {
        overlayView?.let {
            val wm = getSystemService(Context.WINDOW_SERVICE) as WindowManager
            try {
                wm.removeView(it)
            } catch (_: Exception) {}
            overlayView = null
            overlayParams = null
        }
    }

    override fun onDestroy() {
        hideOverlayIcon()
        super.onDestroy()
    }
}
