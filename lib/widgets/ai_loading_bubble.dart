import 'dart:math' as math;

import 'package:flutter/material.dart';

/// Eye-pleasing, intelligent-looking loading bubble shown while the brain
/// is thinking about a normal (text) question. Replaces the old 3-dots and
/// the misplaced image skeleton on plain chat.
///
/// HONEST loading contract (do not regress):
/// - Never shows percentages, never claims completion ahead of time.
/// - [phases] names pipeline stages only; the bubble STICKS on the last
///   stage instead of looping (looping implies progress that isn't real).
/// - When [startedAt] is provided, shows live elapsed seconds
///   ("Thinking… • 5s") and appends "still working" after 12s so long CPU
///   waits read as honest, not frozen.
class AiLoadingBubble extends StatefulWidget {
  final String label;
  final List<String>? phases;
  final int initialPhase;
  final Duration phaseInterval;
  final DateTime? startedAt;
  final bool showElapsed;

  const AiLoadingBubble({
    super.key,
    this.label = 'Thinking',
    this.phases,
    this.initialPhase = 0,
    this.phaseInterval = const Duration(milliseconds: 2400),
    this.startedAt,
    this.showElapsed = true,
  });

  @override
  State<AiLoadingBubble> createState() => _AiLoadingBubbleState();
}

