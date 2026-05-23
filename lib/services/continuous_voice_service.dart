import 'package:flutter/foundation.dart';
import 'speech_service.dart';
import 'intent_processor.dart';

enum ContinuousVoiceState { idle, listening, processing }

class ContinuousVoiceService extends ChangeNotifier {
  final SpeechService _speech;
  final IntentProcessor _processor;

  bool _isRunning = false;
  bool _isListening = false;
  String _lastCommand = '';
  ContinuousVoiceState _state = ContinuousVoiceState.idle;

  void Function(String text)? onCommandRecognized;
  void Function(IntentAction action)? onIntentDetected;

  ContinuousVoiceService({
    SpeechService? speech,
    IntentProcessor? processor,
  })  : _speech = speech ?? SpeechService(),
        _processor = processor ?? IntentProcessor();

  bool get isRunning => _isRunning;
  bool get isListening => _isListening;
  String get lastCommand => _lastCommand;
  ContinuousVoiceState get state => _state;

  Future<void> start() async {
    if (_isRunning) return;
    _isRunning = true;
    _state = ContinuousVoiceState.listening;
    notifyListeners();
    _runLoop();
  }

  void stop() {
    _isRunning = false;
    _isListening = false;
    _speech.stopListening();
    _lastCommand = '';
    _state = ContinuousVoiceState.idle;
    notifyListeners();
  }

  Future<void> listenOnce({
    void Function(String text)? onText,
    void Function()? onDone,
  }) async {
    _isListening = true;
    _state = ContinuousVoiceState.listening;
    notifyListeners();

    final available = await _speech.initialize(
      onError: (err) {
        debugPrint('Voice error: $err');
        _isListening = false;
        _state = ContinuousVoiceState.idle;
        notifyListeners();
        onDone?.call();
      },
    );

    if (!available) {
      _isListening = false;
      _state = ContinuousVoiceState.idle;
      notifyListeners();
      onDone?.call();
      return;
    }

    String recognizedText = '';
    try {
      await _speech.startListening(
        onResult: (result) {
          recognizedText = result.recognizedWords ?? '';
          _lastCommand = recognizedText;
          notifyListeners();
          onText?.call(recognizedText);
        },
      );
    } catch (e) {
      debugPrint('Listen error: $e');
    }

    _isListening = false;
    notifyListeners();

    if (recognizedText.trim().isNotEmpty) {
      onText?.call(recognizedText.trim());
    }
    onDone?.call();
  }

  Future<void> _runLoop() async {
    while (_isRunning) {
      _isListening = true;
      notifyListeners();

      final available = await _speech.initialize(
        onError: (err) {
          debugPrint('Continuous voice error: $err');
          _isRunning = false;
          _isListening = false;
          _state = ContinuousVoiceState.idle;
          notifyListeners();
        },
      );

      if (!available || !_isRunning) break;

      String recognizedText = '';
      try {
        await _speech.startListening(
          onResult: (result) {
            recognizedText = result.recognizedWords ?? '';
            _lastCommand = recognizedText;
            notifyListeners();
          },
        );
      } catch (e) {
        debugPrint('Listen error: $e');
      }

      _isListening = false;
      notifyListeners();

      if (!_isRunning) break;

      if (recognizedText.trim().isNotEmpty) {
        _state = ContinuousVoiceState.processing;
        notifyListeners();

        final action = _processor.process(recognizedText.trim());
        onCommandRecognized?.call(recognizedText.trim());
        onIntentDetected?.call(action);

        _state = ContinuousVoiceState.listening;
        notifyListeners();
      }

      if (_isRunning) {
        await Future.delayed(const Duration(milliseconds: 200));
      }
    }

    _isListening = false;
    _state = ContinuousVoiceState.idle;
    notifyListeners();
  }
}
