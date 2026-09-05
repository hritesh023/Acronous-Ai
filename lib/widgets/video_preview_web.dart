import 'dart:convert';
import 'dart:js_interop';
import 'dart:ui_web' as ui_web;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:web/web.dart' as web;

/// Build a configured native HTML5 <video> element from base64 mp4 and register
/// it as a platform view. `viewType` must be unique per element. `posterB64`
/// (when provided) shows a still thumbnail before playback begins.
web.HTMLVideoElement _makeVideoElement(String b64, String viewType,
    {bool autoplay = true, String? posterB64}) {
  final data = base64Decode(b64);
  final blob = web.Blob(
    [Uint8List.fromList(data).toJS].toJS,
    web.BlobPropertyBag(type: 'video/mp4'),
  );
  final url = web.URL.createObjectURL(blob);
  ui_web.platformViewRegistry.registerViewFactory(viewType, (int viewId) {
    final v = web.HTMLVideoElement();
    v.src = url;
    v.controls = true;
    v.loop = true;
    v.muted = true;
    v.playsInline = true;
    v.preload = 'auto';
    v.style.width = '100%';
    v.style.height = '100%';
    v.style.borderRadius = '14px';
    v.style.objectFit = 'cover';
    if (posterB64 != null && posterB64.isNotEmpty) {
      try {
        final pdata = base64Decode(posterB64);
        final pblob = web.Blob(
          [Uint8List.fromList(pdata).toJS].toJS,
          web.BlobPropertyBag(type: 'image/jpeg'),
        );
        v.poster = web.URL.createObjectURL(pblob);
      } catch (_) {}
    }
    if (autoplay) {
      v.muted = true;
      v.autoplay = true;
      v.play();
    }
    return v;
  });
  return web.HTMLVideoElement();
}

/// Inline, autoplaying video preview inside the chat bubble. Shows a real
/// thumbnail (first frame) + plays muted, with buttons to expand to a fullscreen
/// player and to download. No GPU and no native codec plugins required.
class WebVideoPreview extends StatefulWidget {
  final String b64;
  final String fileName;
  final String poster;
  final VoidCallback onDownload;

  const WebVideoPreview({
    super.key,
    required this.b64,
    required this.fileName,
    this.poster = '',
    required this.onDownload,
  });

  @override
  State<WebVideoPreview> createState() => _WebVideoPreviewState();
}

class _WebVideoPreviewState extends State<WebVideoPreview> {
  final String _viewType =
      'acronous-web-video-${DateTime.now().microsecondsSinceEpoch}-${identityHashCode(WebVideoPreview)}';

