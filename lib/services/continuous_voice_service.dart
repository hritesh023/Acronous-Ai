import 'dart:async';
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
    required SpeechService speech,
    IntentProcessor? processor,
  })  : _speech = speech,
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

  Future<String?> _listenOnce() async {
    if (_speech.isListening || _isListening) return null;

    _isListening = true;
    _lastCommand = '';
    _state = ContinuousVoiceState.listening;
    notifyListeners();

    final completer = Completer<String?>();

    await _speech.initialize(
      onStatusCallback: (status) {
        if (status == 'done' || status == 'notListening' || status == 'endOfSpeech') {
          if (!completer.isCompleted) {
            completer.complete(_lastCommand.isNotEmpty ? _lastCommand : null);
          }
        }
      },
      onErrorCallback: (error) {
        if (!completer.isCompleted) {
          completer.complete(null);
        }
      },
    );

    try {
      await _speech.startListening(
        onResult: (result) {
          final text = result.recognizedWords ?? '';
          _lastCommand = text;
          notifyListeners();
        },
      );
    } catch (_) {
      if (!completer.isCompleted) {
        completer.complete(null);
      }
    }

    final result = await completer.future.timeout(
      const Duration(seconds: 30),
      onTimeout: () {
        _speech.stopListening();
        return _lastCommand.isNotEmpty ? _lastCommand : null;
      },
    );

    _isListening = false;
    notifyListeners();

    return result;
  }

  Future<void> _runLoop() async {
    while (_isRunning) {
      if (_speech.isListening) {
        await Future.delayed(const Duration(milliseconds: 500));
        continue;
      }

      final recognizedText = await _listenOnce();

      if (!_isRunning) break;

      if (recognizedText != null && recognizedText.trim().isNotEmpty) {
        _state = ContinuousVoiceState.processing;
        notifyListeners();

        final text = recognizedText.trim();
        final action = _processor.process(text);
        onCommandRecognized?.call(text);
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
