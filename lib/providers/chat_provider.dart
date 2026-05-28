import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:image_picker/image_picker.dart';
import '../api/client.dart';
import '../config/app_config.dart';
import '../constants/app_constants.dart';
import '../models/message.dart';
import '../services/file_service.dart';
import '../services/preferences_service.dart';
import '../services/speech_service.dart';
import '../services/tts_service.dart';
import '../services/overlay_service.dart';
import '../widgets/camera_screen.dart';

class ChatProvider extends ChangeNotifier {
  final ApiClient _api;
  final PreferencesService _prefs;
  final FileService _fileService;
  final SpeechService _speech;
  final TtsService _tts;

  bool _isServerConnected = false;
  bool _serverCheckDone = false;
  bool _isConnecting = true;

  bool get isServerConnected => _isServerConnected;
  bool get serverCheckDone => _serverCheckDone;
  bool get isConnecting => _isConnecting;

  static const _serverNotFound = '';
  static const _serverError = '';
  static const _genericError = '';
  static const _privateInfoResponse = '';
  static final RegExp _privateInfoPattern = RegExp(
    r"\b(i am|i'm|i use|i run|i'm running|powered by|hosted on|served by|my backend|my model|my provider|my system|my infrastructure|my architecture)\b.{0,140}\b(openai|groq|anthropic|together|ollama|hugging\s*face|hf\s*space|api key|llm|backend|model|provider|system prompt|infrastructure)\b|\b(openai|groq|anthropic|together|ollama|hugging\s*face|hf\s*space)\b.{0,120}\b(powers me|is my provider|backend|model|runs me|hosts me)\b|\b(api key|secret|system prompt|internal configuration|backend technology|technical architecture|infrastructure details)\b|\b(as an ai (assistant|model|language model)|i am a (helpful|useful) (ai|assistant)|i am an ai)\b.{0,100}\b(created by|developed by|built by|made by)\b",
    caseSensitive: false,
    dotAll: true,
  );

  static String _sanitizeAssistantText(String text) {
    final trimmed = text.trim();
    if (trimmed.isEmpty) return '';
    final cleaned = trimmed
        .replaceAll(RegExp(r'\[Current date and time:[^\]]*\]'), '')
        .replaceAll(RegExp(r'\[Web-fetched [^\]]*\]'), '')
        .replaceAll(RegExp(r'\[User location:[^\]]*\]'), '')
        .replaceAll(RegExp(r'\n{3,}'), '\n\n')
        .trim();
    if (cleaned.isEmpty) {
      return trimmed;
    }
    if (_privateInfoPattern.hasMatch(cleaned)) {
      return cleaned;
    }
    return cleaned;
  }

  final List<Conversation> _conversations = [];
  Conversation? _currentConversation;
  bool _isLoading = false;
  bool _isTakingLong = false;
  bool get isTakingLong => _isTakingLong;
  ThemeMode _themeMode = ThemeMode.system;

  bool _isListening = false;
  String _voiceText = '';

  bool _isSpeaking = false;
  String? _speakingMessageId;

  final List<MessageAttachment> _pendingAttachments = [];

  String _searchQuery = '';

  double _ttsSpeed = 0.5;
  double _ttsPitch = 1.0;
  bool _autoSendVoice = false;
  bool _continuousVoiceEnabled = true;
  bool _backgroundAssistantEnabled = false;

  ChatProvider({
    ApiClient? api,
    PreferencesService? prefs,
    FileService? fileService,
    SpeechService? speech,
    TtsService? tts,
  }) : _api = api ?? ApiClient(baseUrl: AppConfig.instance.apiBaseUrl),
       _prefs = prefs ?? PreferencesService(),
       _fileService = fileService ?? FileService(),
       _speech = speech ?? SpeechService(),
       _tts = tts ?? TtsService() {
    _init();
  }

