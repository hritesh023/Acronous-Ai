import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';
import 'package:http/http.dart' as http;


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
    imageBase64: json['image_base64'] as String?,
    videoUrl: json['video_url'] as String?,
    audioUrl: json['audio_url'] as String?,
  );
}

class ApiClient {
  String _baseUrl;
  String? _authToken;
  final http.Client _client = http.Client();

  ApiClient({String baseUrl = ''}) : _baseUrl = baseUrl;

  String get baseUrl => _baseUrl;
  void updateBaseUrl(String url) => _baseUrl = url;

  void setAuthToken(String? token) => _authToken = token;

  Map<String, String> get _headers => {
    'Content-Type': 'application/json',
    if (_authToken != null) 'Authorization': 'Bearer $_authToken',
  };

  Future<Map<String, dynamic>> _get(String path) async {
    final response = await _client.get(
      Uri.parse('$_baseUrl$path'),
      headers: _headers,
    );
    return jsonDecode(response.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> _post(
    String path,
    Map<String, dynamic> body,
  ) async {
    final response = await _client.post(
      Uri.parse('$_baseUrl$path'),
      headers: _headers,
      body: jsonEncode(body),
    );
    return jsonDecode(response.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> _delete(String path) async {
    final response = await _client.delete(
      Uri.parse('$_baseUrl$path'),
      headers: _headers,
    );
    if (response.body.isEmpty) return {};
    return jsonDecode(response.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> _put(
    String path,
    Map<String, dynamic> body,
  ) async {
    final response = await _client.put(
      Uri.parse('$_baseUrl$path'),
      headers: _headers,
      body: jsonEncode(body),
    );
    return jsonDecode(response.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> _uploadFile(
    String path,
    File file,
    Map<String, String> fields,
  ) async {
    final request = http.MultipartRequest('POST', Uri.parse('$_baseUrl$path'));
    if (_authToken != null) {
      request.headers['Authorization'] = 'Bearer $_authToken';
    }
    request.fields.addAll(fields);
    request.files.add(await http.MultipartFile.fromPath('file', file.path));
    final streamedResponse = await request.send();
    final response = await http.Response.fromStream(streamedResponse);
    return jsonDecode(response.body) as Map<String, dynamic>;
  }

  Future<ChatResponse> chatRequest(ChatRequest request) async {
    final resp = await _post('/api/chat', request.toJson());
    return ChatResponse.fromJson(resp);
  }

  Future<ChatResponse> chat({
    required String message,
    String? sessionId,
  }) async {
    final resp = await _post('/v1/chat', {
      'message': message,
      'session_id': ?sessionId,
    });
    return ChatResponse(
      content: resp['response'] as String? ?? '',
      sessionId: resp['session_id'] as String? ?? sessionId ?? '',
      type: resp['type'] as String? ?? 'chat',
    );
  }

  Future<ChatResponse> chatWithImage({
    required String message,
    required Uint8List imageBytes,
    required String fileName,
    String? sessionId,
  }) async {
    final uri = Uri.parse('$_baseUrl/v1/chat/image');
    final request = http.MultipartRequest('POST', uri);
    request.fields['message'] = message;
    if (sessionId != null) request.fields['session_id'] = sessionId;
    request.files.add(
      http.MultipartFile.fromBytes('file', imageBytes, filename: fileName),
    );
    final streamed = await request.send();
    final response = await http.Response.fromStream(streamed);
    final resp = jsonDecode(response.body) as Map<String, dynamic>;
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
  }) async {
    final uri = Uri.parse('$_baseUrl/v1/chat/file');
    final request = http.MultipartRequest('POST', uri);
    request.fields['message'] = message;
    if (sessionId != null) request.fields['session_id'] = sessionId;
    request.files.add(
      http.MultipartFile.fromBytes('file', fileBytes, filename: fileName),
    );
    final streamed = await request.send();
    final response = await http.Response.fromStream(streamed);
    final resp = jsonDecode(response.body) as Map<String, dynamic>;
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
  }) async {
    final body = <String, dynamic>{'prompt': prompt};
    if (style != null) body['style'] = style;
    if (sessionId != null) body['session_id'] = sessionId;
    return _post('/v1/image/generate', body);
  }

  Future<Map<String, dynamic>> generateQRCode({
    required String data,
    int? size,
  }) async {
    final body = <String, dynamic>{'data': data};
    if (size != null) body['size'] = size;
    return _post('/api/image/qr-code', body);
  }

  Future<Map<String, dynamic>> redesignImage(File file, String prompt) async {
    return _uploadFile('/api/image/redesign', file, {'prompt': prompt});
  }

  Future<ChatResponse> analyzeImage(
    File file, {
    String? sessionId,
    List<Map<String, String>>? messages,
    String? analysisType,
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
    final streamedResponse = await request.send();
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
