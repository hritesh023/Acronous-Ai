import 'dart:math' as math;
import 'package:flutter/material.dart';
import 'package:speech_to_text/speech_to_text.dart' as stt;
import '../services/intent_processor.dart';

class VoiceCommandWidget extends StatefulWidget {
  final void Function(String text) onResult;
  final void Function(IntentAction action) onIntent;
  final VoidCallback onDismiss;

  const VoiceCommandWidget({
    super.key,
    required this.onResult,
    required this.onIntent,
    required this.onDismiss,
  });

  @override
  State<VoiceCommandWidget> createState() => _VoiceCommandWidgetState();
}

class _VoiceCommandWidgetState extends State<VoiceCommandWidget>
    with SingleTickerProviderStateMixin {
  final stt.SpeechToText _speech = stt.SpeechToText();
  final IntentProcessor _processor = IntentProcessor();
  late AnimationController _animController;
  bool _isListening = false;
  bool _isInitialized = false;
  bool _isProcessing = false;
  String _recognizedText = '';
  String _actionDescription = '';

  @override
  void initState() {
    super.initState();
    _animController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1500),
    )..repeat();
    _initSpeech();
  }

  @override
  void dispose() {
    _speech.stop();
    _animController.dispose();
    super.dispose();
  }

  Future<void> _initSpeech() async {
    final available = await _speech.initialize(
      onStatus: (status) {
        if (status == 'notListening' && _isListening && mounted) {
          setState(() => _isListening = false);
          _processResult();
        }
      },
    );
    if (mounted) {
      setState(() => _isInitialized = available);
      if (available) _startListening();
    }
  }

  void _startListening() async {
    if (!_isInitialized) return;
    setState(() {
      _isListening = true;
      _recognizedText = '';
      _actionDescription = '';
      _isProcessing = false;
    });

    await _speech.listen(
      onResult: (result) {
        if (mounted) {
          setState(() {
            _recognizedText = result.recognizedWords;
          });
        }
      },
      listenOptions: stt.SpeechListenOptions(
        listenFor: const Duration(seconds: 30),
        pauseFor: const Duration(seconds: 2),
        partialResults: true,
      ),
    );
  }

  void _processResult() {
    final text = _recognizedText.trim();
    if (text.isEmpty) {
      _startListening();
      return;
    }

    setState(() {
      _isProcessing = true;
      _actionDescription = 'Processing...';
    });

    widget.onResult(text);
    final action = _processor.process(text);

    setState(() {
      _actionDescription = _describeAction(action);
    });

    widget.onIntent(action);

    Future.delayed(const Duration(seconds: 1), () {
      if (mounted) widget.onDismiss();
    });
  }

  String _describeAction(IntentAction action) {
    switch (action.type) {
      case IntentType.call:
        return 'Calling ${action.params['contact']}...';
      case IntentType.openApp:
        return 'Opening ${action.params['target']}...';
      case IntentType.openLink:
        return 'Opening link...';
      case IntentType.sendMessage:
        return 'Messaging ${action.params['contact']}...';
      case IntentType.sendWhatsApp:
        return 'Opening WhatsApp...';
      case IntentType.search:
        return 'Searching...';
      case IntentType.aiQuery:
        return 'Asking Acronous AI...';
    }
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Material(
      color: Colors.transparent,
      child: Container(
        color: cs.surface.withValues(alpha: 0.97),
        child: SafeArea(
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              const Spacer(flex: 2),
              Text(
                'Acronous AI Voice',
                style: Theme.of(context).textTheme.titleLarge?.copyWith(
                      fontWeight: FontWeight.w600,
                    ),
              ),
              const SizedBox(height: 8),
              Text(
                _isProcessing
                    ? _actionDescription
                    : _isListening
                        ? 'Listening...'
                        : 'Tap the mic',
                style: TextStyle(color: cs.onSurfaceVariant),
              ),
              const Spacer(flex: 3),
              GestureDetector(
                onTap: () {
                  if (_isProcessing) return;
                  _speech.stop();
                  if (_isListening) {
                    setState(() => _isListening = false);
                    _processResult();
                  } else {
                    _startListening();
                  }
                },
                child: AnimatedBuilder(
                  animation: _animController,
                  builder: (context, _) {
                    final pulse =
                        0.3 + 0.2 * math.sin(_animController.value * math.pi);
                    return Container(
                      width: 120,
                      height: 120,
                      decoration: BoxDecoration(
                        shape: BoxShape.circle,
                        gradient: RadialGradient(
                          colors: [
                            cs.primary.withValues(alpha: pulse),
                            cs.primary.withValues(alpha: 0.05),
                          ],
                        ),
                      ),
                      child: Center(
                        child: Container(
                          width: _isProcessing ? 70 : 88,
                          height: _isProcessing ? 70 : 88,
                          decoration: BoxDecoration(
                            shape: BoxShape.circle,
                            color: _isProcessing ? cs.primary : cs.error,
                            boxShadow: [
                              BoxShadow(
                                color: (_isProcessing
                                        ? cs.primary
                                        : cs.error)
                                    .withValues(alpha: 0.4),
                                blurRadius: 16,
                                spreadRadius: _isListening ? 4 : 0,
                              ),
                            ],
                          ),
                          child: Icon(
                            _isProcessing
                                ? Icons.auto_awesome_rounded
                                : _isListening
                                    ? Icons.mic_rounded
                                    : Icons.mic_none_rounded,
                            color: cs.onPrimary,
                            size: 36,
                          ),
                        ),
                      ),
                    );
                  },
                ),
              ),
              const SizedBox(height: 32),
              if (_recognizedText.isNotEmpty)
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 40),
                  child: Text(
                    _recognizedText,
                    textAlign: TextAlign.center,
                    style:
                        Theme.of(context).textTheme.titleMedium?.copyWith(
                              fontWeight: FontWeight.w500,
                            ),
                  ),
                ),
              if (_isProcessing)
                Padding(
                  padding: const EdgeInsets.only(top: 16),
                  child: Row(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      if (_actionDescription.isNotEmpty)
                        Text(
                          _actionDescription,
                          style: TextStyle(
                            color: cs.primary,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                      const SizedBox(width: 12),
                      const SizedBox(
                        width: 16,
                        height: 16,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      ),
                    ],
                  ),
                ),
              if (!_isListening && !_isProcessing && _recognizedText.isEmpty)
                Padding(
                  padding: const EdgeInsets.only(top: 16),
                  child: Text(
                    'Tap mic to start',
                    style: TextStyle(color: cs.onSurfaceVariant),
                  ),
                ),
              const Spacer(flex: 2),
              TextButton.icon(
                onPressed: widget.onDismiss,
                icon: const Icon(Icons.close_rounded, size: 20),
                label: const Text('Close'),
              ),
              const SizedBox(height: 32),
            ],
          ),
        ),
      ),
    );
  }
}
