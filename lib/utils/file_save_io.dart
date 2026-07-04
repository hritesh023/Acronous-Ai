import 'dart:io';
import 'dart:typed_data';

void saveFileToDisk(Uint8List bytes, String name) {
  final file = File('${Directory.systemTemp.path}/$name');
  file.writeAsBytesSync(bytes);
}
