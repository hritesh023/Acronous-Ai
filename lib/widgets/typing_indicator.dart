import 'package:flutter/material.dart';
import '../constants/app_constants.dart';

class TypingIndicator extends StatefulWidget {
  const TypingIndicator({super.key});

  @override
  State<TypingIndicator> createState() => _TypingIndicatorState();
}

class _TypingIndicatorState extends State<TypingIndicator>
    with SingleTickerProviderStateMixin {
  late AnimationController _controller;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      duration: const Duration(milliseconds: 1200),
      vsync: this,
    )..repeat();
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;

    return Padding(
      padding: EdgeInsets.only(
        left: AppDimens.paddingXL,
        right: AppDimens.paddingXXL * 2,
        top: AppDimens.gapSM - 2,
        bottom: AppDimens.gapSM - 2,
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            margin: const EdgeInsets.only(top: AppDimens.gapSM - 2),
            width: AppDimens.avatarSize,
            height: AppDimens.avatarSize,
            decoration: BoxDecoration(
              borderRadius:
                  BorderRadius.circular(AppDimens.avatarRadius),
              color: cs.primaryContainer,
            ),
            child: ClipRRect(
              borderRadius:
                  BorderRadius.circular(AppDimens.avatarRadius),
              child: Image.asset(
                'assets/logo.png',
                width: AppDimens.avatarSize,
                height: AppDimens.avatarSize,
                fit: BoxFit.contain,
                errorBuilder: (_, _, _) => Icon(
                  Icons.auto_awesome,
                  size: AppDimens.iconMed - 3,
                  color: cs.primary,
                ),
              ),
            ),
          ),
          const SizedBox(width: AppDimens.gapXL - 2),
          Container(
            padding: const EdgeInsets.symmetric(
                horizontal: AppDimens.paddingXL, vertical: AppDimens.bubbleMinPaddingV + 5),
            decoration: BoxDecoration(
              color: cs.surfaceContainerHighest
                  .withValues(alpha: 0.25),
              borderRadius:
                  BorderRadius.circular(AppDimens.bubbleRadius)
                      .copyWith(
                bottomLeft:
                    const Radius.circular(AppDimens.bubbleRadiusSmall),
              ),
            ),
            child: AnimatedBuilder(
              animation: _controller,
              builder: (context, child) {
                return Row(
                  mainAxisSize: MainAxisSize.min,
                  children: List.generate(3, (i) {
                    final delay = i * 0.15;
                    final t =
                        (_controller.value - delay).clamp(0.0, 1.0);
                    final scale = 0.4 +
                        0.6 *
                            (t < 0.5 ? 2 * t : 2 * (1 - t));
                    return Padding(
                      padding: const EdgeInsets.symmetric(
                          horizontal: AppDimens.gapXS),
                      child: Transform.scale(
                        scale: scale,
                        child: Container(
                          width: 8,
                          height: 8,
                          decoration: BoxDecoration(
                            color: cs.onSurfaceVariant
                                .withValues(alpha: 0.6),
                            shape: BoxShape.circle,
                          ),
                        ),
                      ),
                    );
                  }),
                );
              },
            ),
          ),
        ],
      ),
    );
  }
}
