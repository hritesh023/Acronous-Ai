import 'package:flutter/material.dart';

/// Central helper for theme-aware app logos.
///
/// - Dark mode  -> existing dark assets (`assets/logo.png` /
///   `assets/Acronous_Ai_svj_logo.png`)
/// - Light mode (or any non-dark brightness) -> `assets/logo_light.png`
class AppLogo {
  static const String darkAsset = 'assets/logo.png';
  static const String lightAsset = 'assets/logo_light.png';
  static const String darkAssistantAsset = 'assets/Acronous_Ai_svj_logo.png';

  /// Main app logo: light logo in light mode, dark logo in dark mode.
  static String assetFor(BuildContext context) {
    return Theme.of(context).brightness == Brightness.dark
        ? darkAsset
        : lightAsset;
  }

  /// Assistant / floating-icon logo: light logo in light mode,
  /// existing purple svj logo in dark mode (preserves current dark look).
  static String assistantAssetFor(BuildContext context) {
    return Theme.of(context).brightness == Brightness.dark
        ? darkAssistantAsset
        : lightAsset;
  }
}

/// Drop-in [Image.asset] that automatically picks the light/dark logo.
class AppLogoImage extends StatelessWidget {
  final double? width;
  final double? height;
  final BoxFit fit;
  final Widget Function(BuildContext, Object, StackTrace?)? errorBuilder;
  final bool useAssistantDarkVariant;

  const AppLogoImage({
    super.key,
    this.width,
    this.height,
    this.fit = BoxFit.contain,
    this.errorBuilder,
    this.useAssistantDarkVariant = false,
  });

  @override
  Widget build(BuildContext context) {
    final path = useAssistantDarkVariant
        ? AppLogo.assistantAssetFor(context)
        : AppLogo.assetFor(context);
    return Image.asset(
      path,
      width: width,
      height: height,
      fit: fit,
      errorBuilder: errorBuilder ??
          (_, _, _) => Icon(
                Icons.auto_awesome,
                size: (height ?? 24) - 3,
                color: Theme.of(context).colorScheme.primary,
              ),
    );
  }
}