  Future<void> _init() async {
    await _loadPrefs();
    final savedUrl = await _prefs.loadServerUrl();
    if (savedUrl.isNotEmpty) {
      _api.updateBaseUrl(savedUrl);
    }
    await _initTts();
    await _discoverServer(savedUrl: savedUrl);
    _newConversation();
    _fetchLocationInfo();
  }

  Future<void> _discoverServer({int retries = 3, String? savedUrl}) async {
    _isServerConnected = false;
    _isConnecting = true;
    _serverCheckDone = false;
    notifyListeners();

    String? lastUrl;
    for (var attempt = 1; attempt <= retries; attempt++) {
      try {
        final bestUrl = await ApiClient.detectBaseUrl(
          configuredUrl: AppConfig.instance.apiBaseUrl,
          savedUrl: savedUrl,
        );
        lastUrl = bestUrl;
        if (bestUrl.isNotEmpty) {
          _api.updateBaseUrl(bestUrl);
          _isServerConnected = true;
          await _prefs.saveServerUrl(bestUrl);
          await _api.wakeup();
          _startKeepAlive();
          _isConnecting = false;
          _serverCheckDone = true;
          notifyListeners();
          return;
        }
        debugPrint('[discover] No server found on attempt $attempt');
      } catch (e) {
        debugPrint('[discover] Attempt $attempt failed: $e');
      }

      if (attempt < retries) {
        final delay = lastUrl?.startsWith('https://') == true
            ? attempt * 10
            : attempt * 3;
        await Future.delayed(Duration(seconds: delay));
      }
    }
    debugPrint(
      '[discover] All $retries attempts exhausted — server unreachable',
    );

    _isServerConnected = false;
    _isConnecting = false;
    _serverCheckDone = true;
    notifyListeners();
  }

  void _startKeepAlive() {
    Future.delayed(const Duration(minutes: 2), () async {
      try {
        await _api.wakeup();
      } catch (_) {
        _isServerConnected = false;
        _discoverServer(retries: 1);
      }
      if (_keepAliveActive) _startKeepAlive();
    });
  }

  final bool _keepAliveActive = true;

  List<Conversation> get conversations => _conversations;
  Conversation? get currentConversation => _currentConversation;
  bool get isLoading => _isLoading;
  ThemeMode get themeMode => _themeMode;
  bool get isListening => _isListening;
  String get voiceText => _voiceText;
  bool get isSpeaking => _isSpeaking;
  String? get speakingMessageId => _speakingMessageId;
  List<MessageAttachment> get pendingAttachments => _pendingAttachments;
  String get searchQuery => _searchQuery;
  double get ttsSpeed => _ttsSpeed;
  double get ttsPitch => _ttsPitch;
  bool get autoSendVoice => _autoSendVoice;
  bool get continuousVoiceEnabled => _continuousVoiceEnabled;
  bool get backgroundAssistantEnabled => _backgroundAssistantEnabled;

  List<Conversation> get filteredConversations {
    if (_searchQuery.isEmpty) return _conversations;
    final query = _searchQuery.toLowerCase();
    return _conversations
        .where((c) => c.displayTitle.toLowerCase().contains(query))
        .toList();
  }

  void _newConversation() {
    _currentConversation = Conversation(
      id: DateTime.now().millisecondsSinceEpoch.toString(),
    );
    _conversations.insert(0, _currentConversation!);
    _prefs.saveConversations(_conversations).catchError((_) {});
    notifyListeners();
  }

  void newChat() {
    _pendingAttachments.clear();
    _voiceText = '';
    _newConversation();
  }

  void setThemeMode(ThemeMode mode) {
    _themeMode = mode;
    _prefs.saveThemeMode(mode);
    notifyListeners();
  }

  void toggleTheme() {
    if (_themeMode == ThemeMode.system) {
      final brightness =
          WidgetsBinding.instance.platformDispatcher.platformBrightness;
      _themeMode = brightness == Brightness.dark
          ? ThemeMode.light
          : ThemeMode.dark;
    } else {
      _themeMode = _themeMode == ThemeMode.dark
          ? ThemeMode.light
          : ThemeMode.dark;
    }
    _prefs.saveThemeMode(_themeMode);
    notifyListeners();
  }

