import 'package:flutter/widgets.dart';

/// Non-web fallback for the in-chat video preview. The real implementation
/// (video_preview_web.dart) is selected automatically on the web build.
class WebVideoPreview extends StatelessWidget {
  final String b64;
  final String fileName;
  final String poster;
  final VoidCallback onDownload;

  const WebVideoPreview({
    super.key,
    required this.b64,
    required this.fileName,
    this.poster = '',
    required this.onDownload,
  });

  @override
  Widget build(BuildContext context) => const SizedBox.shrink();
}
