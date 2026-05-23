import 'dart:io' show Platform;
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

class OverlayService extends ChangeNotifier {
  static const _channel = MethodChannel('acronous_ai/overlay');

  bool _isSystemOverlayVisible = false;
  bool _systemOverlayPermissionGranted = false;
  bool _isInitialized = false;

  bool get isSystemOverlayVisible => _isSystemOverlayVisible;
  bool get systemOverlayPermissionGranted => _systemOverlayPermissionGranted;
  bool get isInitialized => _isInitialized;

  bool get isMobile =>
      !kIsWeb && (Platform.isAndroid || Platform.isIOS);
  bool get isDesktop =>
      !kIsWeb &&
      (Platform.isWindows || Platform.isMacOS || Platform.isLinux);
  bool get supportsSystemOverlay => !kIsWeb && Platform.isAndroid;
  bool get supportsInAppOverlay => true;

  Future<void> initialize() async {
    if (_isInitialized) return;
    if (supportsSystemOverlay) {
      await _checkOverlayPermission();
    }
    _isInitialized = true;
    notifyListeners();
  }

  Future<bool> requestOverlayPermission() async {
    if (!supportsSystemOverlay) return false;
    try {
      final result =
          await _channel.invokeMethod<bool>('requestOverlayPermission');
      _systemOverlayPermissionGranted = result ?? false;
      notifyListeners();
      return _systemOverlayPermissionGranted;
    } catch (e) {
      debugPrint('Overlay permission error: $e');
      return false;
    }
  }

  Future<bool> _checkOverlayPermission() async {
    try {
      final result =
          await _channel.invokeMethod<bool>('checkOverlayPermission');
      _systemOverlayPermissionGranted = result ?? false;
      return _systemOverlayPermissionGranted;
    } catch (e) {
      debugPrint('Check overlay permission error: $e');
      return false;
    }
  }

  Future<bool> showSystemOverlay() async {
    if (!supportsSystemOverlay || !_systemOverlayPermissionGranted) {
      return false;
    }
    try {
      await _channel.invokeMethod('showOverlay');
      _isSystemOverlayVisible = true;
      notifyListeners();
      return true;
    } catch (e) {
      debugPrint('Show overlay error: $e');
      return false;
    }
  }

  Future<bool> hideSystemOverlay() async {
    if (!supportsSystemOverlay) return false;
    try {
      await _channel.invokeMethod('hideOverlay');
      _isSystemOverlayVisible = false;
      notifyListeners();
      return true;
    } catch (e) {
      debugPrint('Hide overlay error: $e');
      return false;
    }
  }

  @override
  void dispose() {
    if (_isSystemOverlayVisible && supportsSystemOverlay) {
      try {
        _channel.invokeMethod('hideOverlay');
      } catch (_) {}
    }
    super.dispose();
  }
}
