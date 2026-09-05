import 'dart:convert';
import 'dart:io' show File;
import 'dart:math' as math;
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:web/web.dart' as web;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';
import 'package:intl/intl.dart';
import 'package:video_player/video_player.dart';
import 'package:path_provider/path_provider.dart';
import 'video_src.dart';
import '../constants/app_constants.dart';
import '../models/message.dart';
import '../providers/chat_provider.dart';
import '../utils/file_save.dart';
import '../widgets/generation_skeleton.dart';
import '../widgets/image_viewer.dart';
import '../widgets/logo_watermark.dart';
import '../widgets/markdown_renderer.dart';
import '../widgets/video_preview.dart';

class ChatMessageWidget extends StatelessWidget {
  final ChatMessage message;

  const ChatMessageWidget({super.key, required this.message});

  bool _hasCodeBlocks(String text) {
    if (text.contains('```')) return true;
    final inlineCode = RegExp(r'`[^`\n]+`');
    if (inlineCode.hasMatch(text)) return true;
    final codePatterns = [
      RegExp(
        r'(?:function|class|def |import |from |const |let |var |if\s*\()',
        caseSensitive: false,
      ),
      RegExp(r'[{};]\s*$', multiLine: true),
      RegExp(
        r'^\s*(?:public|private|protected|static|void|int|string|bool|float|double|return)\s',
        multiLine: true,
        caseSensitive: false,
      ),
    ];
    for (final p in codePatterns) {
      if (p.hasMatch(text)) return true;
    }
    // Detect raw code without fences (e.g. starts with { or contains ; and =)
    final lines = text.trim().split('\n');
    if (lines.length >= 2) {
      int codeLines = 0;
      for (final line in lines) {
        final l = line.trim();
        if (l.isEmpty) continue;
        if (l.endsWith(';') || l.endsWith(':') ||
            l.startsWith('//') || l.startsWith('#') ||
            (l.startsWith('{') && l.endsWith('}')) ||
            l.contains('=>') || l.contains('===') ||
            RegExp(r'[{}();=]').hasMatch(l)) {
          codeLines++;
        }
      }
      if (codeLines / lines.length > 0.5) return true;
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
            maxWidth:
                (MediaQuery.of(context).size.width *
                        AppDimens.maxBubbleWidthRatio)
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
                    colors: [cs.primary, cs.primary.withValues(alpha: 0.85)],
                    begin: Alignment.topLeft,
                    end: Alignment.bottomRight,
                  ),
                  borderRadius: BorderRadius.circular(AppDimens.bubbleRadius)
                      .copyWith(
                        bottomRight: const Radius.circular(
                          AppDimens.bubbleRadiusSmall,
                        ),
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
                        Icon(
                          Icons.check_rounded,
                          size: AppDimens.iconSmall,
                          color: cs.onPrimary.withValues(alpha: 0.45),
                        ),
                        if (message.content.isNotEmpty) ...[
                          SizedBox(width: AppDimens.gapSM),
                          Tooltip(
                            message: 'Copy message',
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
                                      horizontal: 16,
                                      vertical: 6,
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
                        ],
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
                maxWidth:
                    (MediaQuery.of(context).size.width *
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
                      borderRadius:
                          BorderRadius.circular(
                            AppDimens.bubbleRadius,
                          ).copyWith(
                            bottomLeft: const Radius.circular(
                              AppDimens.bubbleRadiusSmall,
                            ),
                          ),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        if (message.isStreaming &&
                            message.progressLabel.isNotEmpty) ...[
                          SizedBox(
                            width: math.min(
                              340.0,
                              MediaQuery.sizeOf(context).width - 120,
                            ).clamp(120.0, 340.0),
                            child: GenerationSkeleton(
                              label: message.progressLabel,
                              kind: _generationKind(message.progressKind),
                            ),
                          ),
                        ] else ...[
                          if (message.imageData.isNotEmpty)
                            _buildGeneratedImage(context, message.imageData, cs),
                          if (message.fileData.isNotEmpty)
                            _buildGeneratedMedia(context, message, cs),
                          if (message.content.isNotEmpty)
                            MarkdownRenderer(content: message.content),
                        ],
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
                                    horizontal: 16,
                                    vertical: 6,
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
                        if (message.imageData.isNotEmpty) ...[
                          SizedBox(width: AppDimens.gapSM),
                          Tooltip(
                            message: 'Download image',
                            waitDuration: const Duration(milliseconds: 300),
                            child: _ActionIcon(
                              icon: Icons.download_rounded,
                              size: AppDimens.iconSmall,
                              onTap: () => _downloadGeneratedImage(
                                context, message.imageData,
                              ),
                            ),
                          ),
                        ],
                        if (_hasCodeBlocks(message.content))
                          const SizedBox.shrink(),
                        SizedBox(width: AppDimens.gapSM),
                        Consumer<ChatProvider>(
                          builder: (context, chat, _) {
                            final isSpeaking =
                                chat.isSpeaking &&
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

  GenerationKind _generationKind(String kind) {
    switch (kind) {
      case 'video':
        return GenerationKind.video;
      case 'file':
        return GenerationKind.file;
      case 'edit':
        return GenerationKind.edit;
      default:
        return GenerationKind.image;
    }
  }

  Widget _buildGeneratedImage(
    BuildContext context,
    String b64,
    ColorScheme cs,
  ) {
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
                  child: ConstrainedBox(
                    constraints: const BoxConstraints(
                      maxWidth: 340,
                      maxHeight: 300,
                    ),
                    child: Stack(
                      fit: StackFit.loose,
                      clipBehavior: Clip.antiAlias,
                      children: [
                        Image.memory(
                          Uint8List.fromList(bytes),
                          fit: BoxFit.contain,
                          errorBuilder: (_, _, _) =>
                              const Icon(Icons.broken_image, size: 48),
                          frameBuilder:
                              (context, child, frame, wasSynchronouslyLoaded) {
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
                        Positioned(
                          top: 6,
                          right: 6,
                          child: Material(
                            color: Colors.black.withValues(alpha: 0.35),
                            borderRadius: BorderRadius.circular(20),
                            child: InkWell(
                              borderRadius: BorderRadius.circular(20),
                              onTap: () => _downloadGeneratedImage(
                                context, b64,
                              ),
                              child: Container(
                                padding: const EdgeInsets.all(7),
                                decoration: BoxDecoration(
                                  borderRadius: BorderRadius.circular(20),
                                  border: Border.all(
                                    color: Colors.white.withValues(alpha: 0.2),
                                  ),
                                ),
                                child: Icon(
                                  Icons.download_rounded,
                                  size: 16,
                                  color: Colors.white.withValues(alpha: 0.9),
                                ),
                              ),
                            ),
                          ),
                        ),
                        const Positioned(
                          bottom: 3,
                          right: 3,
                          child: LogoWatermark(size: 6),
                        ),
                      ],
                    ),
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

  Widget _buildGeneratedMedia(
    BuildContext context,
    ChatMessage msg,
    ColorScheme cs,
  ) {
    final t = msg.fileType.toLowerCase();
    if (t == 'mp4' || t == 'webm' || t == 'mov' || t == 'm4v') {
      // On the web build the native HTML5 <video> element is far more reliable
      // than the video_player controller (which often fails to initialize from a
      // blob URL), so the in-bubble preview/thumbnail always appears.
      if (kIsWeb) {
        return WebVideoPreview(
          b64: msg.fileData,
          fileName: msg.fileName,
          poster: msg.filePoster,
          onDownload: () => _downloadGeneratedVideo(context, msg),
        );
      }
      return _VideoPreviewBubble(
        msg: msg,
        cs: cs,
        buildFallback: (ctx, m, c) => _buildFileDownload(ctx, m, c),
        onDownload: (ctx, m) => _downloadGeneratedVideo(ctx, m),
      );
    }
    return _buildFileDownload(context, msg, cs);
  }

  Widget _buildFileDownload(
    BuildContext context,
    ChatMessage msg,
    ColorScheme cs,
  ) {
    final icon = _fileIcon(msg.fileType);
    final label = msg.fileName.isNotEmpty
        ? msg.fileName
        : 'Download ${msg.fileType.toUpperCase()}';
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: GestureDetector(
        onTap: () => _saveOrOpenFile(context, msg),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
          decoration: BoxDecoration(
            color: cs.primaryContainer.withValues(alpha: 0.4),
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: cs.primary.withValues(alpha: 0.2)),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(icon, size: 22, color: cs.primary),
              const SizedBox(width: 8),
              Flexible(
                child: Text(
                  label,
                  style: TextStyle(
                    color: cs.primary,
                    fontWeight: FontWeight.w500,
                    fontSize: AppDimens.fontSizeSM,
                  ),
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              const SizedBox(width: 8),
              Icon(Icons.download, size: 18, color: cs.primary),
            ],
          ),
        ),
      ),
    );
  }

  IconData _fileIcon(String type) {
    switch (type) {
      case 'pdf':
        return Icons.picture_as_pdf;
      case 'docx':
      case 'doc':
        return Icons.description;
      case 'xlsx':
      case 'xls':
        return Icons.table_chart;
      case 'csv':
        return Icons.table_chart;
      case 'svg':
        return Icons.image;
      case 'png':
        return Icons.image;
      case 'json':
        return Icons.data_object;
      case 'html':
      case 'htm':
        return Icons.code;
      case 'md':
        return Icons.description;
      default:
        return Icons.insert_drive_file;
    }
  }

  void _saveOrOpenFile(BuildContext context, ChatMessage msg) {
    try {
      final bytes = base64Decode(msg.fileData);
      if (kIsWeb) {
        _downloadOnWeb(bytes, msg.fileName);
      } else {
        _saveToDisk(context, bytes, msg.fileName);
      }
    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('Could not open file'),
          behavior: SnackBarBehavior.floating,
        ),
      );
    }
  }

  void _saveToDisk(BuildContext context, Uint8List bytes, String name) {
    try {
      saveFileToDisk(bytes, name);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('Saved: $name'),
          behavior: SnackBarBehavior.floating,
          duration: const Duration(seconds: 3),
        ),
      );
    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('Could not save file'),
          behavior: SnackBarBehavior.floating,
        ),
      );
    }
  }

  void _downloadGeneratedImage(BuildContext context, String b64) {
    try {
      final bytes = base64Decode(b64);
      final name = 'acronous_image_${DateTime.now().millisecondsSinceEpoch}.png';
      if (kIsWeb) {
        _downloadOnWeb(bytes, name);
      } else {
        _saveToDisk(context, bytes, name);
      }
    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('Could not download image'),
          behavior: SnackBarBehavior.floating,
        ),
      );
    }
  }

