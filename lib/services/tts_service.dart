import 'package:flutter_tts/flutter_tts.dart';
import '../config/app_config.dart';

class TtsService {
  final FlutterTts _tts;

  TtsService({FlutterTts? tts}) : _tts = tts ?? FlutterTts();

  Future<void> initialize({
    void Function()? onComplete,
    void Function(dynamic msg)? onError,
  }) async {
    final config = AppConfig.instance;
    await _tts.setLanguage(config.ttsLanguage);
    await _tts.setSpeechRate(config.ttsDefaultSpeed);
    await _tts.setPitch(config.ttsDefaultPitch);

    if (onComplete != null) {
      _tts.setCompletionHandler(onComplete);
    }
    if (onError != null) {
      _tts.setErrorHandler(onError);
    }
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
