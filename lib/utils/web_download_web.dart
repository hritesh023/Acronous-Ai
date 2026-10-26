import 'dart:convert';
import 'dart:typed_data';
import 'package:web/web.dart' as web;

void downloadOnWeb(Uint8List bytes, String name) {
  final ext = name.split('.').last.toLowerCase();
  final mimeTypes = <String, String>{
    'pdf': 'application/pdf',
    'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'doc': 'application/msword',
    'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
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
