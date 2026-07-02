import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

class ImageViewer extends StatefulWidget {
  final Uint8List imageBytes;

  const ImageViewer({super.key, required this.imageBytes});

  @override
  State<ImageViewer> createState() => _ImageViewerState();
}

class _ImageViewerState extends State<ImageViewer>
    with SingleTickerProviderStateMixin {
  final TransformationController _transformController =
      TransformationController();
  late AnimationController _fadeController;
  late Animation<double> _fadeAnimation;

  @override
  void initState() {
    super.initState();
    _fadeController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 350),
    );
    _fadeAnimation = CurvedAnimation(
      parent: _fadeController,
      curve: Curves.easeInOut,
    );
    _fadeController.forward();
  }

  @override
  void dispose() {
    _transformController.dispose();
    _fadeController.dispose();
    super.dispose();
  }

  void _resetZoom() {
    _transformController.value = Matrix4.identity();
  }

  @override
  Widget build(BuildContext context) {
    return FadeTransition(
      opacity: _fadeAnimation,
      child: Scaffold(
        backgroundColor: Colors.black.withValues(alpha: 0.92),
        appBar: AppBar(
          backgroundColor: Colors.transparent,
          elevation: 0,
          leading: IconButton(
            icon: Icon(Icons.close_rounded, color: Colors.white, size: 28),
            onPressed: () => Navigator.of(context).pop(),
          ),
          actions: [
            IconButton(
              icon: Icon(Icons.zoom_out_map_rounded, color: Colors.white, size: 24),
              onPressed: _resetZoom,
            ),
          ],
          systemOverlayStyle: const SystemUiOverlayStyle(
            statusBarColor: Colors.transparent,
            statusBarIconBrightness: Brightness.light,
          ),
        ),
        body: Center(
          child: InteractiveViewer(
            transformationController: _transformController,
            minScale: 0.5,
            maxScale: 5.0,
            boundaryMargin: const EdgeInsets.all(100),
            child: Hero(
              tag: 'generated_image_${UniqueKey().toString()}',
              child: ClipRRect(
                borderRadius: BorderRadius.circular(8),
                child: Stack(
                  children: [
                    Image.memory(
                      widget.imageBytes,
                      fit: BoxFit.contain,
                      errorBuilder: (_, _, _) => Icon(
                        Icons.broken_image,
                        size: 64,
                        color: Colors.white.withValues(alpha: 0.5),
                      ),
                    ),
                    Positioned(
                      bottom: 4,
                      right: 4,
                      child: Container(
                        decoration: BoxDecoration(
                          color: Colors.black.withValues(alpha: 0.35),
                          borderRadius: BorderRadius.circular(2),
                        ),
                        padding: const EdgeInsets.all(1),
                        child: ClipRRect(
                          borderRadius: BorderRadius.circular(1),
                          child: Image.asset(
                            'assets/logo.png',
                            width: 10,
                            height: 10,
                          ),
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      bottomNavigationBar: SafeArea(
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 12),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Icon(Icons.zoom_in, size: 16, color: Colors.white.withValues(alpha: 0.5)),
                const SizedBox(width: 6),
                Text(
                  'Pinch to zoom \u2022 Double-tap to reset',
                  style: TextStyle(
                    color: Colors.white.withValues(alpha: 0.5),
                    fontSize: 13,
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