  void switchConversation(String id) {
    final idx = _conversations.indexWhere((c) => c.id == id);
    if (idx >= 0) {
      _currentConversation = _conversations[idx];
      _pendingAttachments.clear();
      _voiceText = '';
      notifyListeners();
    }
  }

  void deleteConversation(String id) {
    _conversations.removeWhere((c) => c.id == id);
    if (_currentConversation?.id == id) {
      if (_conversations.isNotEmpty) {
        _currentConversation = _conversations.first;
      } else {
        _newConversation();
      }
    }
    _prefs.saveConversations(_conversations).catchError((_) {});
    notifyListeners();
  }

  void setSearchQuery(String query) {
    _searchQuery = query;
    notifyListeners();
  }

  void setBackgroundAssistantEnabled(bool v) {
    _backgroundAssistantEnabled = v;
    _prefs.saveBackgroundAssistant(v);
    notifyListeners();
  }

  void cancelGeneration() {
    _isLoading = false;
    _isTakingLong = false;
    _api.cancelCurrentRequest();
    notifyListeners();
  }

  String _cachedLocation = '';
  String _cachedCity = '';
  String _cachedCountry = '';

  Future<void> _fetchLocationInfo() async {
    try {
      final resp = await http
          .get(Uri.parse('http://ip-api.com/json/'))
          .timeout(const Duration(seconds: 5));
      if (resp.statusCode == 200) {
        final data = jsonDecode(resp.body) as Map<String, dynamic>;
        if (data['status'] == 'success') {
          _cachedCity = (data['city'] as String?) ?? '';
          _cachedCountry = (data['country'] as String?) ?? '';
          final tz = (data['timezone'] as String?) ?? '';
          final city = _cachedCity;
          final country = _cachedCountry;
          if (city.isNotEmpty && country.isNotEmpty) {
            _cachedLocation = '$city, $country';
          } else if (city.isNotEmpty) {
            _cachedLocation = city;
          } else if (country.isNotEmpty) {
            _cachedLocation = country;
          }
          if (tz.isNotEmpty) {
            _cachedTimezoneName = tz;
          }
        }
      }
    } catch (_) {}
  }

  String _cachedTimezoneName = '';

  String get _userTimezone {
    try {
      final offset = DateTime.now().timeZoneOffset;
      final totalMinutes = offset.inMinutes;
      final sign = totalMinutes >= 0 ? '+' : '-';
      final absMinutes = totalMinutes.abs();
      final hours = absMinutes ~/ 60;
      final minutes = absMinutes % 60;
      return 'UTC$sign${hours.toString().padLeft(2, '0')}:${minutes.toString().padLeft(2, '0')}';
    } catch (_) {
      return '';
    }
  }

  static const String autoDetectPrompt =
      'Analyze this image and auto-detect its type. '
      'If it contains a QR code or barcode, decode its contents. '
      'If it contains text in another language, translate it. '
      'If it appears to be a medical image, analyze for diseases or anomalies. '
      'If it contains encoded or hidden data, decode it. '
      'If it is a document or screenshot, extract and summarize the content. '
      'Otherwise, provide a detailed analysis of what you see.';

