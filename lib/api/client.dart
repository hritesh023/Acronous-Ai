import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';
import 'package:flutter/foundation.dart' show debugPrint;
import 'package:http/http.dart' as http;
import '../config/app_config.dart';

class ApiException implements Exception {
  final int statusCode;
  final String message;
  final Map<String, dynamic>? body;

  ApiException(this.statusCode, this.message, [this.body]);

  @override
  String toString() => 'ApiException($statusCode): $message';
}

class ChatRequest {
  final String query;
  final String? sessionId;
  final Map<String, dynamic>? context;
  final List<Map<String, String>>? messages;
  final bool? webSearchEnabled;
  final String? model;

  ChatRequest({
    required this.query,
    this.sessionId,
    this.context,
    this.messages,
    this.webSearchEnabled,
    this.model,
  });

  Map<String, dynamic> toJson() => {
    'query': query,
    if (sessionId != null) 'session_id': sessionId,
    if (context != null) 'context': context,
    if (messages != null) 'messages': messages,
    if (webSearchEnabled != null) 'web_search_enabled': webSearchEnabled,
    if (model != null) 'model': model,
  };
}

class Source {
  final String title;
  final String? url;

  Source({required this.title, this.url});
}

class ChatResponse {
  final String content;
  final String type;
  final List<Source> sources;
  final Map<String, dynamic>? analysis;
  final String sessionId;
  final String? imageUrl;
  final String? imageBase64;
  final String? videoUrl;
  final String? audioUrl;
  final int complexity;
  final String complexityLabel;

  ChatResponse({
    required this.content,
    this.type = 'chat',
    this.sources = const [],
    this.analysis,
    required this.sessionId,
    this.imageUrl,
    this.imageBase64,
    this.videoUrl,
    this.audioUrl,
    this.complexity = 0,
    this.complexityLabel = 'simple',
  });

  factory ChatResponse.fromJson(Map<String, dynamic> json) => ChatResponse(
    content: json['content'] as String? ?? '',
    type: json['type'] as String? ?? 'chat',
    sources: json['sources'] != null
        ? (json['sources'] as List)
              .map(
                (s) => Source(
                  title: s['title'] as String? ?? '',
                  url: s['url'] as String?,
                ),
              )
              .toList()
        : [],
    analysis: json['analysis'] as Map<String, dynamic>?,
    sessionId: json['session_id'] as String? ?? '',
    imageUrl: json['image_url'] as String?,
    imageBase64:
        (json['image_base64'] as String?) ?? (json['image_data'] as String?),
    videoUrl: json['video_url'] as String?,
    audioUrl: json['audio_url'] as String?,
    complexity: json['complexity'] as int? ?? 0,
    complexityLabel: json['complexity_label'] as String? ?? 'simple',
  );
}

class ApiClient {
  String _baseUrl;
  String? _authToken;
  http.Client _client = http.Client();

  ApiClient({String baseUrl = '', this.httpClient}) : _baseUrl = baseUrl {
    if (httpClient != null) _client = httpClient!;
  }

  http.Client? httpClient;

  String get baseUrl => _baseUrl;
  void updateBaseUrl(String url) => _baseUrl = url;

  static String get _currentOrigin {
    final uri = Uri.base;
    if (uri.scheme != 'http' && uri.scheme != 'https') return '';
    if (uri.host.isEmpty) return '';
    final port = uri.port;
    if (port <= 0 || port == 80 || port == 443) {
      return '${uri.scheme}://${uri.host}';
    }
    return '${uri.scheme}://${uri.host}:$port';
  }

  static String _normalizeBaseUrl(String url) {
    final trimmed = url.trim();
    if (trimmed.isEmpty) return '';
    return trimmed.endsWith('/')
        ? trimmed.substring(0, trimmed.length - 1)
        : trimmed;
  }

