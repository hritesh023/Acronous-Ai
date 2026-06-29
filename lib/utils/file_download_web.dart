import 'dart:convert';
import 'dart:html' as html;
import 'dart:typed_data';

void downloadFile(Uint8List bytes, String name) {
  final blob = base64Encode(bytes);
  final dataUri = 'data:application/octet-stream;base64,$blob';
  final anchor = html.AnchorElement(href: dataUri)
    ..target = '_blank'
    ..download = name;
  anchor.click();
}
