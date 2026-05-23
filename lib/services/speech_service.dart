import 'package:speech_to_text/speech_to_text.dart' as stt;
import '../config/app_config.dart';

class SpeechService {
  final stt.SpeechToText _speech;
  bool _isInitialized = false;

  SpeechService({stt.SpeechToText? speech})
      : _speech = speech ?? stt.SpeechToText();

  bool get isInitialized => _isInitialized;

  Future<bool> initialize({
    void Function(String status)? onStatus,
    void Function(dynamic error)? onError,
  }) async {
    if (_isInitialized) return true;
    final available = await _speech.initialize(
      onStatus: onStatus,
      onError: onError,
    );
    _isInitialized = available;
    return available;
  }

  Future<void> startListening({
    required void Function(dynamic result) onResult,
  }) async {
    final config = AppConfig.instance;
    await _speech.listen(
      onResult: onResult,
      listenOptions: stt.SpeechListenOptions(
        listenFor: config.speechListenDuration,
        pauseFor: config.speechPauseDuration,
        partialResults: config.speechPartialResults,
        localeId: config.speechLocale,
      ),
    );
  }

  void stopListening() {
    _speech.stop();
  }

  void dispose() {
    _speech.stop();
  }
}