  Future<void> sendMessage(
    String text, {
    List<MessageAttachment>? attachments,
  }) async {
    final attach = attachments ?? _pendingAttachments;
    if (text.trim().isEmpty && attach.isEmpty) return;

    if (_currentConversation == null) {
      _newConversation();
    }

    _isLoading = true;
    _isTakingLong = false;
    notifyListeners();

    final userMsg = ChatMessage(
      role: 'user',
      content: text,
      attachments: List.from(attach),
    );
    _currentConversation!.messages.add(userMsg);
    _currentConversation!.updatedAt = DateTime.now();
    if (attachments == null) _pendingAttachments.clear();
    notifyListeners();

    if (!_isServerConnected) {
      debugPrint('[chat] Not connected, attempting re-discovery...');
      await _discoverServer(retries: 1);
      if (!_isServerConnected) {
        _currentConversation!.messages.add(
          ChatMessage(role: 'assistant', content: _serverNotFound),
        );
        _isLoading = false;
        _prefs.saveConversations(_conversations).catchError((_) {});
        notifyListeners();
        return;
      }
    }

    for (var attempt = 0; attempt < 3; attempt++) {
      try {
        final resp = await _callApi(userMsg, text);
        final imageData = resp['image_data'] as String? ?? '';
        final rawContent = _sanitizeAssistantText(
          resp['response'] as String? ?? '',
        );
        final respType = resp['type'] as String? ?? 'chat';
        final isImageGen = _isImageGenRequest(text);
        if (rawContent.isEmpty && imageData.isEmpty) {
          debugPrint('[chat] Server returned empty response (type=$respType)');
          _isLoading = false;
          _prefs.saveConversations(_conversations).catchError((_) {});
          notifyListeners();
          return;
        }
        if (respType == 'error') {
          debugPrint('[chat] Server returned error response: $rawContent');
        }
        _currentConversation!.messages.add(
          ChatMessage(
            role: 'assistant',
            content: rawContent,
            imageData: imageData,
          ),
        );
        _isTakingLong = false;
        _isLoading = false;
        _prefs.saveConversations(_conversations).catchError((_) {});
        notifyListeners();
        return;
      } catch (e) {
        debugPrint('[chat] API call failed (attempt ${attempt + 1}): $e');
        final isAuthError = e is ApiException && (e.statusCode == 401 || e.statusCode == 403);
        if (attempt < 2 && !isAuthError) {
          if (_isTakingLong != true) {
            _isTakingLong = true;
            notifyListeners();
          }
          await _discoverServer(retries: 1);
          if (_isServerConnected) {
            await Future.delayed(Duration(seconds: (attempt + 1) * 2));
          }
          continue;
        }
        _isServerConnected = false;
        unawaited(_discoverServer());
        final errMsg = (e is ApiException) ? e.message : '';
        if (errMsg.isNotEmpty) {
          _currentConversation!.messages.add(
            ChatMessage(role: 'assistant', content: errMsg),
          );
        }
        break;
      }
    }

    _isTakingLong = false;
    _isLoading = false;
    _prefs.saveConversations(_conversations).catchError((_) {});
    notifyListeners();
  }

  Future<void> sendPendingAnalysis() async {
    if (_pendingAttachments.isEmpty) return;
    final attachments = List<MessageAttachment>.from(_pendingAttachments);
    _pendingAttachments.clear();
    notifyListeners();
    await sendMessage(autoDetectPrompt, attachments: attachments);
  }

  bool _isImageGenRequest(String text) {
    final t = text.trim().toLowerCase();
    if (t.length < 4) return false;
    final prefixes = ['draw ', 'paint ', 'sketch ', 'generate ', 'create '];
    for (final p in prefixes) {
      if (t.startsWith(p)) return true;
    }
    final patterns = [
      'generate an image',
      'generate a picture',
      'generate a photo',
      'create an image',
      'create a picture',
      'create a photo',
      'make an image',
      'make a picture',
      'make a photo',
      'generate image of',
      'generate picture of',
      'create image of',
      'create picture of',
      'image of a',
      'image of an',
      'picture of a',
      'picture of an',
      'draw me a',
      'draw me an',
      'paint me a',
    ];
    for (final pat in patterns) {
      if (t.contains(pat)) return true;
    }
    return false;
  }

