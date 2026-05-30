import 'package:flutter/foundation.dart';
import 'package:flutter_tts/flutter_tts.dart';
import '../config/app_config.dart';

class TtsService {
  final FlutterTts _tts;

  TtsService({FlutterTts? tts}) : _tts = tts ?? FlutterTts();

  double _platformAdjustedSpeed() {
    final raw = AppConfig.instance.ttsDefaultSpeed;
    if (defaultTargetPlatform == TargetPlatform.iOS ||
        defaultTargetPlatform == TargetPlatform.macOS) {
      return raw * 0.5;
    }
    return raw;
  }

  Future<void> initialize({
    void Function()? onComplete,
    void Function(dynamic msg)? onError,
  }) async {
    final config = AppConfig.instance;
    await _tts.setLanguage(config.ttsLanguage);
    await _tts.setSpeechRate(_platformAdjustedSpeed());
    await _tts.setPitch(config.ttsDefaultPitch);

    await _selectMaleVoice();

    if (onComplete != null) {
      _tts.setCompletionHandler(onComplete);
    }
    if (onError != null) {
      _tts.setErrorHandler(onError);
    }
  }

  Future<void> _selectMaleVoice() async {
    try {
      final voices = await _tts.getVoices;
      if (voices == null) return;
      final list = voices as List;
      if (list.isEmpty) return;
      for (final v in list) {
        final map = v as Map<String, dynamic>;
        final name = (map['name'] as String? ?? '').toLowerCase();
        final ident = (map['identifier'] as String? ?? '').toLowerCase();
        if (name.contains('male') || ident.contains('male')) {
          final voiceMap = <String, String>{
            'name': map['name'] as String? ?? '',
            'locale': map['locale'] as String? ?? '',
          };
          if (map.containsKey('identifier')) {
            voiceMap['identifier'] = map['identifier'] as String? ?? '';
          }
          await _tts.setVoice(voiceMap);
          break;
        }
      }
    } catch (_) {}
  }

  Future<void> setSpeed(double speed) async {
    await _tts.setSpeechRate(speed);
  }

  Future<void> setPitch(double pitch) async {
    await _tts.setPitch(pitch);
  }

  Future<void> speak(String text) async {
    await _tts.speak(text);
  }

  Future<void> stop() async {
    await _tts.stop();
  }
}
