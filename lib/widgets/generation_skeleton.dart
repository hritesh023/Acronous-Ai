import 'dart:math' as math;

import 'package:flutter/material.dart';
import '../constants/app_constants.dart';

enum GenerationKind { image, video, file, edit }

/// Skeleton preview shown in place of an assistant message while an
/// image / video / document is being generated. Cycles context-aware
/// status labels supplied by the ChatProvider ("Changing background…",
/// "Applying final touches…", …).
class GenerationSkeleton extends StatefulWidget {
  final String label;
  final GenerationKind kind;

  const GenerationSkeleton({
    super.key,
    required this.label,
    this.kind = GenerationKind.image,
  });

  @override
  State<GenerationSkeleton> createState() => _GenerationSkeletonState();
}

class _GenerationSkeletonState extends State<GenerationSkeleton>
    with SingleTickerProviderStateMixin {
  late final AnimationController _shimmer = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 1600),
  )..repeat();

  @override
  void dispose() {
    _shimmer.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final base = cs.onSurfaceVariant.withValues(alpha: 0.10);
    final highlight = cs.onSurfaceVariant.withValues(alpha: 0.045);

    return ConstrainedBox(
      constraints: const BoxConstraints(maxWidth: 340),
      child: Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: cs.surfaceContainerHighest.withValues(alpha: 0.14),
          borderRadius: BorderRadius.circular(14),
          border: Border.all(color: cs.primary.withValues(alpha: 0.14)),
        ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          ClipRRect(
            borderRadius: BorderRadius.circular(10),
            child: AnimatedBuilder(
              animation: _shimmer,
              builder: (context, _) => CustomPaint(
                size: Size.fromHeight(_previewHeight),
                painter: _SkeletonPainter(
                  progress: _shimmer.value,
                  base: base,
                  highlight: highlight,
                  kind: widget.kind,
                  primary: cs.primary.withValues(alpha: 0.16),
                ),
              ),
            ),
          ),
          const SizedBox(height: 10),
          Row(
            children: [
              SizedBox(
                width: 15,
                height: 15,
                child: CircularProgressIndicator(
                  strokeWidth: 2,
                  valueColor: AlwaysStoppedAnimation<Color>(cs.primary),
                ),
              ),
              const SizedBox(width: 9),
              Expanded(
                child: AnimatedSwitcher(
                  duration: const Duration(milliseconds: 260),
                  switchInCurve: Curves.easeOut,
                  switchOutCurve: Curves.easeIn,
                  transitionBuilder: (child, anim) => FadeTransition(
                    opacity: anim,
                    child: SlideTransition(
                      position: Tween<Offset>(
                        begin: const Offset(0, 0.35),
                        end: Offset.zero,
                      ).animate(anim),
                      child: child,
                    ),
                  ),
                  child: Text(
                    widget.label,
                    key: ValueKey(widget.label),
                    style: TextStyle(
                      fontSize: AppDimens.fontSizeSM,
                      color: cs.onSurfaceVariant.withValues(alpha: 0.85),
                      fontWeight: FontWeight.w500,
                    ),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
              ),
            ],
          ),
        ],
        ),
      ),
    );
  }

  double get _previewHeight {
    switch (widget.kind) {
      case GenerationKind.video:
        return 148;
      case GenerationKind.file:
        return 96;
      case GenerationKind.image:
      case GenerationKind.edit:
        return 170;
    }
  }
}

class _SkeletonPainter extends CustomPainter {
  final double progress;
  final Color base;
  final Color highlight;
  final Color primary;
  final GenerationKind kind;

  _SkeletonPainter({
    required this.progress,
    required this.base,
    required this.highlight,
    required this.primary,
    required this.kind,
  });

  @override
  void paint(Canvas canvas, Size size) {
    final r = RRect.fromRectAndRadius(
      Offset.zero & size,
      const Radius.circular(10),
    );
    final paint = Paint()..color = base;
    canvas.drawRRect(r, paint);

    // Sweep shimmer across the whole card.
    final dx = (progress * 2 - 0.5) * size.width;
    final sweep = Paint()
      ..shader = LinearGradient(
        begin: Alignment.centerLeft,
        end: Alignment.centerRight,
        colors: [highlight, primary.withValues(alpha: 0.35), highlight],
      ).createShader(Rect.fromLTWH(dx - size.width, 0, size.width * 2, size.height));
    canvas.drawRRect(r, sweep);

    // Kind-specific placeholder geometry.
    final block = Paint()..color = base;
    if (kind == GenerationKind.file) {
      // Document sheet with text lines.
      final sheet = RRect.fromRectAndRadius(
        Rect.fromCenter(
          center: Offset(size.width * 0.5, size.height * 0.52),
          width: math.min(64, size.width * 0.22),
          height: size.height * 0.72,
        ),
        const Radius.circular(6),
      );
      canvas.drawRRect(sheet, Paint()..color = primary);
      for (var i = 0; i < 3; i++) {
        canvas.drawRRect(
          RRect.fromRectAndRadius(
            Rect.fromLTWH(size.width * 0.42, size.height * (0.34 + i * 0.16), size.width * 0.2, 4),
            const Radius.circular(2),
          ),
          block,
        );
      }
      return;
    }

    // Horizon line + sun/mountain hint for image & video.
    final horizon = size.height * 0.62;
    canvas.drawRect(
      Rect.fromLTWH(0, horizon, size.width, size.height - horizon),
      block,
    );
    canvas.drawCircle(
      Offset(size.width * 0.74, size.height * 0.30),
      math.min(size.width, size.height) * 0.09,
      Paint()..color = primary,
    );
    final mountain = Path()
      ..moveTo(size.width * 0.08, horizon)
      ..lineTo(size.width * 0.34, size.height * 0.26)
      ..lineTo(size.width * 0.58, horizon)
      ..close();
    canvas.drawPath(mountain, block);
    if (kind == GenerationKind.video) {
      // Play glyph to signal a video preview.
      final center = Offset(size.width * 0.5, size.height * 0.46);
      final tri = Path()
        ..moveTo(center.dx - 8, center.dy - 11)
        ..lineTo(center.dx - 8, center.dy + 11)
        ..lineTo(center.dx + 12, center.dy)
        ..close();
      canvas.drawPath(tri, Paint()..color = primary.withValues(alpha: 0.8));
    }
  }

  @override
  bool shouldRepaint(covariant _SkeletonPainter old) =>
      old.progress != progress || old.kind != kind;
}