  Future<Map<String, dynamic>> _callApi(
    ChatMessage userMsg,
    String text,
  ) async {
    final hasImage = userMsg.attachments.any(
      (a) => a.type == AttachmentType.image,
    );
    final sessionId = _currentConversation?.id;

    if (hasImage) {
      final imgAttach = userMsg.attachments.firstWhere(
        (a) => a.type == AttachmentType.image,
      );
      final bytes = await FileService.readAttachmentBytes(imgAttach);
      final resp = await _api.chatWithImage(
        message: text,
        imageBytes: bytes,
        fileName: imgAttach.name,
        sessionId: sessionId,
      );
      return {'response': resp.content, 'image_data': '', 'type': resp.type};
    } else if (userMsg.attachments.isNotEmpty) {
      final attach = userMsg.attachments.first;
      final bytes = await FileService.readAttachmentBytes(attach);
      final resp = await _api.uploadFile(
        fileBytes: bytes,
        fileName: attach.name,
        message: text,
        sessionId: sessionId,
      );
      return {'response': resp.content, 'image_data': '', 'type': resp.type};
    }
    if (_isImageGenRequest(text)) {
      final imgResp = await _api.generateImage(prompt: text, sessionId: sessionId);
      return {
        'response': (imgResp['response'] as String?) ?? (imgResp['content'] as String?) ?? '',
        'image_data': (imgResp['image_data'] as String?) ?? (imgResp['imageBase64'] as String?) ?? '',
        'type': (imgResp['type'] as String?) ?? 'image_gen',
      };
    }
    final timezone = _cachedTimezoneName.isNotEmpty
        ? _cachedTimezoneName
        : _userTimezone;
    final location = _cachedLocation.isNotEmpty ? _cachedLocation : null;
    final resp = await _api.chat(
      message: text,
      sessionId: sessionId,
      timezone: timezone.isNotEmpty ? timezone : null,
      location: location,
    );
    return {'response': resp.content, 'image_data': '', 'type': resp.type};
  }

