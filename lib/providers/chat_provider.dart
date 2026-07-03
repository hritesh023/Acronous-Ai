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

  static final RegExp _privateInfoPattern = RegExp(
    r'\b(api[ _]?key[\s:=]+|system prompt[\s:=]+|internal (configuration|instructions|prompt)[\s:=]+|openrouter|pollinations|cloudflare)[\s:=]',
    caseSensitive: false,
  );

  static String _sanitizeAssistantText(String text) {
    if (text.trim().isEmpty) return '';
    final cleaned = text
        .replaceAll(RegExp(r'\[Internal[^\]]*\]'), '')
        .replaceAll(RegExp(r'\n{3,}'), '\n\n')
        .trim();
    if (cleaned.isEmpty) return text.trim();
    if (_privateInfoPattern.hasMatch(cleaned)) return '';
    return cleaned;
  }

  final List<Conversation> _conversations = [];
  Conversation? _currentConversation;
  bool _isLoading = false;
  bool _isTakingLong = false;
  bool _cancelled = false;
  final List<Map<String, dynamic>> _messageQueue = [];
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
    if (_conversations.isEmpty) {
      _newConversation();
    } else {
      _currentConversation = _conversations.first;
    }
    _fetchLocationInfo();
  }

  Future<void> _discoverServer({int retries = 2, String? savedUrl}) async {
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
          await _prefs.saveServerUrl(bestUrl);
          await _api.wakeup(timeout: const Duration(seconds: 15));
          final ready = await _api.waitForReady(
            timeout: bestUrl.startsWith('https://')
                ? const Duration(seconds: 10)
                : const Duration(seconds: 10),
          );
          if (!ready) {
            final healthy = await _api.healthCheck();
            if (healthy['status'] == 'ok') {
              _isServerConnected = true;
              _startKeepAlive();
              _isConnecting = false;
              _serverCheckDone = true;
              notifyListeners();
              return;
            }
            _startKeepAlive();
            _isConnecting = false;
            _serverCheckDone = true;
            notifyListeners();
            return;
          }
          _isServerConnected = true;
          _startKeepAlive();
          _isConnecting = false;
          _serverCheckDone = true;
          notifyListeners();
          return;
        }
      } catch (_) {}

      if (attempt < retries) {
        await Future.delayed(Duration(seconds: 3));
      }
    }
    _isServerConnected = false;
    _isConnecting = false;
    _serverCheckDone = true;
    notifyListeners();
  }

  void _startKeepAlive() {
    Future.delayed(const Duration(seconds: 10), () async {
      try {
        await _api.wakeup(timeout: const Duration(seconds: 10));
        final healthy = await _api.healthCheck();
        _isServerConnected = healthy['status'] == 'ok';
      } catch (_) {
        _isServerConnected = false;
      }
      if (!_disposed) _startKeepAlive();
    });
  }

  bool _disposed = false;

  @override
  void dispose() {
    _disposed = true;
    super.dispose();
  }

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
    _cancelled = true;
    _isLoading = false;
    _isTakingLong = false;
    _api.cancelCurrentRequest();
    notifyListeners();
  }

  String _cachedLocation = '';

  Future<void> _fetchLocationInfo() async {
    final geoServices = [_fetchFromIpApi, _fetchFromFreeIp];
    for (final service in geoServices) {
      try {
        final success = await service();
        if (success) break;
      } catch (_) {}
    }
    if (_cachedTimezoneName.isEmpty) {
      _cachedTimezoneName = _deviceTimezone;
    }
  }

  Future<bool> _fetchFromIpApi() async {
    try {
      final resp = await http
          .get(Uri.parse('https://ip-api.com/json/'))
          .timeout(const Duration(seconds: 8));
      if (resp.statusCode != 200) return false;
      final data = jsonDecode(resp.body) as Map<String, dynamic>;
      if (data['status'] != 'success') return false;
      _updateLocationData(
        city: data['city'] as String? ?? '',
        country: data['country'] as String? ?? '',
        timezone: data['timezone'] as String? ?? '',
      );
      return true;
    } catch (_) {
      return false;
    }
  }

  Future<bool> _fetchFromFreeIp() async {
    try {
      final resp = await http
          .get(Uri.parse('https://freeipapi.com/api/json'))
          .timeout(const Duration(seconds: 8));
      if (resp.statusCode != 200) return false;
      final data = jsonDecode(resp.body) as Map<String, dynamic>;
      if (data['status'] != 'success') return false;
      _updateLocationData(
        city: data['cityName'] as String? ?? data['city'] as String? ?? '',
        country:
            data['countryName'] as String? ?? data['country'] as String? ?? '',
        timezone:
            data['timeZone'] as String? ?? data['timezone'] as String? ?? '',
      );
      return true;
    } catch (_) {
      return false;
    }
  }

  void _updateLocationData({
    required String city,
    required String country,
    required String timezone,
  }) {
    if (city.isNotEmpty && country.isNotEmpty) {
      _cachedLocation = '$city, $country';
    } else if (city.isNotEmpty) {
      _cachedLocation = city;
    } else if (country.isNotEmpty) {
      _cachedLocation = country;
    }
    if (timezone.isNotEmpty) {
      _cachedTimezoneName = timezone;
    }
  }

  String _cachedTimezoneName = '';

  String get _deviceTimezone {
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

  Future<void> sendMessage(
    String text, {
    List<MessageAttachment>? attachments,
  }) async {
    final attach = attachments ?? _pendingAttachments;
    if (text.trim().isEmpty && attach.isEmpty) return;

    if (_currentConversation == null) {
      _newConversation();
    }

    if (_isLoading) {
      _messageQueue.add({'text': text, 'attachments': attach});
      final userMsg = ChatMessage(
        role: 'user',
        content: text,
        attachments: List.from(attach),
      );
      _currentConversation!.messages.add(userMsg);
      _currentConversation!.updatedAt = DateTime.now();
      if (attachments == null) _pendingAttachments.clear();
      notifyListeners();
      return;
    }

    _cancelled = false;
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

    for (var attempt = 0; attempt < 3; attempt++) {
      if (!_isServerConnected && attempt > 0) {
        await _discoverServer(retries: 1);
      }
      try {
        final resp = await _callApi(userMsg, text);
        final imageData = resp['image_data'] as String? ?? '';
        final fileData = resp['file_data'] as String? ?? '';
        final fileName = resp['file_name'] as String? ?? '';
        final fileType = resp['file_type'] as String? ?? '';
        final rawContent = _sanitizeAssistantText(
          resp['response'] as String? ?? '',
        );
        final respType = resp['type'] as String? ?? 'chat';
        if (respType == 'error') {
          _isTakingLong = false;
          _isLoading = false;
          _prefs.saveConversations(_conversations).catchError((_) {});
          notifyListeners();
          _processQueue();
          return;
        }
        if (rawContent.isEmpty && imageData.isEmpty && fileData.isEmpty) {
          if (attempt < 2) {
            await Future.delayed(const Duration(seconds: 2));
            continue;
          }
          _isTakingLong = false;
          _isLoading = false;
          _prefs.saveConversations(_conversations).catchError((_) {});
          notifyListeners();
          _processQueue();
          return;
        }
        if (rawContent.isNotEmpty ||
            imageData.isNotEmpty ||
            fileData.isNotEmpty) {
          _currentConversation!.messages.add(
            ChatMessage(
              role: 'assistant',
              content: rawContent,
              imageData: imageData,
              fileData: fileData,
              fileName: fileName,
              fileType: fileType,
            ),
          );
        }
        _isTakingLong = false;
        _isLoading = false;
        _prefs.saveConversations(_conversations).catchError((_) {});
        notifyListeners();
        _processQueue();
        return;
      } catch (e) {
        if (_cancelled) break;
        if (attempt < 2) {
          _isTakingLong = true;
          notifyListeners();
          if (_cancelled) break;
          await _discoverServer(retries: 1);
          if (_cancelled) break;
          if (_isServerConnected) {
            await Future.delayed(const Duration(seconds: 5));
          }
          if (_cancelled) break;
          continue;
        }
        _isServerConnected = false;
        unawaited(_discoverServer());
        break;
      }
    }

    _isTakingLong = false;
    _isLoading = false;
    _prefs.saveConversations(_conversations).catchError((_) {});
    notifyListeners();
    _processQueue();
  }

  void _processQueue() {
    if (_messageQueue.isEmpty) return;
    final next = _messageQueue.removeAt(0);
    sendMessage(
      next['text'] as String,
      attachments: next['attachments'] as List<MessageAttachment>?,
    );
  }

  void _addAssistantMessage(String content) {
    _currentConversation!.messages.add(
      ChatMessage(role: 'assistant', content: content),
    );
  }

  Future<void> sendPendingAnalysis() async {
    if (_pendingAttachments.isEmpty) return;
    final attachments = List<MessageAttachment>.from(_pendingAttachments);
    _pendingAttachments.clear();
    notifyListeners();
    await sendMessage('', attachments: attachments);
  }

  bool _isImageGenRequest(String text) {
    final t = text.trim().toLowerCase();
    if (t.length < 4) return false;

    // Direct action prefixes (strong signal)
    final prefixes = ['draw ', 'paint ', 'sketch ', 'render ', 'imagine '];
    for (final p in prefixes) {
      if (t.startsWith(p)) return true;
    }

    // Core image generation patterns
    final patterns = [
      'generate an image', 'generate a picture', 'generate a photo',
      'create an image', 'create a picture', 'create a photo',
      'make an image', 'make a picture', 'make a photo',
      'generate image of', 'generate picture of',
      'create image of', 'create picture of',
      'image of a', 'image of an', 'image of the',
      'picture of a', 'picture of an', 'picture of the',
      'photo of a', 'photo of an', 'photo of the',
      'draw me a', 'draw me an', 'draw me',
      'paint me a', 'paint me an', 'paint me',
      'make me a', 'make me an',
      'create me a', 'create me an',
      'generate me a', 'generate me an',
      'show me a picture', 'show me an image',
      // Image format with visual context
      'png of a', 'png of an', 'png of the',
      'jpg of a', 'jpeg of a', 'jpg of an', 'jpeg of an',
      'gif of a', 'gif of an',
      'webp of a', 'bmp of a',
      'generate a', 'generate an',
      'generate png', 'generate jpg', 'generate jpeg', 'generate gif',
      'create png', 'create jpg', 'create jpeg', 'create gif',
      'make png', 'make jpg', 'make jpeg', 'make gif',
    ];
    for (final pat in patterns) {
      if (t.contains(pat)) return true;
    }

    // Image file extensions with visual context
    final imageExts = ['png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp'];
    if (imageExts.any((ext) => t.contains(ext))) {
      final visualWords = [
        'image',
        'picture',
        'photo',
        'draw',
        'paint',
        'sketch',
        'illustration',
        'artwork',
        'design',
        'graphic',
        'of a',
        'of an',
        'of the',
        'sunset',
        'landscape',
        'portrait',
        'cartoon',
        'art',
        'render',
        'visualize',
        'logo',
        'icon',
        'banner',
        'wallpaper',
        'background',
        'poster',
        'meme',
        'comic',
        'character',
        'scene',
        'view',
      ];
      if (visualWords.any((w) => t.contains(w))) return true;
    }

    // Starting with visual noun phrases
    if (t.startsWith('a picture') ||
        t.startsWith('a photo') ||
        t.startsWith('an image') ||
        t.startsWith('a drawing') ||
        t.startsWith('a painting') ||
        t.startsWith('a sketch') ||
        t.startsWith('a cartoon') ||
        t.startsWith('a logo') ||
        t.startsWith('a poster') ||
        t.startsWith('a banner')) {
      return true;
    }

    // Design patterns
    final designPatterns = [
      'design a',
      'design an',
      'design me',
      'create a logo',
      'create a banner',
      'create a poster',
      'make a logo',
      'make a banner',
      'make a poster',
      'generate a logo',
      'generate a banner',
      'generate a poster',
      'create a wallpaper',
      'make a wallpaper',
      'create a character',
      'design a character',
      'create a meme',
      'make a meme',
    ];
    for (final pat in designPatterns) {
      if (t.contains(pat)) return true;
    }

    // ── Extended natural-language patterns ─────────────────────────────

    // "I want/need" + visual noun (with and without "of")
    final wantNeedPatterns = [
      'i want a picture', 'i want a photo', 'i want an image',
      'i want a drawing', 'i want a painting', 'i want a sketch',
      'i need a picture', 'i need a photo', 'i need an image',
      'i need a drawing', 'i need a painting', 'i need a sketch',
      'want a picture', 'want a photo', 'want an image',
      'need a picture', 'need a photo', 'need an image',
      // Grammatical variants with "a" instead of "an"
      'i want a image', 'i need a image',
      'want a image', 'need a image',
    ];
    for (final pat in wantNeedPatterns) {
      if (t.contains(pat)) return true;
    }

    // "Can you" patterns
    final canYouPatterns = [
      'can you draw',
      'can you paint',
      'can you sketch',
      'can you render',
      'can you create',
      'can you generate',
      'can you make',
      'can you design',
      'can you imagine',
      'can you show me',
      'can you make me',
    ];
    for (final pat in canYouPatterns) {
      if (t.contains(pat)) return true;
    }

    // "Please" patterns
    final pleasePatterns = [
      'please draw',
      'please paint',
      'please sketch',
      'please create',
      'please generate',
      'please make',
    ];
    for (final pat in pleasePatterns) {
      if (t.contains(pat)) return true;
    }

    // Broad visual noun + "of" anywhere
    final visualOfPatterns = [
      'photo of',
      'picture of',
      'image of',
      'drawing of',
      'painting of',
      'sketch of',
    ];
    for (final pat in visualOfPatterns) {
      if (t.contains(pat)) return true;
    }

    // Action + article patterns (covers "draw a cat", "create a landscape", etc.)
    // Includes grammatical variants with "a" instead of "an" before vowels
    final actionArticle = [
      'draw a',
      'draw an',
      'paint a',
      'paint an',
      'sketch a',
      'sketch an',
      'render a',
      'render an',
      'create a picture',
      'create a photo',
      'create an image',
      'create a image',
      'create a drawing',
      'create a painting',
      'make a picture',
      'make a photo',
      'make an image',
      'make a image',
      'make a drawing',
      'make a painting',
      'generate a picture',
      'generate a photo',
      'generate an image',
      'generate a image',
    ];
    for (final pat in actionArticle) {
      if (t.contains(pat)) return true;
    }

    // ── Broad combined-intent safety net ───────────────────────────────
    // If text has both a creation verb and a visual noun, it's image gen
    final creationVerbs = [
      'draw',
      'paint',
      'sketch',
      'render',
      'imagine',
      'generate',
      'create',
      'make',
    ];
    final visualNouns = [
      'image',
      'picture',
      'photo',
      'drawing',
      'painting',
      'sketch',
      'illustration',
      'artwork',
      'art',
      'logo',
      'banner',
      'poster',
      'wallpaper',
      'meme',
      'icon',
      'portrait',
      'landscape',
      'scene',
      'sunset',
      'cartoon',
      'character',
      'graphic',
    ];
    bool hasVerb = false;
    for (final v in creationVerbs) {
      if (RegExp(r'\b' + v + r'\b').hasMatch(t)) {
        hasVerb = true;
        break;
      }
    }
    if (hasVerb) {
      for (final n in visualNouns) {
        if (t.contains(n)) return true;
      }
    }

    return false;
  }

  String? _detectFileGenFormat(String text) {
    final t = text.trim().toLowerCase();

    // ── Code-related queries should NEVER trigger file generation ──
    // If the user is asking for code, show it inline — never as a PDF/doc
    final codeKeywords = [
      'python',
      'javascript',
      'typescript',
      'java',
      'c++',
      'c#',
      'ruby',
      'php',
      'go',
      'rust',
      'swift',
      'kotlin',
      'dart',
      'scala',
      'perl',
      'shell script',
      'bash script',
      'batch script',
      'powershell',
      'code',
      'script',
      'function',
      'class',
      'method',
      'api',
    ];
    final codeMatches = codeKeywords.where((kw) => t.contains(kw)).length;
    final codeActions = [
      'write',
      'create a script',
      'build a',
      'code a',
      'program',
    ];
    final hasCodeAction = codeActions.any((a) => t.contains(a));
    if (codeMatches >= 1 && hasCodeAction) return null;
    // Also catch "write a [language] script" patterns
    if (RegExp(r'write\s+a\s+\w+\s+script').hasMatch(t)) return null;

    // Check for explicit format keyword in the text FIRST
    // Must have a specific format keyword + action to trigger file generation
    final formatKeywords = {
      'pdf': ['pdf', 'document'],
      'docx': ['word', 'docx', '.doc', 'microsoft word'],
      'xlsx': ['excel', 'xlsx', 'xls', 'spreadsheet', 'tabular', 'table'],
      'csv': ['csv', 'comma separated', 'comma-separated'],
      'html': ['html', 'web page', 'website'],
      'md': ['markdown', '.md', 'md file'],
      'svg': ['svg', 'vector'],
      'json': ['json', 'json file'],
      'xml': ['xml', 'xml file'],
      'txt': ['text file', 'txt file'],
    };

    // Image formats should route to image generation
    final imageFormats = ['jpg', 'jpeg', 'gif', 'bmp', 'webp'];
    if (imageFormats.any((f) => t.contains(f))) return null;

    // PNG with visual context -> image gen
    if (t.contains('png')) {
      final visualIndicators = [
        'image',
        'picture',
        'photo',
        'draw',
        'paint',
        'sketch',
        'of a',
        'of an',
        'of the',
        'illustration',
        'artwork',
        'design',
        'graphic',
        'render',
        'visualize',
        'logo',
        'icon',
        'banner',
        'wallpaper',
        'background',
        'sunset',
        'landscape',
        'portrait',
        'cartoon',
        'art',
      ];
      final isVisualRequest = visualIndicators.any((w) => t.contains(w));
      final isShortRequest = t.split(RegExp(r'\s+')).length <= 6;
      if (isVisualRequest || isShortRequest) return null;
      return 'png';
    }

    // Check for explicit format keyword
    String? matchedFormat;
    for (final entry in formatKeywords.entries) {
      if (entry.value.any((kw) => t.contains(kw))) {
        matchedFormat = entry.key;
        break;
      }
    }

    if (matchedFormat == null) return null;

    // If we found a format keyword, also check for creation action
    // This prevents false positives like "explain report" -> docx
    final actionWords = [
      'create',
      'make',
      'generate',
      'build',
      'write',
      'convert',
      'export',
      'save',
      'download',
      'produce',
      'prepare',
      'compile',
      'draft',
      'compose',
      'develop',
      'construct',
      'produce a',
      'make a',
      'create a',
      'generate a',
      'write a',
      'i need',
      'i want',
      'can you create',
      'can you make',
      'can you generate',
      'can you write',
      'please create',
      'please make',
    ];
    final hasAction = actionWords.any((w) => t.contains(w));

    // Also check if text starts with the format (e.g., "pdf of sales report")
    final startsWithFormat = RegExp(
      r'^(a|an|the)?\s*(pdf|docx?|xlsx?|csv|txt|md|html|json|xml)\b',
    ).hasMatch(t);

    if (!hasAction && !startsWithFormat) return null;

    // Slides/presentations -> pdf
    if (t.contains('presentation') ||
        t.contains('slide') ||
        t.contains('powerpoint') ||
        t.contains('pptx') ||
        t.contains('slides')) {
      if (t.contains('resume') ||
          t.contains('cv') ||
          t.contains('cover letter') ||
          t.contains('report') ||
          t.contains('invoice') ||
          t.contains('receipt')) {
        return 'docx';
      }
      return 'pdf';
    }

    return matchedFormat;
  }

  String _stripMarkdownFences(String text) {
    final trimmed = text.trim();
    // Remove leading AI explanations like "Here is your PDF:", "Sure, here's the content:", etc.
    String cleaned = trimmed
        .replaceFirst(
          RegExp(
            r"^(here\s+is|here'?s|i'?ve?\s+(created|generated|made|prepared|produced)|below\s+is|the\s+following\s+is|sure[!.,]+\s*here'?s?|certainly[!.,]+\s*here'?s?|of\s+course[!.,]+\s*here'?s?)[^]*?(?=```|<\w|[A-Z]|\d)",
            caseSensitive: false,
          ),
          '',
        )
        .trim();

    if (cleaned.startsWith('```') && cleaned.endsWith('```')) {
      final firstNewline = cleaned.indexOf('\n');
      if (firstNewline > 3 && firstNewline < cleaned.length - 4) {
        cleaned = cleaned
            .substring(firstNewline + 1, cleaned.length - 3)
            .trim();
      } else {
        cleaned = cleaned.substring(3, cleaned.length - 3).trim();
      }
    } else if (cleaned.startsWith('```')) {
      final firstNewline = cleaned.indexOf('\n');
      if (firstNewline > 3) {
        cleaned = cleaned.substring(firstNewline + 1).trim();
      } else {
        cleaned = cleaned.substring(3).trim();
      }
    }
    if (cleaned.endsWith('```')) {
      cleaned = cleaned.substring(0, cleaned.length - 3).trim();
    }
    // Remove trailing AI wrap-up
    cleaned = cleaned
        .replaceFirst(
          RegExp(
            r'(i\s+hope|feel\s+free|let\s+me\s+know|if\s+you\s+need|please\s+let|do\s+not\s+hesitate).*$',
            caseSensitive: false,
            dotAll: true,
          ),
          '',
        )
        .trim();
    return cleaned;
  }

  List<Map<String, String>> _buildMessageHistory() {
    if (_currentConversation == null) return [];
    final msgs = _currentConversation!.messages;
    if (msgs.length <= 1) return [];
    final history = <Map<String, String>>[];
    for (var i = 0; i < msgs.length - 1; i++) {
      final m = msgs[i];
      if (m.role == 'user' || m.role == 'assistant') {
        history.add({'role': m.role, 'content': m.content});
      }
    }
    return history;
  }

  Future<Map<String, dynamic>> _callApi(
    ChatMessage userMsg,
    String text,
  ) async {
    final hasImage = userMsg.attachments.any(
      (a) => a.type == AttachmentType.image,
    );
    final sessionId = _currentConversation?.id;

    final timezone = _cachedTimezoneName.isNotEmpty
        ? _cachedTimezoneName
        : _deviceTimezone;
    final location = _cachedLocation.isNotEmpty ? _cachedLocation : null;

    if (hasImage) {
      final imgAttach = userMsg.attachments.firstWhere(
        (a) => a.type == AttachmentType.image,
      );
      final bytes = await FileService.readAttachmentBytes(imgAttach);
      final t = text.toLowerCase();
      final wordCount = text.trim().split(RegExp(r'\s+')).length;

      // Check if the message contains image-related context words
      final visualContext = [
        'image',
        'photo',
        'picture',
        'art',
        'design',
        'graphic',
        'background',
        'color',
        'style',
        'filter',
        'texture',
        'subject',
        'object',
        'scene',
        'view',
        'look',
        'cartoon',
        'painting',
        'sketch',
        'drawing',
        'anime',
        'render',
        'logo',
        'icon',
        'banner',
        'wallpaper',
        'dress',
        'clothes',
        'suit',
        'shirt',
        'outfit',
        'wear',
        'face',
        'hair',
        'eyes',
        'skin',
        'background',
        'add',
        'remove',
        'replace',
        'change',
      ];
      final hasVisualContext = visualContext.any((w) => t.contains(w));

      // Strong edit keywords
      final strongEditKeywords = [
        'edit this',
        'edit the',
        'edit my',
        'edit image',
        'edit photo',
        'edit picture',
        'modify this',
        'modify the',
        'modify my',
        'redesign this',
        'redesign the',
        'turn this into',
        'turn it into',
        'enhance this',
        'enhance the',
        'enhance my',
        'enhance image',
        'improve this',
        'improve the',
        'improve my',
        'improve image',
        'make it better',
        'make this better',
        'turn into cartoon',
        'turn into painting',
        'turn into sketch',
        'as a cartoon',
        'as a painting',
        'as a sketch',
        'as an anime',
        'like a cartoon',
        'like a painting',
        'convert to cartoon',
        'convert to painting',
        'change the dress',
        'change the clothes',
        'change the outfit',
        'change the color',
        'change the style',
        'change the background',
        'change the shirt',
        'change the hair',
        'change the eyes',
        'change just',
        'only change',
        'keep the same',
        'keep everything',
        'same face',
        'same person',
      ];
      final mediumEditKeywords = [
        'make it ',
        'make this ',
        'make the ',
        'turn it ',
        'turn this ',
        'turn the ',
        'turn into ',
        'change the',
        'change this',
        'change my',
        'change to',
        'change color',
        'change style',
        'convert this ',
        'convert it ',
        'transform this ',
        'add a ',
        'add some ',
        'add more ',
        'remove the ',
        'remove this ',
        'replace the ',
        'replace this ',
        'convert to ',
        'convert into',
        'put a ',
        'put on ',
      ];
      final weakEditKeywords = [
        'add ',
        'remove ',
        'replace ',
        'crop',
        'rotate',
        'resize',
        'filter',
        'style as',
        'style it',
      ];

      final isStrongMatch = strongEditKeywords.any((kw) => t.contains(kw));
      final isMediumMatch =
          hasVisualContext &&
          wordCount >= 3 &&
          mediumEditKeywords.any((kw) => t.contains(kw));
      bool isWeakKeywordMatch(String kw) {
        if (kw.endsWith(' ')) {
          return t.contains(kw) && t.indexOf(kw) + kw.length < t.length;
        }
        return t.contains(kw);
      }

      final isWeakMatch =
          hasVisualContext &&
          wordCount >= 5 &&
          weakEditKeywords.any(isWeakKeywordMatch);

      final startsWithEdit = RegExp(
        r'^(edit|modify|redesign|enhance|improve|change|make|turn|convert)\s+(this|the|my|image|photo|picture|it|into)\b',
      ).hasMatch(t);
      // Broader catch-all: any edit-like verb + visual context = edit request
      final editVerbs = [
        'edit',
        'modify',
        'redesign',
        'enhance',
        'improve',
        'change',
        'turn',
        'convert',
        'transform',
        'recolor',
        'recolour',
        'replace',
        'add',
        'remove',
        'crop',
        'rotate',
        'resize',
      ];
      final hasEditVerb = editVerbs.any(
        (v) => RegExp(r'\b' + v + r'\b').hasMatch(t),
      );
      final isEditRequest =
          (isStrongMatch ||
              isMediumMatch ||
              isWeakMatch ||
              startsWithEdit ||
              (hasEditVerb && hasVisualContext && wordCount >= 2)) &&
          wordCount >= 2;
          if (isEditRequest) {
        try {
          final editResp = await _api.editImage(
            imageBytes: bytes,
            fileName: imgAttach.name,
            prompt: text,
            sessionId: sessionId,
          );
          final response = editResp['response'] as String? ?? '';
          final imageData = editResp['image_data'] as String? ?? '';
          final editType = editResp['type'] as String? ?? '';
          if (imageData.isNotEmpty) {
            return {
              'response': response,
              'image_data': imageData,
              'type': editType,
            };
          }
          if (response.isNotEmpty) {
            return {'response': response, 'image_data': '', 'type': 'chat'};
          }
        } catch (_) {
        }
        try {
          final editResp = await _api.redesignImageBytes(
            imageBytes: bytes,
            fileName: imgAttach.name,
            prompt: text,
          );
          final imageData =
              editResp['content'] as String? ??
              editResp['image_data'] as String? ??
              '';
          final response = editResp['response'] as String? ?? '';
          if (imageData.isNotEmpty) {
            return {
              'response': response,
              'image_data': imageData,
              'type': 'chat',
            };
          }
          if (response.isNotEmpty) {
            return {'response': response, 'image_data': '', 'type': 'chat'};
          }
        } catch (_) {
        }
      }
      final history = _buildMessageHistory();
      final resp = await _api.chatWithImage(
        message: text,
        imageBytes: bytes,
        fileName: imgAttach.name,
        sessionId: sessionId,
        timezone: timezone.isNotEmpty ? timezone : null,
        location: location,
        messages: history,
      );
      return {
        'response': resp.content,
        'image_data': resp.imageBase64 ?? '',
        'type': resp.type,
      };
    } else if (userMsg.attachments.isNotEmpty) {
      final attach = userMsg.attachments.first;
      final bytes = await FileService.readAttachmentBytes(attach);
      final resp = await _api.uploadFile(
        fileBytes: bytes,
        fileName: attach.name,
        message: text,
        sessionId: sessionId,
        timezone: timezone.isNotEmpty ? timezone : null,
        location: location,
      );
      return {'response': resp.content, 'image_data': '', 'type': resp.type};
    }
    // Check for file generation requests (PDF, Word, Excel, etc.) before image gen
    final fileFormat = _detectFileGenFormat(text);
    if (fileFormat != null) {
      if (fileFormat == 'png') {
        // PNG is an image format — route to image generation instead
        final imgResp = await _api.generateImage(
          prompt: text,
          sessionId: sessionId,
        );
        return {
          'response':
              (imgResp['response'] as String?) ??
              (imgResp['content'] as String?) ??
              '',
          'image_data':
              (imgResp['image_data'] as String?) ??
              (imgResp['imageBase64'] as String?) ??
              '',
          'type': (imgResp['type'] as String?) ?? 'image_gen',
        };
      }

      // For non-image file formats (PDF, DOCX, XLSX, CSV, etc.)
      for (var attempt = 0; attempt < 2; attempt++) {
        try {
          final isComplex = text.length > 80;
          String instruction;
          // Format-specific instructions ensure proper content generation
          final formatInstructions = {
            'pdf':
                'Generate structured HTML content that will be converted to a PDF document. Use proper HTML tags like <h1>, <h2>, <p>, <ul>, <ol>, <li>, <table>, <tr>, <td>, <th>, <pre>, <code>, <strong>, <em>, <br> to structure the content clearly. The HTML will be automatically converted to a proper downloadable PDF file. CRITICAL: You MUST include EVERY specific detail, data point, and section the user requested — do NOT omit any content, do NOT use placeholder text, do NOT use sample data. Include the COMPLETE content the user asked for. Return ONLY the HTML content, no explanations, no greetings, no markdown fences.',
            'docx':
                'Generate HTML content for a Microsoft Word document. Use proper HTML tags like <h1>, <h2>, <p>, <ul>, <ol>, <li>, <table>, <tr>, <td>, <th>, <strong>, <em>, <br> to structure the content. CRITICAL: You MUST include EVERY specific detail, data point, and section the user requested — do NOT omit any content, do NOT use placeholder text, do NOT use sample data. Include the COMPLETE content the user asked for. Return ONLY the HTML content, no explanations, no greetings, no markdown fences.',
            'xlsx':
                'Generate CSV content (comma-separated values) for an Excel spreadsheet. The first row should be column headers. Each subsequent row is a data row with ACTUAL values — do NOT leave cells empty, do NOT use placeholder data. Use proper CSV escaping (double-quote fields containing commas or newlines). CRITICAL: You MUST include EVERY specific data point and row the user requested — include the COMPLETE dataset with all the values asked for. Return ONLY the CSV content, no explanations, no markdown fences.',
            'csv':
                'Generate CSV content (comma-separated values). The first row should be column headers. Each subsequent row is a data row with ACTUAL values — do NOT leave cells empty, do NOT use placeholder data. Use proper CSV escaping. CRITICAL: You MUST include EVERY specific data point the user requested — include the COMPLETE dataset. Return ONLY the CSV content, no explanations, no markdown fences.',
            'md':
                'Generate Markdown content. Use proper markdown formatting with headings, lists, tables, code blocks, and emphasis as appropriate. CRITICAL: You MUST include ALL the specific content the user requested — do NOT omit any sections or details. Return ONLY the markdown content, no explanations, no markdown fences.',
            'html':
                'Generate a complete HTML web page. Include DOCTYPE, html, head, and body tags with proper CSS styling. CRITICAL: You MUST include ALL the specific content and context the user requested — every detail must be in the page. Return ONLY the HTML code, no explanations, no markdown fences.',
            'json':
                'Generate JSON content. Ensure it is valid JSON format. CRITICAL: You MUST include ALL the specific data the user requested — every field, value, and nested structure. Return ONLY the JSON content, no explanations, no markdown fences.',
            'xml':
                'Generate XML content. Ensure it is well-formed XML with proper tags. CRITICAL: You MUST include ALL the specific data the user requested — every element and attribute. Return ONLY the XML content, no explanations, no markdown fences.',
            'svg':
                'Generate SVG image content as raw SVG XML. Include proper viewBox and namespace attributes. CRITICAL: You MUST include ALL the specific visual elements the user requested. Return ONLY the SVG XML, no explanations, no markdown fences.',
            'txt':
                'Generate plain text content. Format the text clearly with sections and proper line breaks. CRITICAL: You MUST include ALL the specific information the user requested — every detail, point, and section complete. Return ONLY the text content, no explanations, no markdown fences.',
          };
          final fmtInstruction =
              formatInstructions[fileFormat] ??
              'Generate the complete content for a ${fileFormat.toUpperCase()} file. CRITICAL: You MUST include EVERY specific detail, data point, and section the user requested — do NOT omit any content, do NOT use placeholder text. Include the COMPLETE content. Return ONLY the raw file content, no explanations, no markdown fences.';
          if (isComplex) {
            instruction =
                'The user wants: $text\n\n$fmtInstruction\n\nCRITICAL INSTRUCTION: Carefully read the user\'s request above and include EVERY specific detail, data point, and section they asked for. The content must be COMPREHENSIVE and COMPLETE — do not summarize, do not use placeholders, do not omit anything. Generate the ACTUAL full content with ALL the information specified. If the user provides specific text to include, include it VERBATIM.';
          } else {
            instruction =
                'The user requested: "$text"\n\n$fmtInstruction\n\nCRITICAL INSTRUCTION: Include the COMPLETE content the user requested — every detail, every data point. Do NOT omit or summarize anything.';
          }
          final history = _buildMessageHistory();
          final chatResp = await _api.chat(
            message: instruction,
            sessionId: sessionId,
            timezone: timezone.isNotEmpty ? timezone : null,
            location: location,
            messages: history,
          );
          final rawContent = _stripMarkdownFences(chatResp.content);
          if (rawContent.isNotEmpty) {
            final fileResp = await _api.generateFile(
              content: rawContent,
              format: fileFormat,
              filename: 'document.$fileFormat',
            );
            final fileContent = fileResp['content'] as String? ?? '';
            final fileName =
                fileResp['filename'] as String? ?? 'document.$fileFormat';
            final fileType = fileResp['format'] as String? ?? fileFormat;
            return {
              'response': '',
              'image_data': '',
              'type': 'chat',
              'file_data': fileContent,
              'file_name': fileName,
              'file_type': fileType,
            };
          }
        } catch (e) {
          if (attempt < 1) {
            await Future.delayed(const Duration(seconds: 2));
          }
        }
      }
      return {'response': '', 'image_data': '', 'type': 'error'};
    }
    if (_isImageGenRequest(text)) {
      final imgResp = await _api.generateImage(
        prompt: text,
        sessionId: sessionId,
      );
      return {
        'response':
            (imgResp['response'] as String?) ??
            (imgResp['content'] as String?) ??
            '',
        'image_data':
            (imgResp['image_data'] as String?) ??
            (imgResp['imageBase64'] as String?) ??
            '',
        'type': (imgResp['type'] as String?) ?? 'image_gen',
      };
    }
    final history = _buildMessageHistory();
    final resp = await _api.chat(
      message: text,
      sessionId: sessionId,
      timezone: timezone.isNotEmpty ? timezone : null,
      location: location,
      messages: history,
    );
    return {
      'response': resp.content,
      'image_data': resp.imageBase64 ?? '',
      'type': resp.type,
      'file_data': resp.fileData ?? '',
      'file_name': resp.fileName ?? '',
      'file_type': resp.fileType ?? '',
    };
  }

  Future<void> pickImageForAnalysis(BuildContext context) async {
    try {
      final attachment = await _fileService.pickImageFromGallery();
      if (attachment != null) {
        _pendingAttachments.add(attachment);
        notifyListeners();
      }
    } catch (e) {
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: const Text('Failed to load image. Please try again.'),
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
      try {
        final image = await _fileService.pickImageFromCamera();
        if (image == null) return;
        _pendingAttachments.add(image);
        notifyListeners();
      } catch (e2) {
        if (context.mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: const Text('Could not access camera. Please try again.'),
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
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: const Text('Something went wrong. Please try again.'),
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
              Future.delayed(
                const Duration(milliseconds: 500),
                startVoiceInput,
              );
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
    } catch (_) {}
  }

  Future<void> pickFile() async {
    try {
      final attachment = await _fileService.pickFile();
      if (attachment != null) {
        _pendingAttachments.add(attachment);
        notifyListeners();
      }
    } catch (_) {}
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
    } catch (_) {}
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

  String? _error;
  String? get error => _error;

  void setError(String? error) {
    _error = error;
    notifyListeners();
  }

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