  static Future<bool> _checkHealth(
    String url, {
    Duration timeout = const Duration(seconds: 5),
  }) async {
    final client = http.Client();
    try {
      final response = await client
          .get(Uri.parse('$url/v1/health'))
          .timeout(timeout);
      if (response.statusCode != 200) return false;
      try {
        final body = jsonDecode(response.body);
        if (body is Map && body['status'] == 'ok') return true;
      } catch (_) {}
      return false;
    } catch (_) {
      return false;
    } finally {
      client.close();
    }
  }

  static Future<String> detectBaseUrl({String? configuredUrl, String? savedUrl}) async {
    final currentOrigin = _normalizeBaseUrl(_currentOrigin);
    final candidates = <String>[
      'http://127.0.0.1:8000',
      'http://localhost:8000',
      if (currentOrigin.isNotEmpty) currentOrigin,
      ?savedUrl,
      ?configuredUrl,
    ];
    final checked = <String>{};

    for (final candidate in candidates) {
      final url = _normalizeBaseUrl(candidate);
      if (url.isEmpty || !checked.add(url)) continue;

      final isRemote = url.startsWith('https://');
      await _wake(url);
      final timeout = isRemote
          ? const Duration(seconds: 45)
          : const Duration(seconds: 12);
      final healthy = await _checkHealth(url, timeout: timeout);
      if (healthy) {
        debugPrint('[discover] Connected to: $url');
        return url;
      }
    }

    return '';
  }

  static Future<void> _wake(String url) async {
    final client = http.Client();
    try {
      await client
          .get(Uri.parse('$url/v1/wakeup'))
          .timeout(const Duration(seconds: 5));
    } catch (_) {
    } finally {
      client.close();
    }
  }

  void setAuthToken(String? token) => _authToken = token;

  void cancelCurrentRequest() {
    try {
      _client.close();
    } catch (_) {}
    _client = http.Client();
  }

  Map<String, String> get _headers => {
    'Content-Type': 'application/json',
    if (_authToken != null) 'Authorization': 'Bearer $_authToken',
  };

  Map<String, dynamic> _checkResponse(http.Response response) {
    final body = response.body;
    Map<String, dynamic> json;
    try {
      json = jsonDecode(body) as Map<String, dynamic>;
    } catch (e) {
      final status = response.statusCode;
      debugPrint(
        '[api] Non-JSON response ($status): ${body.substring(0, body.length.clamp(0, 500))}',
      );
      throw ApiException(
        status,
        'Server error ($status): ${body.substring(0, body.length.clamp(0, 200))}',
        <String, dynamic>{'response': body},
      );
    }
    if (response.statusCode < 200 || response.statusCode >= 300) {
      final msg =
          json['detail'] as String? ??
          json['message'] as String? ??
          json['error'] as String? ??
          'HTTP ${response.statusCode}';
      debugPrint('[api] Error response (${response.statusCode}): $msg');
      throw ApiException(response.statusCode, msg, json);
    }
    return json;
  }

  Future<Map<String, dynamic>> _get(String path, {Duration? timeout}) async {
    var future = _client.get(Uri.parse('$_baseUrl$path'), headers: _headers);
    if (timeout != null) future = future.timeout(timeout);
    return _checkResponse(await future);
  }

  Future<Map<String, dynamic>> _post(
    String path,
    Map<String, dynamic> body, {
    Duration? timeout,
  }) async {
    var future = _client.post(
      Uri.parse('$_baseUrl$path'),
      headers: _headers,
      body: jsonEncode(body),
    );
    if (timeout != null) future = future.timeout(timeout);
    return _checkResponse(await future);
  }

  Future<Map<String, dynamic>> _delete(String path, {Duration? timeout}) async {
    var future = _client.delete(Uri.parse('$_baseUrl$path'), headers: _headers);
    if (timeout != null) future = future.timeout(timeout);
    final response = await future;
    if (response.body.isEmpty && response.statusCode == 200) return {};
    return _checkResponse(response);
  }