  Future<void> pickImageForAnalysis(BuildContext context) async {
    try {
      final attachment = await _fileService.pickImageFromGallery();
      if (attachment != null) {
        _pendingAttachments.add(attachment);
        notifyListeners();
      }
    } catch (e) {
      debugPrint('Image analysis error: $e');
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('${AppStrings.analysisError}: $e'),
            behavior: SnackBarBehavior.floating,
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(10),
            ),
          ),
        );
      }
    }
  }

  Future<void> analyzeWithCamera(BuildContext context) async {
    try {
      final result = await Navigator.push<(String?, CameraResult)>(
        context,
        MaterialPageRoute(builder: (_) => const CameraScreen()),
      );
      if (result == null) return;
      final (imagePath, cameraResult) = result;
      if (imagePath == null) {
        if (cameraResult == CameraResult.error && context.mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: const Text('Failed to capture image'),
              behavior: SnackBarBehavior.floating,
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(10),
              ),
            ),
          );
        }
        return;
      }
      final attachment = MessageAttachment(
        name: 'camera_${DateTime.now().millisecondsSinceEpoch}.jpg',
        path: imagePath,
        type: AttachmentType.image,
      );
      _pendingAttachments.add(attachment);
      notifyListeners();
    } catch (e) {
      debugPrint('Camera plugin unavailable, trying ImagePicker: $e');
      try {
        final image = await _fileService.pickImageFromCamera();
        if (image == null) return;
        _pendingAttachments.add(image);
        notifyListeners();
      } catch (e2) {
        debugPrint('Fallback camera also failed: $e2');
        if (context.mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text('Camera error: $e'),
              behavior: SnackBarBehavior.floating,
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(10),
              ),
            ),
          );
        }
      }
    }
  }

  Future<void> captureAndAnalyze(BuildContext context) async {
    final source = await showModalBottomSheet<ImageSource>(
      context: context,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(AppDimens.sheetRadius),
      ),
      builder: (ctx) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: AppDimens.paddingLG),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Padding(
                padding: const EdgeInsets.only(bottom: AppDimens.paddingMD),
                child: Text(
                  AppStrings.analyzeImage,
                  style: const TextStyle(
                    fontSize: AppDimens.fontSizeTitle,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
              ListTile(
                leading: const Icon(Icons.camera_alt_rounded),
                title: Text(AppStrings.takePhoto),
                subtitle: Text(AppStrings.captureWithCamera),
                onTap: () => Navigator.pop(ctx, ImageSource.camera),
              ),
              ListTile(
                leading: const Icon(Icons.photo_library_rounded),
                title: Text(AppStrings.chooseFromGallery),
                subtitle: Text(AppStrings.selectFromGallery),
                onTap: () => Navigator.pop(ctx, ImageSource.gallery),
              ),
            ],
          ),
        ),
      ),
    );

    if (source == null || !context.mounted) return;

    try {
      MessageAttachment? attachment;
      if (source == ImageSource.camera) {
        try {
          final result = await Navigator.push<(String?, CameraResult)>(
            context,
            MaterialPageRoute(builder: (_) => const CameraScreen()),
          );
          final imagePath = result?.$1;
          if (imagePath != null) {
            attachment = MessageAttachment(
              name: 'camera_${DateTime.now().millisecondsSinceEpoch}.jpg',
              path: imagePath,
              type: AttachmentType.image,
            );
          }
        } catch (_) {
          attachment = await _fileService.pickImageFromCamera();
        }
      } else {
        attachment = await _fileService.pickImageFromGallery();
      }
      if (attachment != null) {
        _pendingAttachments.add(attachment);
        notifyListeners();
      }
    } catch (e) {
      debugPrint('${AppStrings.analysisError}: $e');
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('${AppStrings.analysisError}: $e'),
            behavior: SnackBarBehavior.floating,
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(10),
            ),
          ),
        );
      }
    }
  }

  Future<void> startVoiceInput() async {
    try {
      final available = await _speech.initialize(
        onError: (_) {
          _isListening = false;
          notifyListeners();
        },
        onStatus: (status) {
          if (status == 'notListening' && _isListening) {
            _isListening = false;
            if (_voiceText.isNotEmpty && _autoSendVoice) {
              final text = _voiceText;
              _voiceText = '';
              sendMessage(text);
            }
            if (_continuousVoiceEnabled) {
              Future.delayed(const Duration(milliseconds: 500), startVoiceInput);
            }
            notifyListeners();
          }
        },
      );
      if (!available) return;

      _isListening = true;
      _voiceText = '';
      notifyListeners();

      await _speech.startListening(
        onResult: (result) {
          _voiceText = result.recognizedWords ?? '';
          notifyListeners();
        },
      );
    } catch (e) {
      debugPrint('Voice input error: $e');
      if (_continuousVoiceEnabled) {
        Future.delayed(const Duration(milliseconds: 500), startVoiceInput);
      } else {
        _isListening = false;
        notifyListeners();
      }
    }
  }

  void stopVoiceInput() {
    _isListening = false;
    _speech.stopListening();
    notifyListeners();
  }

  void clearVoiceText() {
    _voiceText = '';
    notifyListeners();
  }

  Future<void> pickImage(ImageSource source) async {
    try {
      final attachment = source == ImageSource.camera
          ? await _fileService.pickImageFromCamera()
          : await _fileService.pickImageFromGallery();
      if (attachment != null) {
        _pendingAttachments.add(attachment);
        notifyListeners();
      }
    } catch (e) {
      debugPrint('Image picker error: $e');
    }
  }

  Future<void> pickFile() async {
    try {
      final attachment = await _fileService.pickFile();
      if (attachment != null) {
        _pendingAttachments.add(attachment);
        notifyListeners();
      }
    } catch (e) {
      debugPrint('File picker error: $e');
    }
  }

  void removePendingAttachment(int index) {
    if (index >= 0 && index < _pendingAttachments.length) {
      _pendingAttachments.removeAt(index);
      notifyListeners();
    }
  }

  Future<void> _initTts() async {
    try {
      await _tts.initialize(
        onComplete: () {
          _isSpeaking = false;
          _speakingMessageId = null;
          notifyListeners();
        },
        onError: (_) {
          _isSpeaking = false;
          _speakingMessageId = null;
          notifyListeners();
        },
      );
    } catch (e) {
      debugPrint('TTS init error: $e');
    }
  }

  Future<void> speakMessage(String messageId, String text) async {
    try {
      if (_isSpeaking && _speakingMessageId == messageId) {
        await _tts.stop();
        _isSpeaking = false;
        _speakingMessageId = null;
        notifyListeners();
        return;
      }
      if (_isSpeaking) {
        await _tts.stop();
      }
      await _tts.setSpeed(_ttsSpeed);
      await _tts.setPitch(_ttsPitch);
      _isSpeaking = true;
      _speakingMessageId = messageId;
      notifyListeners();
      await _tts.speak(text);
    } catch (e) {
      _isSpeaking = false;
      _speakingMessageId = null;
      notifyListeners();
    }
  }

  void stopSpeaking() async {
    await _tts.stop();
    _isSpeaking = false;
    _speakingMessageId = null;
    notifyListeners();
  }

  void updateTtsSpeed(double speed) {
    _ttsSpeed = speed;
    _tts.setSpeed(speed);
    _prefs.saveTtsSpeed(speed);
    notifyListeners();
  }

  void updateTtsPitch(double pitch) {
    _ttsPitch = pitch;
    _tts.setPitch(pitch);
    _prefs.saveTtsPitch(pitch);
    notifyListeners();
  }

  void setContinuousVoiceEnabled(bool v) {
    _continuousVoiceEnabled = v;
    _prefs.saveContinuousVoiceEnabled(v);
    if (v) {
      startVoiceInput();
    } else {
      stopVoiceInput();
    }
    notifyListeners();
  }

  void setAutoSendVoice(bool v) {
    _autoSendVoice = v;
    _prefs.saveAutoSendVoice(v);
    notifyListeners();
  }

  ApiClient get apiClient => _api;
  List<ChatMessage> get currentMessages => _currentConversation?.messages ?? [];
  String? get currentConversationId => _currentConversation?.id;

  void setError(String? error) {
    _error = error;
    notifyListeners();
  }

  String? _error;
  String? get error => _error;

  void handleSendMessage(String query) => sendMessage(query);

  void loadTheme() {
    notifyListeners();
  }

  void loadServerConversations() {}

  OverlayService? _overlayService;
  OverlayService? get overlayService => _overlayService;
  void attachOverlayService(OverlayService service) {
    _overlayService = service;
  }

  bool _continuousVoiceSearchEnabled = false;
  bool get continuousVoiceSearchEnabled => _continuousVoiceSearchEnabled;

  void setContinuousVoiceSearchEnabled(bool v) {
    _continuousVoiceSearchEnabled = v;
    _prefs.saveContinuousVoiceSearch(v);
    notifyListeners();
  }

  bool _systemOverlayEnabled = false;
  bool get systemOverlayEnabled => _systemOverlayEnabled;

  void setSystemOverlayEnabled(bool v) {
    _systemOverlayEnabled = v;
    _prefs.saveSystemOverlay(v);
    _overlayService?.setWantsOverlay(v);
    notifyListeners();
  }

  void executeIntent(String action) {
    if (action.isNotEmpty) {
      sendMessage(action);
    }
  }

  Future<void> _loadPrefs() async {
    try {
      _themeMode = await _prefs.loadThemeMode();
      _ttsSpeed = await _prefs.loadTtsSpeed();
      _ttsPitch = await _prefs.loadTtsPitch();
      _continuousVoiceEnabled = await _prefs.loadContinuousVoice();
      _autoSendVoice = await _prefs.loadAutoSendVoice();
      _backgroundAssistantEnabled = await _prefs.loadBackgroundAssistant();
      _systemOverlayEnabled = await _prefs.loadSystemOverlay();
      if (_systemOverlayEnabled) {
        WidgetsBinding.instance.addPostFrameCallback((_) {
          _overlayService?.setWantsOverlay(true);
        });
      }
      final loaded = await _prefs.loadConversations();
      _conversations.addAll(loaded);
      if (_conversations.isNotEmpty) {
        _currentConversation = _conversations.first;
      }
      notifyListeners();
    } catch (_) {}
  }
}
