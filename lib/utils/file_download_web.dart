import 'dart:convert';
import 'dart:typed_data';
import 'package:web/web.dart' as web;

void downloadFile(Uint8List bytes, String name) {
  final blob = base64Encode(bytes);
  final dataUri = 'data:application/octet-stream;base64,$blob';
  final anchor = web.HTMLAnchorElement();
  anchor.href = dataUri;
  anchor.target = '_blank';
  anchor.download = name;
  anchor.click();
}