  @override
  Widget build(BuildContext context) {
    final hasPoster = widget.poster.isNotEmpty;
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: ClipRRect(
        borderRadius: BorderRadius.circular(14),
        child: Container(
          decoration: BoxDecoration(
            boxShadow: [
              BoxShadow(
                color: Colors.black.withValues(alpha: 0.12),
                blurRadius: 12,
                offset: const Offset(0, 4),
              ),
            ],
          ),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 340, maxHeight: 300),
            child: AspectRatio(
              aspectRatio: 16 / 9,
              child: Stack(
                fit: StackFit.expand,
                children: [
                  // Show the generated thumbnail poster in the bubble so the user
                  // immediately sees a real preview of the video. Tapping expands
                  // to the fullscreen player that actually plays the footage.
                  if (hasPoster)
                    Image.memory(
                      base64Decode(widget.poster),
                      fit: BoxFit.cover,
                      gaplessPlayback: true,
                    )
                  else
                    HtmlElementView(viewType: _viewType),
                  // Subtle gradient so the controls stay legible over the poster.
                  const Positioned.fill(
                    child: DecoratedBox(
                      decoration: BoxDecoration(
                        gradient: LinearGradient(
                          begin: Alignment.topCenter,
                          end: Alignment.bottomCenter,
                          colors: [Colors.transparent, Colors.black26],
                          stops: [0.6, 1.0],
                        ),
                      ),
                    ),
                  ),
                  // Centered play affordance.
                  Center(
                    child: Container(
                      padding: const EdgeInsets.all(12),
                      decoration: const BoxDecoration(
                        color: Colors.black54,
                        shape: BoxShape.circle,
                      ),
                      child: const Icon(Icons.play_arrow_rounded,
                          color: Colors.white, size: 30),
                    ),
                  ),
                  // Tap anywhere expands to the in-app fullscreen player.
                  Positioned.fill(
                    child: GestureDetector(
                      onTap: () => _openFullScreen(context),
                      child: Container(color: Colors.transparent),
                    ),
                  ),
                  Positioned(
                    right: 6,
                    bottom: 6,
                    child: Row(
                      children: [
                        GestureDetector(
                          onTap: () => _openFullScreen(context),
                          child: Container(
                            padding: const EdgeInsets.all(6),
                            decoration: const BoxDecoration(
                              color: Colors.black54,
                              shape: BoxShape.circle,
                            ),
                            child: const Icon(Icons.fullscreen_rounded,
                                color: Colors.white, size: 20),
                          ),
                        ),
                        const SizedBox(width: 8),
                        GestureDetector(
                          onTap: widget.onDownload,
                          child: Container(
                            padding: const EdgeInsets.all(6),
                            decoration: const BoxDecoration(
                              color: Colors.black54,
                              shape: BoxShape.circle,
                            ),
                            child: const Icon(Icons.download_rounded,
                                color: Colors.white, size: 20),
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }

  void _openFullScreen(BuildContext context) {
    Navigator.of(context).push(
      PageRouteBuilder(
        opaque: true,
        pageBuilder: (ctx, animation, secondaryAnimation) => _WebVideoFullScreenPage(
          b64: widget.b64,
          fileName: widget.fileName,
          poster: widget.poster,
          onDownload: widget.onDownload,
        ),
        transitionsBuilder: (context, animation, secondaryAnimation, child) =>
            FadeTransition(opacity: animation, child: child),
        transitionDuration: const Duration(milliseconds: 250),
      ),
    );
  }
}

/// In-app fullscreen video player (web). Mirrors the mobile player: large native
/// video element with controls, a close button, an Escape-to-close handler, and
/// a download button.
class _WebVideoFullScreenPage extends StatefulWidget {
  final String b64;
  final String fileName;
  final String poster;
  final VoidCallback onDownload;

  const _WebVideoFullScreenPage({
    required this.b64,
    required this.fileName,
    this.poster = '',
    required this.onDownload,
  });

  @override
  State<_WebVideoFullScreenPage> createState() => _WebVideoFullScreenPageState();
}

class _WebVideoFullScreenPageState extends State<_WebVideoFullScreenPage> {
  final String _viewType =
      'acronous-web-video-fs-${DateTime.now().microsecondsSinceEpoch}-${identityHashCode(_WebVideoFullScreenPage)}';

  @override
  void initState() {
    super.initState();
    _makeVideoElement(widget.b64, _viewType,
        autoplay: true, posterB64: widget.poster.isNotEmpty ? widget.poster : null);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      body: Stack(
        children: [
          Center(
            child: AspectRatio(
              aspectRatio: 16 / 9,
              child: HtmlElementView(viewType: _viewType),
            ),
          ),
          Positioned(
            top: 12,
            right: 12,
            child: IconButton(
              icon: const Icon(Icons.close_rounded, color: Colors.white, size: 28),
              onPressed: () => Navigator.of(context).pop(),
            ),
          ),
          Positioned(
            left: 12,
            bottom: 12,
            child: IconButton(
              icon: const Icon(Icons.download_rounded, color: Colors.white, size: 26),
              onPressed: widget.onDownload,
            ),
          ),
          // Esc key closes the fullscreen player (desktop/web).
          Focus(
            autofocus: true,
            onKeyEvent: (node, event) {
              if (event is KeyDownEvent &&
                  event.logicalKey == LogicalKeyboardKey.escape) {
                Navigator.of(context).pop();
                return KeyEventResult.handled;
              }
              return KeyEventResult.ignored;
            },
            child: const SizedBox.shrink(),
          ),
        ],
      ),
    );
  }
}