  Future<Map<String, dynamic>> _put(
    String path,
    Map<String, dynamic> body, {
    Duration? timeout,
  }) async {
    var future = _client.put(
      Uri.parse('$_baseUrl$path'),
      headers: _headers,
      body: jsonEncode(body),
    );
    if (timeout != null) future = future.timeout(timeout);
    return _checkResponse(await future);
  }

  Future<Map<String, dynamic>> _uploadFile(
    String path,
    File file,
    Map<String, String> fields, {
    Duration? timeout,
  }) async {
    final request = http.MultipartRequest('POST', Uri.parse('$_baseUrl$path'));
    if (_authToken != null) {
      request.headers['Authorization'] = 'Bearer $_authToken';
    }
    request.fields.addAll(fields);
    request.files.add(await http.MultipartFile.fromPath('file', file.path));
    var future = request.send();
    if (timeout != null) future = future.timeout(timeout);
    final streamedResponse = await future;
    final response = await http.Response.fromStream(streamedResponse);
    return _checkResponse(response);
  }

  Future<Map<String, dynamic>> _multipartPost(
    String path,
    Map<String, String> fields,
    Uint8List fileBytes,
    String fileName, {
    Duration? timeout,
  }) async {
    final uri = Uri.parse('$_baseUrl$path');
    final request = http.MultipartRequest('POST', uri);
    if (_authToken != null) {
      request.headers['Authorization'] = 'Bearer $_authToken';
    }
    request.fields.addAll(fields);
    request.files.add(
      http.MultipartFile.fromBytes('file', fileBytes, filename: fileName),
    );
    var future = request.send();
    if (timeout != null) future = future.timeout(timeout);
    final streamed = await future;
    final response = await http.Response.fromStream(streamed);
    return _checkResponse(response);
  }

  Future<ChatResponse> chatRequest(ChatRequest request) async {
    final resp = await _post('/api/chat', request.toJson());
    return ChatResponse.fromJson(resp);
  }

  Future<ChatResponse> chat({
    required String message,
    String? sessionId,
    String? timezone,
    String? location,
    Duration? timeout,
  }) async {
    final body = <String, dynamic>{
      'message': message,
      'session_id': sessionId ?? 'default',
    };
    if (timezone != null && timezone.isNotEmpty) {
      body['timezone'] = timezone;
    }
    if (location != null && location.isNotEmpty) {
      body['location'] = location;
    }
    final actualTimeout = timeout ?? AppConfig.instance.apiChatTimeout;
    final resp = await _post('/v1/chat', body,
        timeout: actualTimeout > Duration.zero ? actualTimeout : null);
    return ChatResponse(
      content: resp['response'] as String? ?? '',
      sessionId: resp['session_id'] as String? ?? sessionId ?? '',
      type: resp['type'] as String? ?? 'chat',
      complexity: resp['complexity'] as int? ?? 0,
      complexityLabel: resp['complexity_label'] as String? ?? 'simple',
      imageBase64: resp['image_data'] as String?,
    );
  }

  Stream<String> chatStream(String message, {String? sessionId}) async* {
    final uri = Uri.parse('$_baseUrl/v1/chat/stream');
    final client = http.Client();
    try {
      final request = http.Request('POST', uri)
        ..headers['Content-Type'] = 'application/json'
        ..body = jsonEncode({
          'message': message,
          'session_id': sessionId ?? 'default',
        });
      final streamedResp = await client.send(request);
      final lines = streamedResp.stream
          .transform(utf8.decoder)
          .transform(const LineSplitter());
      await for (final line in lines) {
        if (line.startsWith('data: ')) {
          final data = line.substring(6);
          if (data.trim().isEmpty) continue;
          try {
            final json = jsonDecode(data) as Map<String, dynamic>;
            if (json['done'] == true) break;
            if (json['error'] != null) throw Exception(json['error']);
            yield json['content'] as String? ?? '';
          } catch (_) {
            rethrow;
          }
        }
      }
    } finally {
      client.close();
    }
  }

