import 'dart:convert';
import 'dart:typed_data';
import 'package:http/http.dart' as http;
import '../config/app_config.dart';

class ApiClient {
  final String baseUrl;

  ApiClient({String? baseUrl})
      : baseUrl = baseUrl ?? AppConfig.instance.apiBaseUrl;

  String get _chatPath => AppConfig.instance.apiChatPath;
  String get _imagePath => AppConfig.instance.apiImageChatPath;
  String get _filePath => AppConfig.instance.apiFilePath;
  String get _imageGenPath => AppConfig.instance.apiImageGeneratePath;
  String get _imageEditPath => AppConfig.instance.apiImageEditPath;
  String get _sessionId => AppConfig.instance.defaultSessionId;

  Duration get _chatTimeout => AppConfig.instance.apiChatTimeout;
  Duration get _imageTimeout => AppConfig.instance.apiImageTimeout;
  Duration get _fileTimeout => AppConfig.instance.apiFileTimeout;
  Duration get _imageGenTimeout => AppConfig.instance.apiImageGenTimeout;
  Duration get _imageEditTimeout => AppConfig.instance.apiImageGenTimeout;

  Map<String, String> get _jsonHeaders => {
        'Content-Type': 'application/json',
      };

  Future<http.Response> _withTimeout(Future<http.Response> call, Duration timeout) {
    if (timeout.inSeconds > 0) {
      return call.timeout(timeout);
    }
    return call;
  }

  Future<http.StreamedResponse> _withStreamTimeout(Future<http.StreamedResponse> call, Duration timeout) {
    if (timeout.inSeconds > 0) {
      return call.timeout(timeout);
    }
    return call;
  }

  Future<Map<String, dynamic>> chat({
    required String message,
    String? sessionId,
  }) async {
    final uri = Uri.parse('$baseUrl$_chatPath');
    final resp = await _withTimeout(
      http.post(
        uri,
        headers: _jsonHeaders,
        body: jsonEncode({
          'message': message,
          'session_id': sessionId ?? _sessionId,
        }),
      ),
      _chatTimeout,
    );
    if (resp.statusCode != 200) {
      throw Exception('Chat API error: ${resp.statusCode} ${resp.body}');
    }
    return jsonDecode(resp.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> chatWithImage({
    required String message,
    required Uint8List imageBytes,
    required String fileName,
    String? sessionId,
  }) async {
    final uri = Uri.parse('$baseUrl$_imagePath');
    final request = http.MultipartRequest('POST', uri);
    request.fields['message'] = message;
    request.fields['session_id'] = sessionId ?? _sessionId;
    request.files.add(
      http.MultipartFile.fromBytes('file', imageBytes, filename: fileName),
    );
    final resp = await _withStreamTimeout(request.send(), _imageTimeout);
    final body = await resp.stream.bytesToString();
    if (resp.statusCode != 200) {
      throw Exception('Image API error: ${resp.statusCode} $body');
    }
    return jsonDecode(body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> uploadFile({
    required Uint8List fileBytes,
    required String fileName,
    required String message,
    String? sessionId,
  }) async {
    final uri = Uri.parse('$baseUrl$_filePath');
    final request = http.MultipartRequest('POST', uri);
    request.fields['message'] = message;
    request.fields['session_id'] = sessionId ?? _sessionId;
    request.files.add(
      http.MultipartFile.fromBytes('file', fileBytes, filename: fileName),
    );
    final resp = await _withStreamTimeout(request.send(), _fileTimeout);
    final body = await resp.stream.bytesToString();
    if (resp.statusCode != 200) {
      throw Exception('File upload error: ${resp.statusCode} $body');
    }
    return jsonDecode(body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> generateImage({
    required String prompt,
    String? sessionId,
  }) async {
    final params = {
      'prompt': prompt,
      'session_id': sessionId ?? _sessionId,
    };
    final uri = Uri.parse('$baseUrl$_imageGenPath').replace(queryParameters: params);
    final resp = await _withTimeout(http.get(uri), _imageGenTimeout);
    if (resp.statusCode != 200) {
      String detail = '';
      try {
        final body = jsonDecode(resp.body) as Map<String, dynamic>;
        detail = body['response'] as String? ?? body['detail'] as String? ?? '';
      } catch (_) {}
      throw Exception(detail.isNotEmpty ? detail : 'Image generation failed (${resp.statusCode})');
    }
    final b64 = base64Encode(resp.bodyBytes);
    return {'response': prompt, 'image_data': b64, 'type': 'image_gen'};
  }

  Future<Map<String, dynamic>> editImage({
    required String message,
    required Uint8List imageBytes,
    required String fileName,
    String? sessionId,
  }) async {
    final uri = Uri.parse('$baseUrl$_imageEditPath');
    final request = http.MultipartRequest('POST', uri);
    request.fields['message'] = message;
    request.fields['session_id'] = sessionId ?? _sessionId;
    request.files.add(
      http.MultipartFile.fromBytes('file', imageBytes, filename: fileName),
    );
    final resp = await _withStreamTimeout(request.send(), _imageEditTimeout);
    final body = await resp.stream.bytesToString();
    if (resp.statusCode != 200) {
      throw Exception('Image edit error: ${resp.statusCode} $body');
    }
    return jsonDecode(body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> analyzeImage({
    required Uint8List imageBytes,
    required String fileName,
    String? sessionId,
  }) async {
    final uri = Uri.parse('$baseUrl$_imagePath');
    final request = http.MultipartRequest('POST', uri);
    request.fields['message'] = AppConfig.instance.cameraAnalysisPrompt;
    request.fields['session_id'] = sessionId ?? _sessionId;
    request.files.add(
      http.MultipartFile.fromBytes('file', imageBytes, filename: fileName),
    );
    final resp = await _withStreamTimeout(request.send(), _imageTimeout);
    final body = await resp.stream.bytesToString();
    if (resp.statusCode != 200) {
      throw Exception('Image analysis error: ${resp.statusCode} $body');
    }
    return jsonDecode(body) as Map<String, dynamic>;
  }
}
