import 'dart:io';
import 'dart:typed_data';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:http/http.dart' as http;
import 'package:image_picker/image_picker.dart';
import 'package:file_picker/file_picker.dart';
import '../config/app_config.dart';
import '../models/message.dart';

class FileService {
  final ImagePicker _picker;

  FileService({ImagePicker? picker}) : _picker = picker ?? ImagePicker();

  Future<MessageAttachment?> pickImageFromCamera({
    double? maxWidth,
    double? maxHeight,
    int? quality,
  }) async {
    final config = AppConfig.instance;
    final XFile? image = await _picker.pickImage(
      source: ImageSource.camera,
      maxWidth: maxWidth ?? config.imagePickerMaxWidth,
      maxHeight: maxHeight ?? config.imagePickerMaxHeight,
      imageQuality: quality ?? config.imagePickerQuality,
    );
    if (image == null) return null;
    return MessageAttachment(
      name: image.name,
      path: image.path,
      type: AttachmentType.image,
    );
  }

  Future<MessageAttachment?> pickImageFromGallery({
    double? maxWidth,
    double? maxHeight,
    int? quality,
  }) async {
    final config = AppConfig.instance;
    final XFile? image = await _picker.pickImage(
      source: ImageSource.gallery,
      maxWidth: maxWidth ?? config.imagePickerMaxWidth,
      maxHeight: maxHeight ?? config.imagePickerMaxHeight,
      imageQuality: quality ?? config.imagePickerQuality,
    );
    if (image == null) return null;
    return MessageAttachment(
      name: image.name,
      path: image.path,
      type: AttachmentType.image,
    );
  }

  Future<MessageAttachment?> pickFile({
    List<String>? allowedExtensions,
  }) async {
    final config = AppConfig.instance;
    final result = await FilePicker.platform.pickFiles(
      type: FileType.custom,
      allowedExtensions: allowedExtensions ?? config.allowedFileExtensions,
    );
    if (result == null) return null;
    final file = result.files.single;
    final ext = file.extension?.toLowerCase() ?? '';
    if (kIsWeb && file.bytes != null) {
      return MessageAttachment(
        name: file.name,
        path: file.name,
        type: _inferType(ext),
        bytes: file.bytes,
      );
    }
    if (file.path == null) return null;
    return MessageAttachment(
      name: file.name,
      path: file.path!,
      type: _inferType(ext),
    );
  }

  static Future<Uint8List> readAttachmentBytes(MessageAttachment att) async {
    if (att.bytes != null) return att.bytes!;
    if (kIsWeb) {
      final resp = await http.get(Uri.parse(att.path));
      return resp.bodyBytes;
    }
    return File(att.path).readAsBytes();
  }

  static AttachmentType _inferType(String ext) {
    switch (ext) {
      case 'png':
      case 'jpg':
      case 'jpeg':
      case 'gif':
      case 'bmp':
      case 'webp':
        return AttachmentType.image;
      case 'mp3':
      case 'wav':
      case 'ogg':
      case 'aac':
      case 'flac':
        return AttachmentType.audio;
      case 'mp4':
      case 'avi':
      case 'mkv':
      case 'mov':
      case 'webm':
        return AttachmentType.video;
      case 'txt':
      case 'md':
      case 'csv':
      case 'json':
      case 'xml':
      case 'log':
        return AttachmentType.text;
      case 'pdf':
        return AttachmentType.pdf;
      default:
        return AttachmentType.other;
    }
  }
}
