import 'dart:io';
import 'dart:convert';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';
import 'package:intl/intl.dart';
import '../constants/app_constants.dart';
import '../models/message.dart';
import '../providers/chat_provider.dart';
import '../widgets/image_viewer.dart';
import '../widgets/markdown_renderer.dart';

class ChatMessageWidget extends StatelessWidget {
  final ChatMessage message;

  const ChatMessageWidget({super.key, required this.message});

  bool _hasCodeBlocks(String text) {
    if (text.contains('```')) return true;
    final inlineCode = RegExp(r'`[^`\n]+`');
    if (inlineCode.hasMatch(text)) return true;
    final codePatterns = [
      RegExp(r'(?:function|class|def |import |from |const |let |var |if\s*\()',
          caseSensitive: false),
      RegExp(r'[{};]\s*$', multiLine: true),
      RegExp(r'^\s*(?:public|private|protected|static|void|int|string|bool|float|double|return)\s',
          multiLine: true, caseSensitive: false),
    ];
    for (final p in codePatterns) {
      if (p.hasMatch(text)) return true;
    }
    return false;
  }

  @override
  Widget build(BuildContext context) {
    final isUser = message.role == 'user';
    final cs = Theme.of(context).colorScheme;
    final time = DateFormat('h:mm a').format(message.timestamp);

    if (isUser) return _buildUserBubble(context, cs, time);
    return _buildAIBubble(context, cs, time);
  }