  Future<ChatResponse> chatWithImage({
    required String message,
    required Uint8List imageBytes,
    required String fileName,
    String? sessionId,
    Duration? timeout,
  }) async {
    final fields = <String, String>{'message': message};
    if (sessionId != null) fields['session_id'] = sessionId;
    final resp = await _multipartPost(
      '/v1/chat/image',
      fields,
      imageBytes,
      fileName,
      timeout: timeout,
    );
    return ChatResponse(
      content: resp['response'] as String? ?? '',
      sessionId: resp['session_id'] as String? ?? sessionId ?? '',
      type: resp['type'] as String? ?? 'chat',
    );
  }

  Future<ChatResponse> uploadFile({
    required Uint8List fileBytes,
    required String fileName,
    String message = '',
    String? sessionId,
    Duration? timeout,
  }) async {
    final fields = <String, String>{'message': message};
    if (sessionId != null) fields['session_id'] = sessionId;
    final resp = await _multipartPost(
      '/v1/chat/file',
      fields,
      fileBytes,
      fileName,
      timeout: timeout,
    );
    return ChatResponse(
      content: resp['response'] as String? ?? '',
      sessionId: resp['session_id'] as String? ?? sessionId ?? '',
      type: resp['type'] as String? ?? 'chat',
    );
  }

  Future<Map<String, dynamic>> generateImage({
    required String prompt,
    String? sessionId,
    String? style,
    Duration? timeout,
  }) async {
    final body = <String, dynamic>{'prompt': prompt};
    if (style != null) body['style'] = style;
    if (sessionId != null) body['session_id'] = sessionId;
    final t = timeout ?? AppConfig.instance.apiImageGenTimeout;
    return _post(
      '/v1/image/generate',
      body,
      timeout: t > Duration.zero ? t : null,
    );
  }

  Future<Map<String, dynamic>> generateQRCode({
    required String data,
    int? size,
  }) async {
    final body = <String, dynamic>{'data': data};
    if (size != null) body['size'] = size;
    return _post('/api/image/qr-code', body);
  }

  Future<Map<String, dynamic>> redesignImage(
    File file,
    String prompt, {
    Duration? timeout,
  }) async {
    return _uploadFile('/api/image/redesign', file, {
      'prompt': prompt,
    }, timeout: timeout);
  }

  Future<ChatResponse> analyzeImage(
    File file, {
    String? sessionId,
    List<Map<String, String>>? messages,
    String? analysisType,
    Duration? timeout,
  }) async {
    final request = http.MultipartRequest(
      'POST',
      Uri.parse('$_baseUrl/api/image/analyze'),
    );
    if (_authToken != null) {
      request.headers['Authorization'] = 'Bearer $_authToken';
    }
    request.files.add(await http.MultipartFile.fromPath('file', file.path));
    if (sessionId != null) request.fields['session_id'] = sessionId;
    if (messages != null) {
      request.fields['messages'] = jsonEncode(messages);
    }
    if (analysisType != null) request.fields['analysis_type'] = analysisType;
    var analyzeFuture = request.send();
    if (timeout != null) analyzeFuture = analyzeFuture.timeout(timeout);
    final streamedResponse = await analyzeFuture;
    final response = await http.Response.fromStream(streamedResponse);
    return ChatResponse.fromJson(
      jsonDecode(response.body) as Map<String, dynamic>,
    );
  }

  Future<Map<String, dynamic>> webSearch(
    String query, {
    int maxResults = 5,
  }) async {
    return _post('/api/tools/search', {
      'query': query,
      'max_results': maxResults,
    });
  }