class _AiLoadingBubbleState extends State<AiLoadingBubble>
    with TickerProviderStateMixin {
  late final AnimationController _orbit;
  late final AnimationController _pulse;
  late final AnimationController _shimmer;
  int _phase = 0;
  int _elapsedSecs = 0;

  List<String> get _phases =>
      widget.phases ??
      (widget.label.isEmpty
          ? const ['Thinking', 'Recalling memory', 'Writing']
          : [widget.label, 'Recalling memory', 'Writing']);

  String get _honestLabel {
    final base = _phases[_phase.clamp(0, _phases.length - 1)];
    if (!widget.showElapsed || widget.startedAt == null) return base;
    if (_elapsedSecs <= 0) return base;
    // After 12s on CPU inference, say so explicitly — never fake progress.
    if (_elapsedSecs >= 12) return '$base • ${_elapsedSecs}s (still working…)';
    return '$base • ${_elapsedSecs}s';
  }

  @override
  void initState() {
    super.initState();
    _phase = widget.initialPhase;
    _elapsedSecs = widget.startedAt == null
        ? 0
        : DateTime.now().difference(widget.startedAt!).inSeconds;
    _orbit = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 2200),
    )..repeat();
    _pulse = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1400),
    )..repeat(reverse: true);
    _shimmer = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1800),
    )..repeat();
    if (_phases.length > 1) {
      Future.delayed(widget.phaseInterval, _advancePhase);
    }
    if (widget.showElapsed && widget.startedAt != null) {
      Future.delayed(const Duration(seconds: 1), _tickElapsed);
    }
  }

  void _tickElapsed() {
    if (!mounted) return;
    if (widget.startedAt != null) {
      setState(() => _elapsedSecs =
          DateTime.now().difference(widget.startedAt!).inSeconds);
    }
    Future.delayed(const Duration(seconds: 1), _tickElapsed);
  }

  void _advancePhase() {
    if (!mounted) return;
    // HONEST: advance through real stages then STICK on the last one.
    // Looping back to "Thinking" after "Writing" would imply restarted
    // progress that never happened.
    if (_phase < _phases.length - 1) {
      setState(() => _phase++);
      Future.delayed(widget.phaseInterval, _advancePhase);
    }
  }

  @override
  void didUpdateWidget(covariant AiLoadingBubble old) {
    super.didUpdateWidget(old);
    // The parent drives the canonical label (e.g. advancing through
    // mode-specific phases while work is pending). Snap to it when it names
    // a phase we know, so parent and bubble never show different stages; the
    // self-cycle keeps advancing between parent updates.
    if (widget.label != old.label && widget.label.isNotEmpty) {
      final idx = _phases.indexOf(widget.label);
      if (idx >= 0 && idx != _phase) {
        setState(() => _phase = idx);
      }
    }
  }

  @override
  void dispose() {
    _orbit.dispose();
    _pulse.dispose();
    _shimmer.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final dark = cs.brightness == Brightness.dark;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      decoration: BoxDecoration(
        color: dark ? const Color(0xFF161628) : Colors.white,
        borderRadius: BorderRadius.circular(18),
        border: Border.all(
          color: cs.primary.withValues(alpha: dark ? 0.25 : 0.18),
        ),
        boxShadow: [
          BoxShadow(
            color: cs.primary.withValues(alpha: dark ? 0.12 : 0.08),
            blurRadius: 18,
            spreadRadius: -4,
          ),
        ],
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          SizedBox(
            width: 34,
            height: 34,
            child: AnimatedBuilder(
              animation: Listenable.merge([_orbit, _pulse]),
              builder: (context, _) {
                return CustomPaint(
                  painter: _OrbPainter(
                    t: _orbit.value,
                    pulse: _pulse.value,
                    primary: cs.primary,
                    secondary: cs.tertiary,
                    dark: dark,
                  ),
                );
              },
            ),
          ),
          const SizedBox(width: 12),
          Flexible(
            child: AnimatedBuilder(
              animation: _shimmer,
              builder: (context, child) {
                final phase = (_shimmer.value * 2 - 1).abs();
                return Opacity(
                  opacity: 0.55 + 0.45 * phase,
                  child: child,
                );
              },
              child: AnimatedSwitcher(
                duration: const Duration(milliseconds: 350),
                transitionBuilder: (child, anim) => FadeTransition(
                  opacity: anim,
                  child: SlideTransition(
                    position: Tween<Offset>(
                      begin: const Offset(0, 0.4),
                      end: Offset.zero,
                    ).animate(anim),
                    child: child,
                  ),
                ),
                child: Text(
                  _honestLabel,
                  key: ValueKey('$_phase-$_elapsedSecs'),
                  style: TextStyle(
                    fontSize: 13.5,
                    fontWeight: FontWeight.w600,
                    letterSpacing: 0.2,
                    color: cs.onSurface,
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _OrbPainter extends CustomPainter {
  final double t;
  final double pulse;
  final Color primary;
  final Color secondary;
  final bool dark;
  _OrbPainter({
    required this.t,
    required this.pulse,
    required this.primary,
    required this.secondary,
    required this.dark,
  });

  @override
  void paint(Canvas canvas, Size size) {
    final c = Offset(size.width / 2, size.height / 2);
    final r = size.width / 2;
    // Soft breathing halo
    final halo = Paint()
      ..color = primary.withValues(alpha: 0.10 + 0.10 * pulse)
      ..maskFilter = const MaskFilter.blur(BlurStyle.normal, 6);
    canvas.drawCircle(c, r * (0.78 + 0.18 * pulse), halo);
    // Core gradient orb
    final core = Paint()
      ..shader = SweepGradient(
        startAngle: t * math.pi * 2,
        colors: [primary, secondary, primary],
      ).createShader(Rect.fromCircle(center: c, radius: r * 0.62));
    canvas.drawCircle(c, r * 0.55, core);
    // Orbiting satellite dot
    final a = t * math.pi * 2;
    final dot = Offset(c.dx + math.cos(a) * r * 0.85,
        c.dy + math.sin(a) * r * 0.85);
    canvas.drawCircle(dot, 2.4, Paint()..color = secondary);
    // Inner sparkle
    canvas.drawCircle(
      Offset(c.dx - r * 0.18, c.dy - r * 0.18),
      r * 0.14,
      Paint()..color = Colors.white.withValues(alpha: 0.85),
    );
  }

  @override
  bool shouldRepaint(covariant _OrbPainter old) =>
      old.t != t || old.pulse != pulse;
}