  Widget _buildUserBubble(BuildContext context, ColorScheme cs, String time) {
    return Padding(
      padding: EdgeInsets.only(
        left: AppDimens.paddingXXL * 2,
        right: AppDimens.paddingXL,
        top: AppDimens.paddingXS,
        bottom: AppDimens.paddingXS,
      ),
      child: Align(
        alignment: Alignment.centerRight,
          child: ConstrainedBox(
            constraints: BoxConstraints(
              maxWidth: (MediaQuery.of(context).size.width * AppDimens.maxBubbleWidthRatio)
                  .clamp(0, 650),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                if (message.attachments.isNotEmpty)
                  _buildAttachmentPreviews(context, cs, true),
              Container(
                padding: EdgeInsets.symmetric(
                  horizontal: AppDimens.bubbleMinPaddingH,
                  vertical: AppDimens.bubbleMinPaddingV,
                ),
                decoration: BoxDecoration(
                  gradient: LinearGradient(
                    colors: [
                      cs.primary,
                      cs.primary.withValues(alpha: 0.85),
                    ],
                    begin: Alignment.topLeft,
                    end: Alignment.bottomRight,
                  ),
                  borderRadius: BorderRadius.circular(AppDimens.bubbleRadius)
                      .copyWith(
                    bottomRight: const Radius.circular(AppDimens.bubbleRadiusSmall),
                  ),
                ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.end,
                      children: [
                        if (message.content.isNotEmpty)
                          Text(
                            message.content,
                            style: TextStyle(
                              color: cs.onPrimary,
                              fontSize: AppDimens.fontSizeBody,
                              height: 1.35,
                            ),
                          ),
                        SizedBox(height: AppDimens.paddingXS),
                    Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Text(
                          time,
                          style: TextStyle(
                            color: cs.onPrimary.withValues(alpha: 0.55),
                            fontSize: AppDimens.fontSizeXS,
                          ),
                        ),
                        SizedBox(width: AppDimens.gapXS),
                        Icon(Icons.check_rounded,
                            size: AppDimens.iconSmall,
                            color: cs.onPrimary.withValues(alpha: 0.45)),
                      ],
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildAIBubble(BuildContext context, ColorScheme cs, String time) {
    return Padding(
      padding: EdgeInsets.only(
        left: AppDimens.paddingXL,
        right: AppDimens.paddingXXL * 2,
        top: AppDimens.paddingXS,
        bottom: AppDimens.paddingXS,
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            margin: const EdgeInsets.only(top: 6),
            width: AppDimens.avatarSize,
            height: AppDimens.avatarSize,
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(AppDimens.avatarRadius),
              color: cs.primaryContainer,
            ),
              child: ClipRRect(
                borderRadius: BorderRadius.circular(AppDimens.avatarRadius),
                child: Image.asset(
                  'assets/logo.png',
                  width: AppDimens.avatarSize,
                  height: AppDimens.avatarSize,
                  fit: BoxFit.contain,
                  errorBuilder: (_, _, _) => Icon(
                    Icons.auto_awesome,
                    size: AppDimens.iconMed - 3,
                    color: cs.primary,
                  ),
                ),
              ),
          ),
          SizedBox(width: AppDimens.gapLG),
          Expanded(
            child: ConstrainedBox(
              constraints: BoxConstraints(
                maxWidth: (MediaQuery.of(context).size.width *
                        AppDimens.maxBubbleWidthRatioAI)
                    .clamp(0, 700),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Container(
                    padding: EdgeInsets.symmetric(
                      horizontal: AppDimens.bubbleMinPaddingH,
                      vertical: AppDimens.bubbleMinPaddingV,
                    ),
                    decoration: BoxDecoration(
                      color: cs.surfaceContainerHighest.withValues(alpha: 0.2),
                      borderRadius: BorderRadius.circular(AppDimens.bubbleRadius)
                          .copyWith(
                        bottomLeft:
                            const Radius.circular(AppDimens.bubbleRadiusSmall),
                      ),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        if (message.imageData.isNotEmpty)
                          _buildGeneratedImage(context, message.imageData, cs),
                        if (message.content.isNotEmpty)
                          MarkdownRenderer(content: message.content),
                      ],
                    ),
                  ),
                  Padding(
                    padding: const EdgeInsets.only(top: 3, left: 2),
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Text(
                          time,
                          style: TextStyle(
                            color: cs.onSurfaceVariant.withValues(alpha: 0.5),
                            fontSize: AppDimens.fontSizeXS,
                          ),
                        ),
                        SizedBox(width: AppDimens.gapLG),
                        Tooltip(
                          message: 'Copy entire response',
                          waitDuration: const Duration(milliseconds: 300),
                          child: _ActionIcon(
                            icon: Icons.content_copy_outlined,
                            size: AppDimens.iconSmall,
                            onTap: () {
                              Clipboard.setData(
                                ClipboardData(text: message.content),
                              );
                              ScaffoldMessenger.of(context).showSnackBar(
                                SnackBar(
                                  content: Text(AppStrings.copied),
                                  behavior: SnackBarBehavior.floating,
                                  duration: const Duration(seconds: 1),
                                  padding: const EdgeInsets.symmetric(
                                    horizontal: 16, vertical: 6,
                                  ),
                                  margin: const EdgeInsets.only(bottom: 60),
                                  shape: RoundedRectangleBorder(
                                    borderRadius: BorderRadius.circular(10),
                                  ),
                                ),
                              );
                            },
                          ),
                        ),
                        if (_hasCodeBlocks(message.content))
                          const SizedBox.shrink(),
                        SizedBox(width: AppDimens.gapSM),
                        Consumer<ChatProvider>(
                          builder: (context, chat, _) {
                            final isSpeaking = chat.isSpeaking &&
                                chat.speakingMessageId == message.id;
                            return _ActionIcon(
                              icon: isSpeaking
                                  ? Icons.stop_circle_outlined
                                  : Icons.volume_up_outlined,
                              size: AppDimens.iconSmall,
                              active: isSpeaking,
                              activeColor: cs.primary,
                              onTap: () => chat.speakMessage(
                                message.id,
                                message.content,
                              ),
                            );
                          },
                        ),
                      ],
                    ),
                  ),
                  if (message.attachments.isNotEmpty)
                    Padding(
                      padding: const EdgeInsets.only(top: AppDimens.gapSM),
                      child: _buildAttachmentPreviews(context, cs, false),
                    ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildGeneratedImage(BuildContext context, String b64, ColorScheme cs) {
    try {
      final bytes = base64Decode(b64);
      return Padding(
        padding: const EdgeInsets.only(bottom: 8),
        child: GestureDetector(
          onTap: () => _openImageViewer(context, bytes),
          child: Hero(
            tag: 'generated_image_${message.id}',
            child: Container(
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(14),
                boxShadow: [
                  BoxShadow(
                    color: Colors.black.withValues(alpha: 0.12),
                    blurRadius: 12,
                    offset: const Offset(0, 4),
                  ),
                  BoxShadow(
                    color: Colors.black.withValues(alpha: 0.06),
                    blurRadius: 4,
                    offset: const Offset(0, 1),
                  ),
                ],
              ),
              child: ClipRRect(
                borderRadius: BorderRadius.circular(14),
                child: AnimatedOpacity(
                  opacity: 1.0,
                  duration: const Duration(milliseconds: 400),
                  child: Image.memory(
                    Uint8List.fromList(bytes),
                    fit: BoxFit.contain,
                    width: double.infinity,
                    height: 300,
                    errorBuilder: (_, _, _) => const Icon(Icons.broken_image, size: 48),
                    frameBuilder: (context, child, frame, wasSynchronouslyLoaded) {
                      if (wasSynchronouslyLoaded) return child;
                      if (frame == null) {
                        return _imagePlaceholder(cs);
                      }
                      return AnimatedOpacity(
                        opacity: 1.0,
                        duration: const Duration(milliseconds: 300),
                        child: child,
                      );
                    },
                  ),
                ),
              ),
            ),
          ),
        ),
      );
    } catch (_) {
      return const SizedBox.shrink();
    }
  }

  Widget _imagePlaceholder(ColorScheme cs) {
    return Container(
      height: 300,
      width: double.infinity,
      decoration: BoxDecoration(
        color: cs.surfaceContainerHighest.withValues(alpha: 0.15),
        borderRadius: BorderRadius.circular(14),
      ),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(
            Icons.image_outlined,
            size: 48,
            color: cs.onSurfaceVariant.withValues(alpha: 0.3),
          ),
          const SizedBox(height: 8),
          Text(
            'Loading image...',
            style: TextStyle(
              color: cs.onSurfaceVariant.withValues(alpha: 0.4),
              fontSize: AppDimens.fontSizeSM,
            ),
          ),
        ],
      ),
    );
  }

  void _openImageViewer(BuildContext context, Uint8List bytes) {
    Navigator.of(context).push(
      PageRouteBuilder(
        opaque: false,
        pageBuilder: (context, animation, secondaryAnimation) =>
            ImageViewer(imageBytes: bytes),
        transitionsBuilder: (context, animation, secondaryAnimation, child) {
          return FadeTransition(
            opacity: animation,
            child: child,
          );
        },
        transitionDuration: const Duration(milliseconds: 300),
      ),
    );
  }

  Widget _buildAttachmentPreviews(
    BuildContext context,
    ColorScheme cs,
    bool isUser,
  ) {
    return Padding(
      padding: EdgeInsets.only(bottom: isUser ? AppDimens.gapSM : 0),
      child: Wrap(
        spacing: AppDimens.gapSM,
        runSpacing: AppDimens.gapSM,
        children: message.attachments.map((att) {
          if (att.type == AttachmentType.image) {
            return Container(
              width: 140,
              height: 100,
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(10),
                border: Border.all(
                  color: cs.outlineVariant.withValues(alpha: 0.15),
                ),
              ),
              child: ClipRRect(
                borderRadius: BorderRadius.circular(10),
                child: att.bytes != null
                    ? Image.memory(
                        att.bytes!,
                        fit: BoxFit.cover,
                        errorBuilder: (_, _, _) =>
                            const Icon(Icons.broken_image),
                      )
                    : kIsWeb
                        ? Image.network(
                            att.path,
                            fit: BoxFit.cover,
                            errorBuilder: (_, _, _) =>
                                const Icon(Icons.broken_image),
                          )
                        : Image.file(
                            File(att.path),
                            fit: BoxFit.cover,
                            errorBuilder: (_, _, _) =>
                                const Icon(Icons.broken_image),
                          ),
              ),
            );
          }
          return Container(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 5),
            decoration: BoxDecoration(
              color: cs.surfaceContainerHighest.withValues(alpha: 0.25),
              borderRadius: BorderRadius.circular(8),
            ),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(att.iconLabel, style: const TextStyle(fontSize: 12)),
                const SizedBox(width: 4),
                Text(
                  att.name.length > 16
                      ? '${att.name.substring(0, 13)}...'
                      : att.name,
                  style: TextStyle(
                    fontSize: AppDimens.fontSizeSM,
                    color: cs.onSurfaceVariant,
                  ),
                ),
              ],
            ),
          );
        }).toList(),
      ),
    );
  }
}

class _ActionIcon extends StatelessWidget {
  final IconData icon;
  final double size;
  final VoidCallback onTap;
  final bool active;
  final Color? activeColor;

  const _ActionIcon({
    required this.icon,
    required this.size,
    required this.onTap,
    this.active = false,
    this.activeColor,
  });

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(6),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.all(AppDimens.paddingXS),
          child: Icon(
            icon,
            size: size,
            color: active
                ? (activeColor ?? cs.primary)
                : cs.onSurfaceVariant.withValues(alpha: 0.45),
          ),
        ),
      ),
    );
  }
}