  void _downloadGeneratedVideo(BuildContext context, ChatMessage msg) {
    try {
      final bytes = base64Decode(msg.fileData);
      final name = msg.fileName.isNotEmpty
          ? msg.fileName
          : 'acronous_video_${DateTime.now().millisecondsSinceEpoch}.mp4';
      if (kIsWeb) {
        _downloadOnWeb(bytes, name);
      } else {
        _saveToDisk(context, bytes, name);
      }
    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('Could not download video'),
          behavior: SnackBarBehavior.floating,
        ),
      );
    }
  }

  void _downloadOnWeb(Uint8List bytes, String name) {
    final ext = name.split('.').last.toLowerCase();
    final mimeTypes = <String, String>{
      'pdf': 'application/pdf',
      'docx':
          'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      'doc': 'application/msword',
      'xlsx':
          'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      'csv': 'text/csv',
      'png': 'image/png',
      'jpg': 'image/jpeg',
      'jpeg': 'image/jpeg',
      'gif': 'image/gif',
      'svg': 'image/svg+xml',
      'html': 'text/html',
      'htm': 'text/html',
      'json': 'application/json',
      'xml': 'application/xml',
      'md': 'text/markdown',
      'txt': 'text/plain',
      'mp4': 'video/mp4',
      'webm': 'video/webm',
      'mov': 'video/quicktime',
      'm4v': 'video/mp4',
      'mp3': 'audio/mpeg',
      'wav': 'audio/wav',
      'm4a': 'audio/mp4',
    };
    final mime = mimeTypes[ext] ?? 'application/octet-stream';
    final blob = base64Encode(bytes);
    final dataUri = 'data:$mime;base64,$blob';
    final anchor = web.HTMLAnchorElement();
    anchor.href = dataUri;
    anchor.target = '_blank';
    anchor.download = name;
    anchor.click();
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
          return FadeTransition(opacity: animation, child: child);
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

class _VideoPreviewBubble extends StatefulWidget {
  final ChatMessage msg;
  final ColorScheme cs;
  final Widget Function(BuildContext, ChatMessage, ColorScheme) buildFallback;
  final void Function(BuildContext, ChatMessage) onDownload;
  const _VideoPreviewBubble({
    required this.msg,
    required this.cs,
    required this.buildFallback,
    required this.onDownload,
  });

  @override
  State<_VideoPreviewBubble> createState() => _VideoPreviewBubbleState();
}

class _VideoPreviewBubbleState extends State<_VideoPreviewBubble> {
  VideoPlayerController? _controller;
  bool _ready = false;
  final bool _playing = false;
  bool _failed = false;
  String? _webUrl;

  @override
  void initState() {
    super.initState();
    _init();
  }

  Future<void> _init() async {
    try {
      final bytes = base64Decode(widget.msg.fileData);
      late VideoPlayerController c;
      if (kIsWeb) {
        // data: URIs don't reliably load in the HTML5 video element — use a
        // blob: URL so the preview thumbnail/player actually appears on web.
        _webUrl = createVideoObjectUrl(bytes);
        c = VideoPlayerController.networkUrl(Uri.parse(_webUrl!));
      } else {
        final dir = await getTemporaryDirectory();
        final file = File(
          '${dir.path}/acronous_${DateTime.now().microsecondsSinceEpoch}.mp4',
        );
        await file.writeAsBytes(bytes);
        c = VideoPlayerController.file(file);
      }
      await c.initialize();
      await c.setLooping(true);
      c.addListener(() {
        if (mounted) setState(() {});
      });
      if (mounted) {
        setState(() {
          _controller = c;
          _ready = true;
        });
      } else {
        c.dispose();
      }
    } catch (e) {
      if (mounted) setState(() => _failed = true);
    }
  }

  void _openFullScreen(BuildContext context) {
    final bytes = base64Decode(widget.msg.fileData);
    Navigator.of(context).push(
      PageRouteBuilder(
        opaque: true,
        pageBuilder: (ctx, animation, secondaryAnimation) => _VideoFullScreenPage(
          bytes: bytes,
          cs: widget.cs,
          onDownload: widget.onDownload,
          message: widget.msg,
        ),
        transitionsBuilder: (context, animation, secondaryAnimation, child) =>
            FadeTransition(opacity: animation, child: child),
        transitionDuration: const Duration(milliseconds: 250),
      ),
    );
  }

  @override
  void dispose() {
    if (_webUrl != null) revokeVideoObjectUrl(_webUrl!);
    _controller?.dispose();
    super.dispose();
  }

  bool get _hasPoster => widget.msg.filePoster.isNotEmpty;

  @override
  Widget build(BuildContext context) {
    final cs = widget.cs;
    if (_failed) return widget.buildFallback(context, widget.msg, cs);

    // Show poster thumbnail immediately while video controller initializes,
    // so the bubble never appears blank (perceived as missing thumbnail).
    if (!_ready) {
      if (_hasPoster) {
        try {
          final posterBytes = base64Decode(widget.msg.filePoster);
          return Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: ClipRRect(
              borderRadius: BorderRadius.circular(14),
              child: Container(
                constraints: const BoxConstraints(maxWidth: 340, maxHeight: 300),
                child: AspectRatio(
                  aspectRatio: 16 / 9,
                  child: Stack(
                    fit: StackFit.expand,
                    children: [
                      Image.memory(posterBytes, fit: BoxFit.cover, gaplessPlayback: true),
                      const Positioned.fill(
                        child: DecoratedBox(
                          decoration: BoxDecoration(
                            gradient: LinearGradient(
                              begin: Alignment.topCenter,
                              end: Alignment.bottomCenter,
                              colors: [Colors.transparent, Colors.black26],
                              stops: [0.6, 1.0],
                            ),
                          ),
                        ),
                      ),
                      Center(
                        child: Container(
                          padding: const EdgeInsets.all(12),
                          decoration: const BoxDecoration(color: Colors.black54, shape: BoxShape.circle),
                          child: const Icon(Icons.play_arrow_rounded, color: Colors.white, size: 32),
                        ),
                      ),
                      Positioned.fill(
                        child: GestureDetector(
                          onTap: () => _openFullScreen(context),
                          child: Container(color: Colors.transparent),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          );
        } catch (_) {}
      }
      return Padding(
        padding: const EdgeInsets.only(bottom: 8),
        child: Container(
          width: 340,
          height: 190,
          decoration: BoxDecoration(
            color: cs.surfaceContainerHighest.withValues(alpha: 0.2),
            borderRadius: BorderRadius.circular(14),
          ),
          child: const Center(child: CircularProgressIndicator(strokeWidth: 2)),
        ),
      );
    }

    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Container(
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(14),
          boxShadow: [
            BoxShadow(
              color: Colors.black.withValues(alpha: 0.12),
              blurRadius: 12,
              offset: const Offset(0, 4),
            ),
          ],
        ),
        child: ClipRRect(
          borderRadius: BorderRadius.circular(14),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 340, maxHeight: 300),
            child: AspectRatio(
              aspectRatio: _controller?.value.aspectRatio ?? 16 / 9,
              child: Stack(
                fit: StackFit.expand,
                children: [
                  if (_ready && _controller != null)
                    GestureDetector(
                      onTap: () => _openFullScreen(context),
                      child: VideoPlayer(_controller!),
                    )
                  else
                    Container(
                      color: cs.surfaceContainerHighest.withValues(alpha: 0.2),
                      child: const Center(
                        child: CircularProgressIndicator(strokeWidth: 2),
                      ),
                    ),
                  if (_ready && !_playing)
                    Positioned.fill(
                      child: GestureDetector(
                        onTap: () => _openFullScreen(context),
                        child: Container(
                          color: Colors.black.withValues(alpha: 0.25),
                          child: Center(
                            child: Container(
                              padding: const EdgeInsets.all(14),
                              decoration: const BoxDecoration(
                                color: Colors.black54,
                                shape: BoxShape.circle,
                              ),
                              child: const Icon(
                                Icons.play_arrow_rounded,
                                size: 38,
                                color: Colors.white,
                              ),
                            ),
                          ),
                        ),
                      ),
                    ),
                  if (_ready)
                    Positioned(
                      right: 6,
                      bottom: 6,
                      child: Row(
                        children: [
                          GestureDetector(
                            onTap: () => _openFullScreen(context),
                            child: Container(
                              padding: const EdgeInsets.all(6),
                              decoration: const BoxDecoration(
                                color: Colors.black54,
                                shape: BoxShape.circle,
                              ),
                              child: const Icon(Icons.fullscreen_rounded,
                                  color: Colors.white, size: 20),
                            ),
                          ),
                          const SizedBox(width: 8),
                          GestureDetector(
                            onTap: () => widget.onDownload(context, widget.msg),
                            child: Container(
                              padding: const EdgeInsets.all(6),
                              decoration: const BoxDecoration(
                                color: Colors.black54,
                                shape: BoxShape.circle,
                              ),
                              child: const Icon(Icons.download_rounded,
                                  color: Colors.white, size: 20),
                            ),
                          ),
                        ],
                      ),
                    ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _VideoFullScreenPage extends StatefulWidget {
  final Uint8List bytes;
  final ColorScheme cs;
  final void Function(BuildContext, ChatMessage) onDownload;
  final ChatMessage message;
  const _VideoFullScreenPage({
    required this.bytes,
    required this.cs,
    required this.onDownload,
    required this.message,
  });
  @override
  State<_VideoFullScreenPage> createState() => _VideoFullScreenPageState();
}

class _VideoFullScreenPageState extends State<_VideoFullScreenPage> {
  VideoPlayerController? _controller;
  bool _ready = false;
  bool _playing = false;

  @override
  void initState() {
    super.initState();
    _init();
  }

  Future<void> _init() async {
    try {
      late VideoPlayerController c;
      if (kIsWeb) {
        final url = createVideoObjectUrl(widget.bytes);
        c = VideoPlayerController.networkUrl(Uri.parse(url));
      } else {
        final dir = await getTemporaryDirectory();
        final file = File(
          '${dir.path}/acronous_fs_${DateTime.now().microsecondsSinceEpoch}.mp4',
        );
        await file.writeAsBytes(widget.bytes);
        c = VideoPlayerController.file(file);
      }
      await c.initialize();
      await c.setLooping(true);
      c.addListener(() {
        if (mounted) setState(() => _playing = c.value.isPlaying);
      });
      await c.play();
      if (mounted) setState(() => _ready = true);
    } catch (e) {
      if (mounted) setState(() => _ready = true);
    }
  }

  void _close() => Navigator.of(context).pop();

  String _fmt(Duration d) {
    final m = d.inMinutes.toString().padLeft(1, '0');
    final s = (d.inSeconds % 60).toString().padLeft(2, '0');
    return '$m:$s';
  }

  @override
  void dispose() {
    _controller?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final cs = widget.cs;
    return Scaffold(
      backgroundColor: Colors.black,
      body: Stack(
        children: [
          Center(
            child: _ready && _controller != null
                ? AspectRatio(
                    aspectRatio: _controller!.value.aspectRatio,
                    child: VideoPlayer(_controller!),
                  )
                : const CircularProgressIndicator(),
          ),
          Positioned(
            top: 12,
            right: 12,
            child: IconButton(
              icon: const Icon(Icons.close_rounded, color: Colors.white, size: 28),
              onPressed: _close,
            ),
          ),
          if (_ready && _controller != null)
            Positioned(
              left: 0,
              right: 0,
              bottom: 0,
              child: Container(
                color: Colors.black54,
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
                child: Row(
                  children: [
                    IconButton(
                      icon: Icon(
                        _playing ? Icons.pause : Icons.play_arrow,
                        color: Colors.white,
                      ),
                      onPressed: () {
                        final c = _controller!;
                        if (c.value.isPlaying) {
                          c.pause();
                        } else {
                          c.play();
                        }
                      },
                    ),
                    Expanded(
                      child: VideoProgressIndicator(
                        _controller!,
                        allowScrubbing: true,
                        colors: VideoProgressColors(
                          playedColor: cs.primary,
                          bufferedColor: Colors.white38,
                          backgroundColor: Colors.white24,
                        ),
                      ),
                    ),
                    Text(
                      '${_fmt(_controller!.value.position)} / ${_fmt(_controller!.value.duration)}',
                      style: const TextStyle(color: Colors.white70, fontSize: 12),
                    ),
                    IconButton(
                      icon: const Icon(Icons.download_rounded, color: Colors.white),
                      onPressed: () => widget.onDownload(context, widget.message),
                    ),
                  ],
                ),
              ),
            ),
          // Esc key closes the fullscreen player (web / desktop)
          Focus(
            autofocus: true,
            onKeyEvent: (node, event) {
              if (event is KeyDownEvent &&
                  event.logicalKey == LogicalKeyboardKey.escape) {
                _close();
                return KeyEventResult.handled;
              }
              return KeyEventResult.ignored;
            },
            child: const SizedBox.shrink(),
          ),
        ],
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

