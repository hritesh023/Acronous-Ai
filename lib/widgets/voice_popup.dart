import 'dart:async';
import 'dart:math' as math;
import 'package:flutter/material.dart';
import 'package:speech_to_text/speech_to_text.dart' as stt;
import '../constants/app_constants.dart';

class VoicePopup extends StatefulWidget {
  final void Function(String text) onResult;
  final bool continuous;
  final bool searchMode;

  const VoicePopup({
    super.key,
    required this.onResult,
    this.continuous = false,
    this.searchMode = false,
  });

  @override
  State<VoicePopup> createState() => _VoicePopupState();
}

class _VoicePopupState extends State<VoicePopup>
    with SingleTickerProviderStateMixin {
  final stt.SpeechToText _speech = stt.SpeechToText();
  final TextEditingController _textController = TextEditingController();
  bool _isListening = false;
  bool _isInitialized = false;
  String _recognizedText = '';
  String _error = '';
  String _lastSetBySpeech = '';
  late AnimationController _animController;

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
    _textController.dispose();
    super.dispose();
  }

  Future<void> _initSpeech() async {
    final available = await _speech.initialize(
      onStatus: (status) {
        if (status == 'notListening' && _isListening) {
          setState(() => _isListening = false);
          if (widget.continuous) {
            Future.delayed(const Duration(milliseconds: 500), () {
              if (mounted) _startListening();
            });
          }
        }
      },
      onError: (err) => setState(() => _error = err.errorMsg),
    );
    setState(() => _isInitialized = available);
    if (available) _startListening();
  }

  void _startListening() async {
    if (!_isInitialized) return;
    setState(() {
      _isListening = true;
      _recognizedText = '';
      _lastSetBySpeech = '';
      _textController.clear();
    });
    await _speech.listen(
      onResult: (result) {
        if (!mounted) return;
        final words = result.recognizedWords;
        setState(() {
          _recognizedText = words;
          if (_textController.text == _lastSetBySpeech) {
            _textController.text = words;
            _lastSetBySpeech = words;
          }
        });
      },
      listenOptions: stt.SpeechListenOptions(
        listenFor: const Duration(seconds: 60),
        pauseFor: const Duration(seconds: 3),
        partialResults: true,
        localeId: 'en_US',
      ),
    );
  }

  void _stopListening() {
    _speech.stop();
    setState(() => _isListening = false);
  }

  void _submit() {
    _stopListening();
    final text = _textController.text.trim();
    if (text.isNotEmpty) {
      widget.onResult(text);
    }
    Navigator.of(context).pop();
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final bottomInset = MediaQuery.of(context).viewInsets.bottom;

    return Padding(
      padding: EdgeInsets.only(bottom: bottomInset),
      child: Container(
        padding: EdgeInsets.only(
          top: AppDimens.paddingXXL,
          left: AppDimens.paddingXL + 4,
          right: AppDimens.paddingXL + 4,
          bottom: MediaQuery.of(context).padding.bottom + AppDimens.paddingXL + 4,
        ),
        decoration: BoxDecoration(
          color: Theme.of(context).scaffoldBackgroundColor,
          borderRadius: const BorderRadius.vertical(
              top: Radius.circular(AppDimens.sheetRadius)),
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              width: 36,
              height: 4,
              decoration: BoxDecoration(
                color: cs.onSurfaceVariant.withValues(alpha: 0.2),
                borderRadius: BorderRadius.circular(2),
              ),
            ),
            const SizedBox(height: AppDimens.paddingXL + 4),
            Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  widget.searchMode ? 'Voice Search' 
                      : _isListening ? AppStrings.listening : AppStrings.tapToSpeak,
                  style: Theme.of(context).textTheme.titleMedium?.copyWith(
                        fontWeight: FontWeight.w600,
                        fontSize: AppDimens.fontSizeTitle,
                      ),
                ),
                if (widget.continuous && _isListening) ...[
                  const SizedBox(width: AppDimens.gapLG),
                  Container(
                    padding: const EdgeInsets.symmetric(
                        horizontal: 6, vertical: 2),
                    decoration: BoxDecoration(
                      color: cs.error.withValues(alpha: 0.15),
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Icon(Icons.fiber_manual_record_rounded,
                            size: 10, color: cs.error),
                        const SizedBox(width: 3),
                        Text('LIVE',
                            style: TextStyle(
                                fontSize: AppDimens.fontSizeXS,
                                fontWeight: FontWeight.w700,
                                color: cs.error)),
                      ],
                    ),
                  ),
                ],
              ],
            ),
            const SizedBox(height: AppDimens.paddingXXL),
            GestureDetector(
              onTap: _isListening ? _stopListening : _startListening,
              child: AnimatedBuilder(
                animation: _animController,
                builder: (context, child) {
                  final pulse =
                      0.3 + 0.2 * math.sin(_animController.value * math.pi);
                  return Container(
                    width: _isListening ? 120 : 88,
                    height: _isListening ? 120 : 88,
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      gradient: RadialGradient(
                        colors: [
                          cs.primary.withValues(alpha: pulse),
                          cs.primary.withValues(alpha: 0.08),
                        ],
                      ),
                    ),
                    child: Center(
                      child: Container(
                        width: _isListening ? 80 : 64,
                        height: _isListening ? 80 : 64,
                        decoration: BoxDecoration(
                          shape: BoxShape.circle,
                          color: _isListening ? cs.error : cs.primary,
                          boxShadow: [
                            BoxShadow(
                              color: (_isListening ? cs.error : cs.primary)
                                  .withValues(alpha: 0.35),
                              blurRadius: 16,
                              spreadRadius: _isListening ? 6 : 0,
                            ),
                          ],
                        ),
                        child: Icon(
                          _isListening ? Icons.mic : Icons.mic_none,
                          color: cs.onPrimary,
                          size: 34,
                        ),
                      ),
                    ),
                  );
                },
              ),
            ),
            const SizedBox(height: AppDimens.paddingXL + 4),
            if (_error.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(bottom: AppDimens.paddingSM),
                child: Text(
                  _error,
                  style: TextStyle(
                      color: cs.error, fontSize: AppDimens.fontSizeMD),
                ),
              ),
            Container(
              width: double.infinity,
              padding: const EdgeInsets.symmetric(
                  horizontal: AppDimens.bubbleMinPaddingH, vertical: 4),
              decoration: BoxDecoration(
                color: cs.surfaceContainerHighest.withValues(alpha: 0.2),
                borderRadius: BorderRadius.circular(14),
              ),
              child: TextField(
                controller: _textController,
                maxLines: 3,
                minLines: 1,
                textAlign: TextAlign.center,
                decoration: InputDecoration(
                  hintText: _isListening
                      ? AppStrings.speakNow
                      : AppStrings.tapMic,
                  hintStyle: TextStyle(
                    color: cs.onSurfaceVariant,
                    fontSize: AppDimens.fontSizeBase,
                    fontStyle: FontStyle.italic,
                  ),
                  border: InputBorder.none,
                  contentPadding: const EdgeInsets.symmetric(
                    horizontal: AppDimens.gapSM,
                    vertical: AppDimens.paddingMD,
                  ),
                  isDense: true,
                ),
                style: TextStyle(
                  color: cs.onSurface,
                  fontSize: AppDimens.fontSizeBase,
                ),
              ),
            ),
            const SizedBox(height: AppDimens.paddingXXL - 4),
            Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                OutlinedButton(
                  onPressed: () => Navigator.of(context).pop(),
                  style: OutlinedButton.styleFrom(
                    minimumSize: const Size(140, 44),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(12),
                    ),
                  ),
                  child: Text(AppStrings.cancel,
                      style:
                          const TextStyle(fontSize: AppDimens.fontSizeBase)),
                ),
                const SizedBox(width: AppDimens.gapXL),
                FilledButton(
                  onPressed: _recognizedText.trim().isNotEmpty
                      ? _submit
                      : null,
                  style: FilledButton.styleFrom(
                    minimumSize: const Size(140, 44),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(12),
                    ),
                  ),
                  child: Text(AppStrings.send,
                      style:
                          const TextStyle(fontSize: AppDimens.fontSizeBase)),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
