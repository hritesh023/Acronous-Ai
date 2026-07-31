import 'package:speech_to_text/speech_to_text.dart' as stt;
import '../config/app_config.dart';

class SpeechService {
  final stt.SpeechToText _speech;
  bool _isInitialized = false;

  void Function(String status)? onStatus;
  void Function(dynamic error)? onError;

  SpeechService({stt.SpeechToText? speech})
      : _speech = speech ?? stt.SpeechToText();

  bool get isInitialized => _isInitialized;
  bool get isListening => _speech.isListening;

  Future<bool> initialize({
    void Function(String status)? onStatusCallback,
    void Function(dynamic error)? onErrorCallback,
  }) async {
    if (onStatusCallback != null) onStatus = onStatusCallback;
    if (onErrorCallback != null) onError = onErrorCallback;

    if (!_isInitialized) {
      final available = await _speech.initialize(
        onStatus: (status) => onStatus?.call(status),
        onError: (error) => onError?.call(error),
      );
      _isInitialized = available;
      return available;
    }
    return true;
  }

  Future<void> startListening({
    required void Function(dynamic result) onResult,
  }) async {
    if (_speech.isListening) {
      await _speech.stop();
    }
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
    if (_speech.isListening) {
      _speech.stop();
    }
  }

  void dispose() {
    if (_speech.isListening) {
      _speech.stop();
    }
  }
}
