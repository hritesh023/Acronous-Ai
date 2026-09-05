import 'dart:typed_data';
import 'dart:js_interop';
import 'package:web/web.dart' as web;

/// Create a blob: URL for in-memory video bytes so the HTML5 player can load
/// them on the web build (data: URIs are unreliable for video in browsers).
String createVideoObjectUrl(List<int> bytes) {
  final data = Uint8List.fromList(bytes);
  final blob = web.Blob(
    [data.toJS].toJS,
    web.BlobPropertyBag(type: 'video/mp4'),
  );
  return web.URL.createObjectURL(blob);
}

void revokeVideoObjectUrl(String url) {
  web.URL.revokeObjectURL(url);
}
