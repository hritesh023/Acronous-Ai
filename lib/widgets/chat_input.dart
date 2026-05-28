import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:image_picker/image_picker.dart';
import '../constants/app_constants.dart';
import '../providers/chat_provider.dart';

class ChatInput extends StatefulWidget {
  const ChatInput({super.key});

  @override
  State<ChatInput> createState() => _ChatInputState();
}

class _ChatInputState extends State<ChatInput> with WidgetsBindingObserver {
  final _controller = TextEditingController();
  final _focusNode = FocusNode();
  bool _isComposing = false;
  bool _showExtras = false;
  bool _isSyncingVoice = false;
  String _lastSyncedVoiceText = '';
  bool _disposed = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
  }

  @override
  void dispose() {
    _disposed = true;
    WidgetsBinding.instance.removeObserver(this);
    FocusManager.instance.primaryFocus?.unfocus();
    _focusNode.unfocus();
    _controller.dispose();
    _focusNode.dispose();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.paused || state == AppLifecycleState.inactive) {
      _focusNode.unfocus();
    }
  }

  void _sendText([String? text]) {
    if (_disposed) return;
    final chat = context.read<ChatProvider>();
    final msg = (text ?? _controller.text).trim();
    if (msg.isEmpty && chat.pendingAttachments.isEmpty) {
      return;
    }
    _controller.clear();
    _focusNode.unfocus();
    setState(() {
      _isComposing = false;
      _showExtras = false;
    });
    chat.sendMessage(msg);
  }

  void _onChanged(String v) {
    setState(() => _isComposing = v.trim().isNotEmpty);
  }

  @override
  Widget build(BuildContext context) {
    final chat = context.watch<ChatProvider>();
    final cs = Theme.of(context).colorScheme;
    final hasContent = _isComposing || chat.pendingAttachments.isNotEmpty;

    if (chat.voiceText.isNotEmpty &&
        !_isSyncingVoice &&
        _controller.text == _lastSyncedVoiceText) {
      _isSyncingVoice = true;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (!_disposed && mounted) {
          if (chat.voiceText.isNotEmpty &&
              _controller.text == _lastSyncedVoiceText) {
            _controller.text = chat.voiceText;
            _lastSyncedVoiceText = chat.voiceText;
            _controller.selection = TextSelection.fromPosition(
              TextPosition(offset: _controller.text.length),
            );
            setState(() => _isComposing = true);
          }
          _isSyncingVoice = false;
        }
      });
    }

    return Container(
      padding: EdgeInsets.only(
        left: AppDimens.inputPaddingH,
        right: AppDimens.inputPaddingH,
        bottom: MediaQuery.of(context).padding.bottom + AppDimens.inputPaddingB,
        top: AppDimens.gapSM,
      ),
      color: Theme.of(context).scaffoldBackgroundColor,
      child: SafeArea(
        top: false,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (chat.pendingAttachments.isNotEmpty)
              _buildAttachmentChips(chat, cs),
            if (_showExtras && !chat.isLoading)
              _buildExtrasRow(chat, cs),
            Container(
              decoration: BoxDecoration(
                color: cs.surfaceContainerHighest.withValues(alpha: 0.15),
                borderRadius:
                    BorderRadius.circular(AppDimens.inputBarRadius),
                border: Border.all(
                  color: cs.outlineVariant.withValues(alpha: 0.15),
                ),
              ),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  InkWell(
                    borderRadius: BorderRadius.circular(10),
                    onTap: () => setState(() => _showExtras = !_showExtras),
                    child: Container(
                      width: AppDimens.inputIconSize,
                      height: AppDimens.inputIconSize,
                      margin: const EdgeInsets.only(left: 3, bottom: 3),
                      alignment: Alignment.center,
                      child: Icon(
                        _showExtras
                            ? Icons.close_rounded
                            : Icons.add_rounded,
                        size: AppDimens.inputIconInnerSize,
                        color: _showExtras
                            ? cs.primary
                            : cs.onSurfaceVariant.withValues(alpha: 0.6),
                      ),
                    ),
                  ),
                  const SizedBox(width: AppDimens.gapXS),
                  Expanded(
                    child: RepaintBoundary(
                      child: TextField(
                        key: const ValueKey('chat_text_field'),
                        controller: _controller,
                        focusNode: _focusNode,
                        maxLines: 5,
                        minLines: 1,
                        textInputAction: TextInputAction.send,
                        onChanged: _onChanged,
                        onSubmitted: chat.isLoading
                            ? null
                            : (v) => _sendText(v.trim()),
                        readOnly: chat.isLoading,
                        decoration: const InputDecoration(
                          hintText: AppStrings.messageHint,
                          border: InputBorder.none,
                          filled: false,
                          contentPadding: EdgeInsets.symmetric(
                            horizontal: 4,
                            vertical: 9,
                          ),
                        ),
                      ),
                    ),
                  ),
                  if (chat.isListening)
                    _buildMicActiveButton(cs, chat)
                  else
                    Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                          InkWell(
                            borderRadius: BorderRadius.circular(10),
                            onTap: () => chat.startVoiceInput(),
                            child: Container(
                              width: AppDimens.inputIconSize,
                              height: AppDimens.inputIconSize,
                              margin: const EdgeInsets.only(bottom: 3),
                              alignment: Alignment.center,
                              child: Icon(
                                Icons.mic_outlined,
                                size: AppDimens.inputIconInnerSize - 2,
                                color: cs.onSurfaceVariant
                                    .withValues(alpha: 0.6),
                              ),
                            ),
                          ),
                          InkWell(
                            borderRadius: BorderRadius.circular(10),
                            onTap: () => chat.analyzeWithCamera(context),
                            child: Container(
                              width: AppDimens.inputIconSize,
                              height: AppDimens.inputIconSize,
                              margin: const EdgeInsets.only(bottom: 3),
                              alignment: Alignment.center,
                              child: Icon(
                                Icons.camera_alt_rounded,
                                size: AppDimens.inputIconInnerSize - 2,
                                color: cs.onSurfaceVariant
                                    .withValues(alpha: 0.6),
                              ),
                            ),
                          ),
                          Padding(
                            padding: const EdgeInsets.only(bottom: 3, right: 3),
                            child: Material(
                              color: chat.isLoading
                                  ? cs.error.withValues(alpha: 0.15)
                                  : (hasContent ? cs.primary : Colors.transparent),
                              borderRadius: BorderRadius.circular(10),
                              child: InkWell(
                                borderRadius: BorderRadius.circular(10),
                                onTap: chat.isLoading
                                    ? () => chat.cancelGeneration()
                                    : _sendText,
                              child: Container(
                                width: AppDimens.inputIconSize,
                                height: AppDimens.inputIconSize,
                                alignment: Alignment.center,
                                child: chat.isLoading
                                    ? Icon(
                                        Icons.stop_rounded,
                                        size: AppDimens.inputIconInnerSize - 2,
                                        color: cs.error,
                                      )
                                    : Icon(
                                        Icons.arrow_upward_rounded,
                                        size: AppDimens.inputIconInnerSize - 2,
                                        color: hasContent
                                            ? cs.onPrimary
                                            : cs.onSurfaceVariant
                                                .withValues(alpha: 0.6),
                                      ),
                              ),
                            ),
                          ),
                        ),
                      ],
                    ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildAttachmentChips(ChatProvider chat, ColorScheme cs) {
    return Container(
      padding: const EdgeInsets.only(bottom: 5),
      child: SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        child: Row(
          children: [
            ...List.generate(chat.pendingAttachments.length, (i) {
              final att = chat.pendingAttachments[i];
              return Padding(
                padding: const EdgeInsets.only(right: 5),
                child: Chip(
                  avatar: Text(att.iconLabel,
                      style: const TextStyle(fontSize: AppDimens.fontSizeMD)),
                  label: Text(
                    att.name.length > 16
                        ? '${att.name.substring(0, 13)}...'
                        : att.name,
                    style: const TextStyle(fontSize: AppDimens.fontSizeSM),
                  ),
                  deleteIcon: const Icon(Icons.close_rounded,
                      size: AppDimens.iconSmall),
                  onDeleted: () => chat.removePendingAttachment(i),
                  visualDensity: VisualDensity.compact,
                  materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
                  labelPadding: const EdgeInsets.only(left: AppDimens.gapXS),
                  padding: const EdgeInsets.symmetric(
                      horizontal: AppDimens.paddingSM),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(16),
                  ),
                ),
              );
            }),
            ActionChip(
              avatar: Icon(Icons.auto_awesome, size: 16,
                  color: chat.isLoading ? cs.onSurfaceVariant.withValues(alpha: 0.3) : cs.primary),
              label: Text(
                AppStrings.analyzeImage,
                style: TextStyle(
                  fontSize: AppDimens.fontSizeSM,
                  color: chat.isLoading ? cs.onSurfaceVariant.withValues(alpha: 0.3) : cs.primary,
                ),
              ),
              onPressed: chat.isLoading ? null : () => chat.sendPendingAnalysis(),
              visualDensity: VisualDensity.compact,
              materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
              padding: const EdgeInsets.symmetric(
                  horizontal: AppDimens.paddingSM),
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(16),
                side: BorderSide(
                  color: chat.isLoading
                      ? cs.onSurfaceVariant.withValues(alpha: 0.1)
                      : cs.primary.withValues(alpha: 0.3),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildExtrasRow(ChatProvider chat, ColorScheme cs) {
    return Container(
      padding: const EdgeInsets.only(bottom: AppDimens.paddingSM),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          _ExtrasButton(
            icon: Icons.photo_library_rounded,
            label: AppStrings.galleryBtn,
            color: cs.secondary,
            onTap: () => chat.pickImage(ImageSource.gallery),
          ),
          const SizedBox(width: AppDimens.gapLG),
          _ExtrasButton(
            icon: Icons.attach_file_rounded,
            label: AppStrings.filesBtn,
            color: cs.error,
            onTap: () => chat.pickFile(),
          ),
        ],
      ),
    );
  }

  Widget _buildMicActiveButton(ColorScheme cs, ChatProvider chat) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 3, right: 3),
      child: Material(
        color: cs.error,
        borderRadius: BorderRadius.circular(10),
        child: InkWell(
          borderRadius: BorderRadius.circular(10),
          onTap: () {
            final text = chat.voiceText;
            chat.stopVoiceInput();
            if (text.trim().isNotEmpty) {
              WidgetsBinding.instance.addPostFrameCallback((_) {
                if (mounted) {
                  _controller.text = text;
                  _controller.selection = TextSelection.fromPosition(
                    TextPosition(offset: _controller.text.length),
                  );
                  setState(() => _isComposing = true);
                }
              });
            }
          },
          child: Container(
            width: AppDimens.inputIconSize,
            height: AppDimens.inputIconSize,
            alignment: Alignment.center,
            child: const Icon(
              Icons.stop_rounded,
              size: AppDimens.inputIconInnerSize - 2,
              color: Colors.white,
            ),
          ),
        ),
      ),
    );
  }
}

class _ExtrasButton extends StatelessWidget {
  final IconData icon;
  final String label;
  final Color color;
  final VoidCallback onTap;

  const _ExtrasButton({
    required this.icon,
    required this.label,
    required this.color,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return InkWell(
      borderRadius: BorderRadius.circular(10),
      onTap: onTap,
      child: Container(
        padding:
            const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(10),
          color: color.withValues(alpha: 0.08),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 16, color: color),
            const SizedBox(width: AppDimens.gapSM),
            Text(
              label,
              style: TextStyle(
                color: color,
                fontWeight: FontWeight.w500,
                fontSize: AppDimens.fontSizeSM - 0.5,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