  Future<Map<String, dynamic>> transcribeAudio(File file) async {
    final request = http.MultipartRequest(
      'POST',
      Uri.parse('$_baseUrl/api/voice/transcribe'),
    );
    if (_authToken != null) {
      request.headers['Authorization'] = 'Bearer $_authToken';
    }
    request.files.add(await http.MultipartFile.fromPath('file', file.path));
    final streamedResponse = await request.send();
    final response = await http.Response.fromStream(streamedResponse);
    return jsonDecode(response.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> processDocument(File file) async {
    final request = http.MultipartRequest(
      'POST',
      Uri.parse('$_baseUrl/api/tools/process-document'),
    );
    if (_authToken != null) {
      request.headers['Authorization'] = 'Bearer $_authToken';
    }
    request.files.add(await http.MultipartFile.fromPath('file', file.path));
    final streamedResponse = await request.send();
    final response = await http.Response.fromStream(streamedResponse);
    return jsonDecode(response.body) as Map<String, dynamic>;
  }

  Future<List<Map<String, dynamic>>> listModels() async {
    final resp = await _get('/api/models/list');
    return (resp['models'] as List? ?? resp as List?)
            ?.cast<Map<String, dynamic>>() ??
        [];
  }

  Future<Map<String, dynamic>> getStatus() => _get('/api/status');

  Future<Map<String, dynamic>> healthCheck() => _get('/health');

  Future<Map<String, dynamic>> getConfig() async {
    return _get('/api/config');
  }

  Future<Map<String, dynamic>> wakeup() async {
    try {
      return await _get('/v1/wakeup', timeout: const Duration(seconds: 5));
    } catch (_) {
      return {'status': 'ok'};
    }
  }

  Future<Map<String, dynamic>> getMe() => _get('/api/auth/me');

  Future<List<Map<String, dynamic>>> listConversations() async {
    final resp = await _get('/api/conversations');
    return (resp['conversations'] as List? ?? resp as List?)
            ?.cast<Map<String, dynamic>>() ??
        [];
  }

  Future<Map<String, dynamic>> createConversation({
    String title = 'New Conversation',
  }) async {
    return _post('/api/conversations', {'title': title});
  }

  Future<void> deleteConversation(String convId) async {
    await _delete('/api/conversations/$convId');
  }

  Future<Map<String, dynamic>> exportConversation(
    String convId, {
    String format = 'markdown',
  }) async {
    final response = await _client.get(
      Uri.parse('$_baseUrl/api/conversations/$convId/export?fmt=$format'),
      headers: _headers,
    );
    return {'content': response.body};
  }

  Future<Map<String, dynamic>> updateConversation(
    String convId,
    String title,
  ) async {
    return _put('/api/conversations/$convId', {'title': title});
  }

  Future<List<Map<String, dynamic>>> listMessages(String convId) async {
    final resp = await _get('/api/conversations/$convId/messages');
    return (resp['messages'] as List? ?? resp as List?)
            ?.cast<Map<String, dynamic>>() ??
        [];
  }

  Future<Map<String, dynamic>> addMessage(
    String convId, {
    required String role,
    required String content,
    String msgType = 'text',
    String? sources,
    String? label,
    String? image,
    String? mediaUrl,
    String? videoUrl,
    String? audioUrl,
  }) async {
    final body = <String, dynamic>{
      'role': role,
      'content': content,
      'msg_type': msgType,
    };
    if (sources != null) body['sources'] = sources;
    if (label != null) body['label'] = label;
    if (image != null) body['image'] = image;
    if (mediaUrl != null) body['media_url'] = mediaUrl;
    if (videoUrl != null) body['video_url'] = videoUrl;
    if (audioUrl != null) body['audio_url'] = audioUrl;
    return _post('/api/conversations/$convId/messages', body);
  }

  Future<Map<String, dynamic>> syncConversations(
    List<Map<String, dynamic>> conversations,
  ) async {
    return _post('/api/conversations/sync', {'conversations': conversations});
  }

  Future<Map<String, dynamic>> updateLLMConfig({
    String? provider,
    String? apiKey,
    String? model,
    String? apiUrl,
  }) async {
    final body = <String, dynamic>{};
    if (provider != null) body['provider'] = provider;
    if (apiKey != null) body['api_key'] = apiKey;
    if (model != null) body['model'] = model;
    if (apiUrl != null) body['api_url'] = apiUrl;
    return _post('/api/config/llm', body);
  }

  Future<Map<String, dynamic>> getLLMConfig() => _get('/api/config/llm');
}
