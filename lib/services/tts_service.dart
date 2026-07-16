import 'package:flutter/foundation.dart';
import 'package:flutter_tts/flutter_tts.dart';
import '../config/app_config.dart';

class TtsService {
  final FlutterTts _tts;

  TtsService({FlutterTts? tts}) : _tts = tts ?? FlutterTts();

  double _platformAdjustedSpeed() {
    final raw = AppConfig.instance.ttsDefaultSpeed;
    // On iOS/macOS, FlutterTTS max rate is 1.0 but speech sounds slow at that value.
    // Boost slightly to compensate.
    if (defaultTargetPlatform == TargetPlatform.iOS || defaultTargetPlatform == TargetPlatform.macOS) {
      return (raw * 1.2).clamp(0.0, 1.0);
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

      // Priority: natural-sounding male voices first
      const preferredNames = ['daniel', 'james', 'matthew', 'john', 'david', 'mark', 'alex', 'guy', 'tom', 'ryan'];
      Map<String, dynamic>? bestVoice;

      for (final v in list) {
        final map = v as Map<String, dynamic>;
        final name = (map['name'] as String? ?? '').toLowerCase();
        final ident = (map['identifier'] as String? ?? '').toLowerCase();
        final locale = (map['locale'] as String? ?? '').toLowerCase();

        // Must be English voice
        if (!locale.startsWith('en')) continue;

        // Check if it matches a preferred natural male voice name
        for (final preferred in preferredNames) {
          if (name.contains(preferred) || ident.contains(preferred)) {
            bestVoice = map;
            break;
          }
        }
        if (bestVoice != null) break;
      }

      // Fallback: any English male voice
      if (bestVoice == null) {
        for (final v in list) {
          final map = v as Map<String, dynamic>;
          final name = (map['name'] as String? ?? '').toLowerCase();
          final ident = (map['identifier'] as String? ?? '').toLowerCase();
          final locale = (map['locale'] as String? ?? '').toLowerCase();
          if (locale.startsWith('en') && (name.contains('male') || ident.contains('male'))) {
            bestVoice = map;
            break;
          }
        }
      }

      // Final fallback: any male voice
      if (bestVoice == null) {
        for (final v in list) {
          final map = v as Map<String, dynamic>;
          final name = (map['name'] as String? ?? '').toLowerCase();
          final ident = (map['identifier'] as String? ?? '').toLowerCase();
          if (name.contains('male') || ident.contains('male')) {
            bestVoice = map;
            break;
          }
        }
      }

      if (bestVoice != null) {
        final voiceMap = <String, String>{
          'name': bestVoice['name'] as String? ?? '',
          'locale': bestVoice['locale'] as String? ?? '',
        };
        if (bestVoice.containsKey('identifier')) {
          voiceMap['identifier'] = bestVoice['identifier'] as String? ?? '';
        }
        await _tts.setVoice(voiceMap);
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
