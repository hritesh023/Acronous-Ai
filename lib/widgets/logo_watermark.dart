import 'package:flutter/material.dart';

class LogoWatermark extends StatelessWidget {
  final double size;

  const LogoWatermark({super.key, this.size = 7});

  @override
  Widget build(BuildContext context) {
    return Opacity(
      opacity: 0.55,
      child: Container(
        padding: EdgeInsets.all(size * 0.12),
        decoration: BoxDecoration(
          color: Colors.black.withValues(alpha: 0.12),
          borderRadius: BorderRadius.circular(size * 0.35),
          border: Border.all(
            color: Colors.white.withValues(alpha: 0.06),
            width: 0.3,
          ),
        ),
        child: Image.asset(
          'assets/logo.png',
          width: size,
          height: size,
          fit: BoxFit.contain,
        ),
      ),
    );
  }
}
