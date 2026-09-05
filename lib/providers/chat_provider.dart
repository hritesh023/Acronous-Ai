import 'dart:async';
import 'dart:convert';
import 'dart:js_util' as js_util;
import 'dart:math' as math;

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:web/web.dart' as web;
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:image_picker/image_picker.dart';
import 'package:geolocator/geolocator.dart' as geo;
import 'package:geocoding/geocoding.dart' as geocoding;
import '../api/client.dart';
import '../config/app_config.dart';
import '../constants/app_constants.dart';
import '../models/message.dart';
import '../services/file_service.dart';
import '../services/preferences_service.dart';
import '../services/speech_service.dart';
import '../services/tts_service.dart';
import '../services/overlay_service.dart';
import '../services/continuous_voice_service.dart';
import '../widgets/camera_screen.dart';

class ChatProvider extends ChangeNotifier {
  final ApiClient _api;
  final PreferencesService _prefs;
  final FileService _fileService;
  final SpeechService _speech;
  final TtsService _tts;
  final ContinuousVoiceService _continuousVoiceService;

  bool _isServerConnected = false;
  bool _serverCheckDone = false;
  bool _isConnecting = true;

  bool get isServerConnected => _isServerConnected;
  bool get serverCheckDone => _serverCheckDone;
  bool get isConnecting => _isConnecting;

  static final RegExp _privateInfoLinePattern = RegExp(
    r"(api[ _]?key[\s:=]+|system prompt[\s:=]+|internal (configuration|instructions|prompt)[\s:=]+|powered by \w|based on (my|the|our) (training|web )?(data|)?search|according to (my|the|our) (web )?(search|results?|findings?)|i (searched|looked\s+up|checked|found|retrieved|gathered) (online|the\s+web|information|data)|let me (search|look\s+up|check|find)|as of my (knowledge\s+)?(cutoff|training)|knowledge cutoff|last (updated|trained|update)|training data|as an AI|as a language model|as an AI assistant)",
    caseSensitive: false,
  );

  static String _sanitizeAssistantText(String text) {
    if (text.trim().isEmpty) return '';
    // PROTECT fenced code blocks — their contents (indentation, brackets,
    // URLs, identifiers) must NEVER be altered by the sanitizer
    final codeBlocks = <String>[];
    var cleaned = text.replaceAllMapped(RegExp(r'```[\s\S]*?```'), (m) {
      codeBlocks.add(m.group(0)!);
      return '\u0000CB${codeBlocks.length - 1}\u0000';
    });
    cleaned = cleaned
        .replaceAll(RegExp(r'\[[^\]]*\]'), '') // Strip bracket tags in prose (internal markers, search context, etc.)
        .replaceAll(RegExp(r'\n{3,}'), '\n\n')
        .trim();
    if (cleaned.isEmpty && codeBlocks.isEmpty) return text.trim();
    // Strip apologetic openers — Acronous AI never apologizes
    cleaned = cleaned.replaceFirst(
      RegExp(
        r"^\s*(?:(?:i'?m|i\s+am|we'?re|we\s+are)\s+(?:really|very|so|terribly|deeply)\s+)?(?:sorry|apologize|apologise|apologies)(?:\s+(?:really|very|so|terribly|deeply))?\b[,.;:!]*\s*(?:but|however|yet|though)?\s*",
        caseSensitive: false,
      ),
      '',
    );
    cleaned = cleaned.replaceFirst(
      RegExp(r"^\s*(?:my|our)\s+(?:sincere\s+)?apologies\b[,.;:!]*\s*(?:but|however|yet|though)?\s*", caseSensitive: false),
      '',
    );
    // Whole-text cleanup: strip backend leak phrases anywhere in the prose
    cleaned = cleaned
        // Stock-photo / placeholder image services are NEVER part of an
        // answer — their mention means a hallucinated URL leaked through
        .replaceAll(
          RegExp(
            r'[^\n]*(?:picsum|pexels|unsplash|pixabay|shutterstock|loremflickr|placehold\.(?:co|com))[^\n]*',
            caseSensitive: false,
          ),
          '',
        )
        .replaceAll(RegExp(r'(?:powered\s+by|brought\s+to\s+you\s+by|sponsored\s+by|supported\s+by|provided\s+by)\s+[^.\n]*', caseSensitive: false), '')
        .replaceAll(RegExp(r'\b(?:based\s+on\s+(?:my|the|our)\s+(?:training|web\s+)?(?:data\s+)?search|according\s+to\s+(?:my|the|our)\s+(?:web\s+)?(?:search|results?|findings?)|as\s+per\s+(?:my|the)\s+search|i\s+(?:searched|looked\s+up|checked|found|retrieved|gathered)\s+(?:online|the\s+web|information|data)|let\s+me\s+(?:search|look\s+up|check|find))\b[^.\n]*', caseSensitive: false), '')
        .replaceAll(RegExp(r'\b(?:as\s+of\s+my\s+(?:knowledge\s+)?cutoff|knowledge\s+cutoff|last\s+(?:updated|trained|update\s+in)|training\s+data|based\s+on\s+my\s+training)\b[^.\n]*', caseSensitive: false), '')
        .replaceAll(RegExp(r'\bas\s+of\s+(?:my\s+)?(?:last\s+)?(?:knowledge\s+)?(?:cutoff\s+)?(?:in\s+)?\d{4}\b[^.\n]*', caseSensitive: false), '')
        .replaceAll(RegExp(r'\b(?:as\s+(?:an?\s+)?(?:AI|language\s+model|AI\s+language\s+model|assistant))\b[^.\n]*', caseSensitive: false), '')
        .replaceAll(RegExp(r"\b(?:i[']?m\s+(?:an?\s+)?(?:AI|language\s+model|AI\s+assistant))\b[^.\n]*", caseSensitive: false), '')
        .replaceAll(RegExp(r"\b(?:i\s+(?:don[']?t|do\s+not)\s+have\s+(?:access\s+to|real[- ]time|live|current|up[- ]to[- ]date))\b[^.\n]*", caseSensitive: false), '')
        .replaceAll(RegExp(r"\b(?:i\s+(?:cannot|can[']?t|am\s+unable\s+to)\s+(?:browse|search|access|check))\b[^.\n]*", caseSensitive: false), '')
        .replaceAll(RegExp(r'\b(?:please\s+(?:check|verify|confirm|visit)\s+(?:the|external|online|official))\b[^.\n]*', caseSensitive: false), '')
        // Backend/provider/model/company names — replaced with Acronous so the
        // sentence still reads naturally but NO third-party name ever shows
        .replaceAll(
          RegExp(
            r'\b(?:cloudflare\s+workers?|cloudflare|workers\s+ai|searxng|duckduckgo|ollama|llama|qwen|deepseek|chatgpt|gpt[- ]?[45o]|gpt|claude|anthropic|openai|gemini|mistral|cohere|llava|stable\s+diffusion|instructpix2pix|flux\.?1|flux|groq|hugging\s*face|deepmind|runwayml|black[- ]forest[- ]labs|pollinations|nominatim|moviepy|edge[- ]tts|rembg|real[- ]esrgan|whisper|oracle|image[- ]?service|backend|deployment|sana)\b',
            caseSensitive: false,
          ),
          'Acronous',
        )
        // Identity sentences that survived the above ("I am Acronous based on…") get normalized
        .replaceAll(RegExp(r"(?:i(?:'m| am)|built|created|developed|trained|made)\s+(?:on|by|with|using)\s+Acronous\b[^.\n]*", caseSensitive: false), '')
        // Strip GPS coordinates from responses
        .replaceAll(RegExp(r'\d{1,3}\.\d{2,6}\s*°?\s*[NSns]\s*[,;]?\s*\d{1,3}\.\d{2,6}\s*°?\s*[EWew]'), '')
        .replaceAll(RegExp(r'\b(?:latitude|lat|lng|longitude)\s*[:=]?\s*-?\d{1,3}\.\d{1,6}', caseSensitive: false), '')
        .replaceAll(RegExp(r'\(\s*-?\d{1,3}\.\d{1,6}\s*,\s*-?\d{1,3}\.\d{1,6}\s*\)'), '')
        .replaceAll(RegExp(r'\n{3,}'), '\n\n')
        .trim();
    // Whitespace collapse ONLY on prose (never touches restored code blocks)
    cleaned = cleaned.split('\n').map((l) => l.trim()).join('\n').replaceAll(RegExp(r'\n{3,}'), '\n\n');
    // Restore protected code blocks exactly as generated
    cleaned = cleaned.replaceAllMapped(RegExp('\u0000CB(\\d+)\u0000'), (m) {
      final i = int.tryParse(m.group(1)!);
      return (i != null && i < codeBlocks.length) ? codeBlocks[i] : '';
    });
    // Line-by-line cleanup as well
    final lines = cleaned.split('\n');
    final filtered = lines.where((line) {
      final t = line.trim();
      if (t.startsWith('```')) return true; // never drop fence lines
      return !_privateInfoLinePattern.hasMatch(t);
    }).join('\n').trim();
    return filtered.isEmpty ? cleaned : filtered;
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

  double _ttsSpeed = 1.0;
  double _ttsPitch = 1.0;
  bool _autoSendVoice = false;
  bool _continuousVoiceEnabled = false;
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
       _tts = tts ?? TtsService(),
       _continuousVoiceService = ContinuousVoiceService(speech: speech ?? SpeechService()) {
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

    for (var attempt = 1; attempt <= retries; attempt++) {
      try {
        final bestUrl = await ApiClient.detectBaseUrl(
          configuredUrl: AppConfig.instance.apiBaseUrl,
          savedUrl: savedUrl,
        );
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
    _continuousVoiceService.stop();
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
    _finishGenerationProgress();
    _api.cancelCurrentRequest();
    notifyListeners();
  }

  // ── Generation progress skeleton ────────────────────────────────────────
  // While an image / video / document / image-edit is being produced, an
  // assistant bubble shows a skeleton preview whose status label cycles
  // through steps derived from what the user actually asked for.
  Timer? _progressTimer;
  ChatMessage? _progressMsg;
  List<String> _progressSteps = const [];
  int _progressIdx = 0;

  bool get _generationInProgress => _progressMsg != null;

  static bool _isVideoGenRequest(String text) {
    final t = text.trim().toLowerCase();
    if (t.length < 5) return false;
    final patterns = [
      RegExp(r'\b(make|create|generate|produce|render|give me|show me|build)\b[^.?!]{0,60}\b(video|animation|animated (clip|video|short)|motion graphic)\b'),
      RegExp(r'\b(video|animation)\s+(of|about|for|on)\b'),
      RegExp(r'^\s*(make|create|generate)\s+(me\s+)?(a\s+)?(short\s+)?(clip|video)\b'),
      RegExp(r'\b\d+\s*(second|sec|minute|min)\s+video\b'),
    ];
    return patterns.any((p) => p.hasMatch(t));
  }

  static String? _extractImageSubject(String text) {
    var t = text.trim().toLowerCase().replaceAll(RegExp(r'[!.?]+$'), '');
    t = t.replaceFirst(
      RegExp(r'^(please\s+|can you\s+|could you\s+|i want you to\s+|i need you to\s+)'),
      '',
    );
    t = t.replaceFirst(
      RegExp(
        r'^(draw|paint|sketch|render|imagine|generate|create|make|design)\s+(me\s+)?(an?\s+|the\s+)?(image|picture|photo|artwork|drawing|painting|illustration)?\s*(of\s+|showing\s+|with\s+)?',
      ),
      '',
    ).trim();
    if (t.isEmpty || t.length < 3) return null;
    if (t.length > 42) {
      final cut = t.substring(0, 42);
      final lastSpace = cut.lastIndexOf(' ');
      t = lastSpace > 12 ? cut.substring(0, lastSpace) : cut;
    }
    return t;
  }

  static List<String> _buildProgressSteps(
    String text, {
    required String kind,
  }) {
    final t = text.toLowerCase();
    switch (kind) {
      case 'edit':
        final steps = <String>['Analyzing your photo…'];
        if (t.contains('background')) {
          steps.addAll(['Removing the old background…', 'Blending in the new background…']);
        } else if (RegExp(r'recolo|change.{0,12}colou?r|color swap|different colou?r').hasMatch(t)) {
          steps.add('Recoloring your image…');
        } else if (RegExp(r'enhance|sharp|hd|4k|quality|upscale|brighten|clearer|denoise').hasMatch(t)) {
          steps.add('Enhancing details and clarity…');
        } else if (RegExp(r'remove|erase|delete|get rid of').hasMatch(t)) {
          steps.add('Removing unwanted elements…');
        } else if (RegExp(r'dress|suit|outfit|shirt|hairstyle|hair|face').hasMatch(t)) {
          steps.add('Reworking the subject…');
        }
        steps.addAll([
          'Applying your changes…',
          'Refining edges and lighting…',
          'Applying final touches…',
        ]);
        return steps;
      case 'video':
        return [
          'Storyboarding your video…',
          'Designing scenes from your idea…',
          'Animating shot 1…',
          'Animating shot 2…',
          'Rendering transitions…',
          'Recording narration…',
          'Encoding video…',
          'Applying final touches…',
        ];
      case 'file':
        return [
          'Outlining your document…',
          'Generating the content…',
          'Formatting pages…',
          'Polishing wording…',
          'Applying final touches…',
        ];
      default:
        final subject = _extractImageSubject(text);
        return [
          if (subject != null) 'Imagining $subject…',
          'Sketching the composition…',
          'Painting colors and light…',
          'Adding depth and texture…',
          'Applying final touches…',
        ];
    }
  }

  void _startGenerationProgress(String text, {required String kind}) {
    _finishGenerationProgress();
    _progressSteps = _buildProgressSteps(text, kind: kind);
    if (_progressSteps.isEmpty) return;
    _progressIdx = 0;
    _progressMsg = ChatMessage(
      role: 'assistant',
      content: '',
      isStreaming: true,
      progressLabel: _progressSteps.first,
      progressKind: kind,
    );
    _currentConversation!.messages.add(_progressMsg!);
    _progressTimer = Timer.periodic(const Duration(milliseconds: 2400), (_) {
      final msg = _progressMsg;
      if (msg == null || _progressSteps.isEmpty) return;
      // Cycle forward but hold on the final step ("Applying final touches…").
      _progressIdx = math.min(_progressIdx + 1, _progressSteps.length - 1);
      msg.progressLabel = _progressSteps[_progressIdx];
      notifyListeners();
    });
    notifyListeners();
  }

  void _finishGenerationProgress({bool remove = true}) {
    _progressTimer?.cancel();
    _progressTimer = null;
    final msg = _progressMsg;
    _progressMsg = null;
    _progressSteps = const [];
    if (msg != null && remove && _currentConversation != null) {
      _currentConversation!.messages.remove(msg);
    }
  }

  // ── End generation progress skeleton ────────────────────────────────────

  String _cachedLocation = '';
  String _cachedGpsCoords = '';

  Future<void> _fetchLocationInfo() async {
    // Try GPS first for exact location, fall back to IP-based
    final gpsSuccess = await _fetchFromGps();
    if (!gpsSuccess) {
      // Fallback: try both IP APIs in parallel
      await Future.wait([
        _fetchFromIpApi(),
        _fetchFromFreeIp(),
      ]);
    }
    // If neither worked, use device timezone offset mapped to IANA
    if (_cachedTimezoneName.isEmpty) {
      _cachedTimezoneName = _deviceTimezoneIana;
    }
  }

  Future<bool> _fetchFromGps() async {
    try {
      // On web, call browser's native navigator.geolocation directly via JS interop.
      // The Flutter Geolocator plugin is unreliable on web — the native API works.
      if (kIsWeb) {
        try {
          final result = await _getBrowserGps();
          if (result != null) {
            _cachedGpsCoords = '${result[0]},${result[1]}';
            if (_cachedTimezoneName.isEmpty) _cachedTimezoneName = _deviceTimezoneIana;
            return true;
          }
        } catch (_) {}
        return false;
      }

      // Mobile path — use Flutter Geolocator plugin
      bool serviceEnabled = await geo.Geolocator.isLocationServiceEnabled();
      if (!serviceEnabled) return false;

      geo.LocationPermission permission = await geo.Geolocator.checkPermission();
      if (permission == geo.LocationPermission.denied) {
        permission = await geo.Geolocator.requestPermission();
        if (permission == geo.LocationPermission.denied) return false;
      }
      if (permission == geo.LocationPermission.deniedForever) return false;

      final position = await geo.Geolocator.getCurrentPosition(
        locationSettings: geo.LocationSettings(
          accuracy: geo.LocationAccuracy.high,
          timeLimit: Duration(seconds: 10),
        ),
      );

      final lat = position.latitude;
      final lng = position.longitude;
      _cachedGpsCoords = '$lat,$lng';

      try {
        final placemarks = await geocoding.placemarkFromCoordinates(lat, lng);
        if (placemarks.isNotEmpty) {
          final place = placemarks.first;
          final parts = <String>[];
          final street = place.street ?? '';
          final subLocality = place.subLocality ?? '';
          final locality = place.locality ?? '';
          final subAdmin = place.subAdministrativeArea ?? '';
          final admin = place.administrativeArea ?? '';
          final postalCode = place.postalCode ?? '';
          final country = place.country ?? '';
          if (street.isNotEmpty && street != locality && street != subAdmin) {
            parts.add(street);
          }
          if (subLocality.isNotEmpty && subLocality != locality && subLocality != subAdmin) {
            parts.add(subLocality);
          }
          if (locality.isNotEmpty && locality != subAdmin) {
            parts.add(locality);
          } else if (subAdmin.isNotEmpty) {
            parts.add(subAdmin);
          }
          if (admin.isNotEmpty && admin != locality) {
            parts.add(admin);
          }
          if (postalCode.isNotEmpty) parts.add(postalCode);
          if (country.isNotEmpty) parts.add(country);
          final address = parts.join(', ');
          if (address.isNotEmpty) {
            _cachedLocation = address;
          }
        }
      } catch (_) {}

      if (_cachedTimezoneName.isEmpty) {
        _cachedTimezoneName = _deviceTimezoneIana;
      }

      return true;
    } catch (_) {
      return false;
    }
  }

  Future<List<double>?> _getBrowserGps() async {
    final completer = Completer<List<double>?>();
    try {
      final geoObj = web.window.navigator.geolocation;
      js_util.callMethod(geoObj, 'getCurrentPosition', [
        js_util.allowInterop((dynamic pos) {
          if (!completer.isCompleted && pos != null) {
            final coords = js_util.getProperty(pos, 'coords');
            final lat = js_util.getProperty(coords, 'latitude') as double;
            final lng = js_util.getProperty(coords, 'longitude') as double;
            completer.complete([lat, lng]);
          }
        }),
        js_util.allowInterop((dynamic err) {
          if (!completer.isCompleted) completer.complete(null);
        }),
      ]);
      return completer.future.timeout(Duration(seconds: 15));
    } catch (_) {
      return null;
    }
  }

  Future<bool> _fetchFromIpApi() async {
    try {
      final resp = await http
          .get(Uri.parse('https://ip-api.com/json/'))
          .timeout(const Duration(seconds: 5));
      if (resp.statusCode != 200) return false;
      final data = jsonDecode(resp.body) as Map<String, dynamic>;
      if (data['status'] != 'success') return false;
      _updateLocationData(
        city: data['city'] as String? ?? '',
        region: data['regionName'] as String? ?? '',
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
          .timeout(const Duration(seconds: 5));
      if (resp.statusCode != 200) return false;
      final data = jsonDecode(resp.body) as Map<String, dynamic>;
      if (data['status'] != 'success') return false;
      _updateLocationData(
        city: data['cityName'] as String? ?? data['city'] as String? ?? '',
        region: data['regionName'] as String? ?? data['region'] as String? ?? '',
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
    String region = '',
    required String country,
    required String timezone,
  }) {
    final parts = <String>[];
    if (city.isNotEmpty) parts.add(city);
    if (region.isNotEmpty && region != city) parts.add(region);
    if (country.isNotEmpty) parts.add(country);
    if (parts.isNotEmpty) {
      _cachedLocation = parts.join(', ');
    }
    if (timezone.isNotEmpty) {
      _cachedTimezoneName = timezone;
    }
  }

  String _cachedTimezoneName = '';

  String get _deviceTimezoneIana {
    try {
      final now = DateTime.now();
      final offset = now.timeZoneOffset;
      final totalMinutes = offset.inMinutes;
      // Map common UTC offsets to IANA timezone names
      const offsetMap = <int, String>{
        -720: 'Pacific/Midway',
        -660: 'Pacific/Honolulu',
        -600: 'America/Anchorage',
        -540: 'America/Los_Angeles',
        -480: 'America/Denver',
        -420: 'America/Chicago',
        -360: 'America/New_York',
        -300: 'America/Caracas',
        -240: 'America/Halifax',
        -180: 'America/Sao_Paulo',
        -120: 'Atlantic/South_Georgia',
        -60: 'Atlantic/Azores',
        0: 'Europe/London',
        60: 'Europe/Paris',
        120: 'Europe/Helsinki',
        180: 'Europe/Moscow',
        240: 'Asia/Tbilisi',
        270: 'Asia/Tehran',
        300: 'Asia/Dubai',
        330: 'Asia/Kolkata',
        345: 'Asia/Kathmandu',
        360: 'Asia/Dhaka',
        390: 'Asia/Yangon',
        420: 'Asia/Bangkok',
        480: 'Asia/Shanghai',
        540: 'Asia/Tokyo',
        570: 'Australia/Adelaide',
        600: 'Australia/Sydney',
        660: 'Pacific/Noumea',
        720: 'Pacific/Auckland',
        765: 'Pacific/Chatham',
        780: 'Pacific/Tongatapu',
      };
      final mapped = offsetMap[totalMinutes];
      if (mapped != null) return mapped;
      // Generic fallback: construct UTC offset string
      final sign = totalMinutes >= 0 ? '+' : '-';
      final absMinutes = totalMinutes.abs();
      final hours = absMinutes ~/ 60;
      final minutes = absMinutes % 60;
      return 'UTC$sign${hours.toString().padLeft(2, '0')}:${minutes.toString().padLeft(2, '0')}';
    } catch (_) {
      return '';
    }
  }

  static final RegExp _questionStartPattern = RegExp(
    r'^(?:how|what|why|which|where|who|when|is|are|was|were|does|do|did)\b',
    caseSensitive: false,
  );

  /// Detects image-edit intent in plain text WITHOUT an attached image.
  /// Requests like "edit this photo", "turn the background into beach",
  /// "remove the background", "make it brighter" must never fall through to
  /// plain chat — the LLM used to answer those with code snippets.
  bool _looksLikeImageEditRequest(String text) {
    final t = text.trim().toLowerCase();
    if (t.length < 4) return false;

    // File-conversion asks route to file generation, not image editing
    if (_detectFileGenFormat(text) != null) return false;
    // Image-generation asks have their own pipeline
    if (_isImageGenRequest(text)) return false;

    // Code-related asks belong to normal chat — never hijack them
    const codeHints = [
      'code', 'snippet', 'script', 'function', 'program', 'algorithm',
      'python', 'javascript', 'typescript', 'java ', 'c++', 'c#',
      'sql', 'html', 'css', 'flutter', 'react', 'node.js', 'regex',
      'query', 'terminal', 'formula',
    ];
    for (final h in codeHints) {
      if (t.contains(h)) return false;
    }
    // Questions ABOUT editing are informational, not edit requests
    if (_questionStartPattern.hasMatch(t)) return false;
    // Brainstorming / informational asks are not edits either
    if (RegExp(
      r'\b(?:ideas?|concepts?|suggestions?|tips?|tutorial|guide|examples?|learn|learning|course|lessons?)\b',
    ).hasMatch(t)) {
      return false;
    }

    // Nouns that live INSIDE a picture — editing targets
    final hasTargetNoun = RegExp(
      r'\b(?:images?|photos?|photographs?|pictures?|pics?|selfies?|screenshots?|wallpapers?|portraits?|avatars?|backgrounds?|bg|skies|sky|hair|hairstyle|haircut|face|eyes?|eyebrows|teeth|skin|dress|gown|shirt|t-?shirt|outfit|clothes|clothing|suit|jeans|jacket|coat|watermark|logo|object|objects|person|people|head|hat|cap|glasses|sunglasses|beard|moustache|mustache|scenery|scene|setting)\b',
    ).hasMatch(t);

    final hasActionWord = RegExp(
      r'\b(?:edit|edits|editing|edited|chang\w+|turn\w*|mak\w+|convert\w*|transform\w*|replac\w+|swap\w*|set|put|appl\w+|add\w*|giv\w+|remov\w+|delet\w+ |eras\w+|clean\w*|clear\w*|fix\w*|repair\w*|redo|redraw|repaint|redesign\w*|restyle\w*|reimagin\w*|regenerat\w*|styliz\w*|stylis\w*|enhanc\w+|improv\w+|blur\w*|sharpen\w*|brighten\w*|darken\w*|lighten\w*|crop\w*|resiz\w+|rotat\w+|flip\w*|upscale[ds]?|restor\w+|coloriz\w+|colouris\w+|recolou?r\w*|extend\w*|fill|outpaint)\b'
      r'|touch\s?up'
      r'|(?:can|could|will)\s+you\b'
      r'|i\s+(?:want|need|would\s+like)\b',
    ).hasMatch(t);

    // "edit this photo", "turn the background into beach", "change her dress"…
    if (hasTargetNoun && hasActionWord) return true;

    // Short follow-ups referring to a recent result:
    // "make it brighter", "turn it into anime"
    final refersToResult = RegExp(
      r'\b(?:make|turn|change|convert|transform|enhance|improve|blur|sharpen|brighten|darken|recolor|recolour|restore|redo)\s+(?:it|this|that|him|her|them|everything)\b',
    ).hasMatch(t);
    final transformTarget = RegExp(
      r'(?:into|to)\s+(?:a|an)?\s*(?:cartoon|anime|painting|sketch|drawing|watercolor|oil painting|3d render|pixar)',
      caseSensitive: false,
    ).hasMatch(t);
    if (refersToResult || transformTarget) return true;

    return false;
  }

  /// Returns the base64 image data of the most recent assistant-generated
  /// image in the current conversation, or null if none exists.
  String? _findLastGeneratedImageData() {
    if (_currentConversation == null) return null;
    final msgs = _currentConversation!.messages;
    for (var i = msgs.length - 1; i >= 0; i--) {
      final m = msgs[i];
      if (m.role == 'assistant' && m.imageData.isNotEmpty) return m.imageData;
    }
    return null;
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

    // ── Smart request classification ────────────────────────────────────
    // An image-edit request without an attached image must NEVER fall
    // through to plain chat. Reuse the most recently generated image if one
    // exists; otherwise the request is intercepted below and the user is
    // asked to attach an image.
    final editIntentWithoutAttachment =
        attach.isEmpty &&
        !_isImageGenRequest(text) &&
        _looksLikeImageEditRequest(text);
    List<MessageAttachment> effectiveAttachments =
        List<MessageAttachment>.from(attach);
    if (editIntentWithoutAttachment) {
      final lastImageData = _findLastGeneratedImageData();
      if (lastImageData != null) {
        try {
          var b64 = lastImageData.trim();
          final commaIdx = b64.indexOf(',');
          if (b64.startsWith('data:') && commaIdx != -1) {
            b64 = b64.substring(commaIdx + 1);
          }
          b64 = b64.replaceAll(RegExp(r'\s'), '');
          final bytes = base64Decode(b64);
          if (bytes.isNotEmpty) {
            effectiveAttachments.add(MessageAttachment(
              name: 'image_edit_${DateTime.now().millisecondsSinceEpoch}.png',
              path: '',
              type: AttachmentType.image,
              bytes: bytes,
            ));
          }
        } catch (_) {}
      }
    }

    if (_isLoading) {
      _messageQueue.add({'text': text, 'attachments': effectiveAttachments});
      final userMsg = ChatMessage(
        role: 'user',
        content: text,
        attachments: List.from(effectiveAttachments),
      );
      _currentConversation!.messages.add(userMsg);
      _currentConversation!.updatedAt = DateTime.now();
      if (attachments == null) _pendingAttachments.clear();
      notifyListeners();
      return;
    }

    // Intercept edit requests that reference no image at all — reply asking
    // for the image instead of letting the chat model improvise with code.
    if (editIntentWithoutAttachment && effectiveAttachments.isEmpty) {
      _currentConversation!.messages.add(
        ChatMessage(role: 'user', content: text),
      );
      _currentConversation!.messages.add(
        ChatMessage(
          role: 'assistant',
          content:
              "Happy to! Please attach the image you'd like me to edit "
              '(use the gallery or camera button) and tell me exactly what '
              'to change — colors, background, style, objects, anything.',
        ),
      );
      _currentConversation!.updatedAt = DateTime.now();
      if (attachments == null) _pendingAttachments.clear();
      _prefs.saveConversations(_conversations).catchError((_) {});
      notifyListeners();
      _processQueue();
      return;
    }

    _cancelled = false;
    _isLoading = true;
    _isTakingLong = false;
    notifyListeners();

    final userMsg = ChatMessage(
      role: 'user',
      content: text,
      attachments: List.from(effectiveAttachments),
    );
    _currentConversation!.messages.add(userMsg);
    _currentConversation!.updatedAt = DateTime.now();
    if (attachments == null) _pendingAttachments.clear();
    notifyListeners();

    // Determine if this is a simple text-only chat eligible for streaming
    final hasAttachments = userMsg.attachments.isNotEmpty;
    final isImageGen = !hasAttachments && _isImageGenRequest(text);
    final isFileGen = !hasAttachments && !isImageGen && _detectFileGenFormat(text) != null;
    final isVideoGen = !hasAttachments && !isImageGen && !isFileGen && _isVideoGenRequest(text);
    final canStream = !hasAttachments && !isImageGen && !isFileGen;
    // Generation-style requests show a skeleton preview with live status
    // steps while the backend works (image gen, video gen, file gen, and
    // attached-image edits/analysis).
    final wantsProgress = isImageGen || isFileGen || isVideoGen ||
        (hasAttachments &&
            userMsg.attachments.any((a) => a.type == AttachmentType.image));
    if (wantsProgress) {
      _startGenerationProgress(
        text,
        kind: (hasAttachments && _isVideoGenRequest(text)) || isVideoGen
            ? 'video'
            : isFileGen
                ? 'file'
                : hasAttachments
                    ? 'edit'
                    : 'image',
      );
    }

    for (var attempt = 0; attempt < 3; attempt++) {
      if (!_isServerConnected && attempt > 0) {
        await _discoverServer(retries: 1);
      }
      try {
        Map<String, dynamic> resp;
        if (canStream && attempt == 0 && !_generationInProgress) {
          // Try streaming for text-only chat — add placeholder message
          final streamingMsg = ChatMessage(
            role: 'assistant',
            content: '',
            isStreaming: true,
          );
          _currentConversation!.messages.add(streamingMsg);
          _isTakingLong = true;
          notifyListeners();
          try {
            resp = await _streamChatResponse(
              text: text,
              sessionId: _currentConversation?.id,
              timezone: _cachedTimezoneName.isNotEmpty ? _cachedTimezoneName : _deviceTimezoneIana,
              location: _cachedLocation.isNotEmpty ? _cachedLocation : null,
              gpsCoords: _cachedGpsCoords.isNotEmpty ? _cachedGpsCoords : null,
            );
            // Mark streaming complete
            streamingMsg.isStreaming = false;
          } catch (_) {
            // Streaming failed — remove placeholder and fall through to non-streaming
            streamingMsg.isStreaming = false;
            _currentConversation!.messages.removeLast();
            notifyListeners();
            rethrow;
          }
        } else {
          resp = await _callApi(userMsg, text);
        }
        // A response arrived — drop the skeleton preview before processing.
        _finishGenerationProgress();
        final imageData = resp['image_data'] as String? ?? '';
        final fileData = resp['file_data'] as String? ?? '';
        final fileName = resp['file_name'] as String? ?? '';
        final fileType = resp['file_type'] as String? ?? '';
        final filePoster = resp['file_poster'] as String? ?? '';
        final rawContent = _sanitizeAssistantText(
          resp['response'] as String? ?? '',
        );
        final respType = resp['type'] as String? ?? 'chat';
        if (respType == 'error') {
          // NEVER drop silently — always show the user something
          _currentConversation!.messages.add(
            ChatMessage(
              role: 'assistant',
              content: rawContent.isNotEmpty
                  ? rawContent
                  : "I ran into a problem processing that request. Could you try again in a moment?",
            ),
          );
          _isTakingLong = false;
          _isLoading = false;
          _prefs.saveConversations(_conversations).catchError((_) {});
          notifyListeners();
          _processQueue();
          return;
        }
        if (rawContent.isEmpty && imageData.isEmpty && fileData.isEmpty) {
          // Streaming placeholder exists but no content — remove it
          if (canStream && _currentConversation!.messages.isNotEmpty) {
            final lastMsg = _currentConversation!.messages.last;
            if (lastMsg.role == 'assistant' && lastMsg.content.isEmpty) {
              _currentConversation!.messages.removeLast();
            }
          }
          if (attempt < 2) {
            await Future.delayed(const Duration(seconds: 2));
            continue;
          }
          // All attempts returned nothing — NEVER leave the user without a reply
          _currentConversation!.messages.add(
            ChatMessage(
              role: 'assistant',
              content: "I didn't receive a proper response just now. Please try sending your message again.",
            ),
          );
          _isTakingLong = false;
          _isLoading = false;
          _prefs.saveConversations(_conversations).catchError((_) {});
          notifyListeners();
          _processQueue();
          return;
        }

        // Ensure no empty responses are processed - this is a critical safeguard
        if ((rawContent.isEmpty && respType != 'image_gen') ||
            (imageData.isEmpty && respType == 'image_gen') ||
            (fileData.isEmpty && respType != 'error' && respType != 'chat' && respType != 'image_gen')) {
          if (attempt < 2) {
            await Future.delayed(const Duration(seconds: 2));
            continue;
          }
          // Final attempt still empty — show a message instead of dropping silently
          _currentConversation!.messages.add(
            ChatMessage(
              role: 'assistant',
              content: imageData.isEmpty && fileData.isEmpty
                  ? "I couldn't complete that request. Please try rephrasing it and sending it again."
                  : "I generated a response but the attachment data came back incomplete. Please try again.",
            ),
          );
          _isTakingLong = false;
          _isLoading = false;
          notifyListeners();
          _processQueue();
          continue;
        }
        
        if (rawContent.isNotEmpty ||
            imageData.isNotEmpty ||
            fileData.isNotEmpty) {
          // For streaming: message already exists (placeholder), update it
          // For non-streaming: add a new message
          final lastMsg = _currentConversation!.messages.isNotEmpty
              ? _currentConversation!.messages.last
              : null;
          final alreadyAdded = canStream &&
              lastMsg != null &&
              lastMsg.role == 'assistant' &&
              (lastMsg.content.isNotEmpty || lastMsg.isStreaming == false);
          if (alreadyAdded && canStream && (fileData.isNotEmpty || imageData.isNotEmpty)) {
            // Binary payload (rendered video / generated image) arrived via the
            // stream's done event — replace the text-only placeholder so the
            // attachment fields (final) are populated.
            _currentConversation!.messages.removeLast();
            _currentConversation!.messages.add(
              ChatMessage(
                role: 'assistant',
                content: rawContent,
                imageData: imageData,
                fileData: fileData,
                fileName: fileName,
                fileType: fileType,
                filePoster: filePoster,
              ),
            );
          } else if (alreadyAdded && canStream && lastMsg.content.isEmpty) {
            // Streaming placeholder exists but has no content — update it
            lastMsg.content = rawContent;
            lastMsg.isStreaming = false;
          } else if (alreadyAdded && canStream) {
            // Streaming populated the content — swap in the SANITIZED version
            // so backend/provider names are never left on screen
            lastMsg.content = rawContent;
            lastMsg.isStreaming = false;
          } else {
            // Keep conversation history meaningful: an image/file reply with no
            // text still needs a caption, otherwise later turns lose context.
            final effectiveContent = rawContent.isEmpty && (imageData.isNotEmpty || fileData.isNotEmpty)
                ? "Here's your image."
                : rawContent;
            _currentConversation!.messages.add(
              ChatMessage(
                role: 'assistant',
                content: effectiveContent,
                imageData: imageData,
                fileData: fileData,
                fileName: fileName,
                fileType: fileType,
                filePoster: filePoster,
              ),
            );
          }
        }
        _isTakingLong = false;
        _isLoading = false;
        _prefs.saveConversations(_conversations).catchError((_) {});
        notifyListeners();
        _processQueue();
        return;
      } catch (e) {
        // Remove any streaming placeholder that may have been added
        if (canStream && _currentConversation!.messages.isNotEmpty) {
          final lastMsg = _currentConversation!.messages.last;
          if (lastMsg.role == 'assistant' && lastMsg.isStreaming) {
            lastMsg.isStreaming = false;
            if (lastMsg.content.isEmpty) {
              _currentConversation!.messages.removeLast();
            }
          }
        }
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
        // Connection failed after all retries — NEVER leave the user hanging
        _finishGenerationProgress();
        _currentConversation!.messages.add(
          ChatMessage(
            role: 'assistant',
            content: "I'm having trouble connecting right now. Please check your connection and try again in a moment.",
          ),
        );
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
        : _deviceTimezoneIana;
    final location = _cachedLocation.isNotEmpty ? _cachedLocation : null;
    final gpsCoords = _cachedGpsCoords.isNotEmpty ? _cachedGpsCoords : null;

    if (hasImage) {
      final imgAttach = userMsg.attachments.firstWhere(
        (a) => a.type == AttachmentType.image,
      );
      final bytes = await FileService.readAttachmentBytes(imgAttach);
      final t = text.toLowerCase();
      final wordCount = text.trim().split(RegExp(r'\s+')).length;

      // ── Use LLM-powered smart-edit endpoint first ──
      // This intelligently classifies intent (edit/generate/analyze/chat)
      // and routes to the right handler, preserving original image dimensions
      try {
        final history = _buildMessageHistory();
        final smartResp = await _api.smartEditImage(
          imageBytes: bytes,
          fileName: imgAttach.name,
          message: text,
          sessionId: sessionId,
        timezone: timezone.isNotEmpty ? timezone : null,
          location: location,
          messages: history,
          timeout: const Duration(minutes: 30),
        );
        final response = smartResp['response'] as String? ?? '';
        final imageData = smartResp['image_data'] as String? ?? '';
        final fileData = smartResp['file_data'] as String? ?? '';
        final fileName = smartResp['file_name'] as String? ?? '';
        final fileType = smartResp['file_type'] as String? ?? '';
        final filePoster = smartResp['file_poster'] as String? ?? '';
        final respType = smartResp['type'] as String? ?? 'chat';
        // Forward video/file payloads too — converting an attached image (or any
        // file) into a video returns file_data, which must reach the message so
        // the in-bubble player actually appears (file_poster = the video's
        // thumbnail preview so the bubble never shows a blank player).
        if (imageData.isNotEmpty || fileData.isNotEmpty || response.isNotEmpty) {
          return {
            'response': response,
            'image_data': imageData,
            'file_data': fileData,
            'file_name': fileName,
            'file_type': fileType,
            'file_poster': filePoster,
            'type': respType == 'image_gen' ? respType : 'chat',
          };
        }
      } catch (_) {
        // Smart-edit failed, fall through to legacy flow
      }

      // Legacy fallback: keyword-based detection (already handled by smart-edit,
      // but kept as fallback for backward compatibility)
      // Check if the message contains image-related context words
      final visualContext = [
        'image', 'photo', 'picture', 'art', 'design', 'graphic',
        'background', 'color', 'style', 'filter', 'texture',
        'subject', 'object', 'scene', 'view', 'look',
        'cartoon', 'painting', 'sketch', 'drawing', 'anime', 'render',
        'logo', 'icon', 'banner', 'wallpaper',
        'dress', 'clothes', 'suit', 'shirt', 'outfit', 'wear',
        'face', 'hair', 'eyes', 'skin',
        'add', 'remove', 'replace', 'change',
        'cut', 'crop', 'trim',
        'part', 'section', 'area',
        'expression', 'pose', 'make', 'turn',
      ];
      final hasVisualContext = visualContext.any((w) => t.contains(w));

      // Strong edit keywords (expanded)
      final strongEditKeywords = [
        'edit this', 'edit the', 'edit my', 'edit image', 'edit photo', 'edit picture',
        'modify this', 'modify the', 'modify my',
        'redesign this', 'redesign the',
        'turn this into', 'turn it into',
        'enhance this', 'enhance the', 'enhance my', 'enhance image',
        'improve this', 'improve the', 'improve my', 'improve image',
        'make it better', 'make this better',
        'turn into cartoon', 'turn into painting', 'turn into sketch',
        'as a cartoon', 'as a painting', 'as a sketch', 'as an anime',
        'like a cartoon', 'like a painting',
        'convert to cartoon', 'convert to painting',
        'change the dress', 'change the clothes', 'change the outfit',
        'change the color', 'change the style', 'change the background',
        'change the shirt', 'change the hair', 'change the eyes',
        'change just', 'only change',
        'keep the same', 'keep everything',
        'same face', 'same person',
        'cut the', 'cut out', 'crop the', 'crop this', 'trim the',
        'make it ', 'make this ', 'make the ',
        'turn it ', 'turn this ', 'turn the ',
        'add a ', 'add some ', 'add more ',
        'remove the ', 'remove this ',
        'replace the ', 'replace this ',
        'put a ', 'put on ',
        'recolor', 'recolour',
        'change to', 'change color', 'change style',
        'convert to ', 'convert into', 'convert this ',
        'transform this ', 'transform it ',
      ];
      final isStrongMatch = strongEditKeywords.any((kw) => t.contains(kw));

      final mediumEditKeywords = [
        'make it', 'make this', 'make the',
        'turn it', 'turn this', 'turn the',
        'change', 'add', 'remove', 'replace',
        'convert', 'transform',
        'put', 'remove',
      ];

      // Lower thresholds for edit detection
      final isMediumMatch =
          hasVisualContext &&
          wordCount >= 2 &&
          mediumEditKeywords.any((kw) => t.contains(kw));

      bool isWeakKeywordMatch(String kw) {
        if (kw.endsWith(' ')) {
          return t.contains(kw) && t.indexOf(kw) + kw.length < t.length;
        }
        return t.contains(kw);
      }

      final weakEditKeywords = [
        'add', 'remove', 'replace', 'crop', 'rotate', 'resize',
        'filter', 'style', 'color', 'shade',
      ];

      // Lowered word count threshold from 5 to 3
      final isWeakMatch =
          hasVisualContext &&
          wordCount >= 3 &&
          weakEditKeywords.any(isWeakKeywordMatch);

      final startsWithEdit = RegExp(
        r'^(edit|modify|redesign|enhance|improve|change|make|turn|convert|cut|crop|trim|recolor|recolour|transform|add|remove|replace)\s+',
      ).hasMatch(t);

      // Broader catch-all: any edit-like verb + visual context = edit request
      final editVerbs = [
        'edit', 'modify', 'redesign', 'enhance', 'improve',
        'change', 'turn', 'convert', 'transform',
        'recolor', 'recolour', 'replace',
        'add', 'remove', 'crop', 'cut', 'trim',
        'rotate', 'resize', 'make', 'put',
      ];
      final hasEditVerb = editVerbs.any(
        (v) => RegExp(r'\b' + v + r'\b').hasMatch(t),
      );

      // More permissive: wordCount >= 1 (just needs text + image + edit verb)
      final isEditRequest =
          isStrongMatch ||
          isMediumMatch ||
          isWeakMatch ||
          startsWithEdit ||
          (hasEditVerb && hasVisualContext && wordCount >= 1);

      if (isEditRequest) {
        // Only use /v1/image/edit — it uses real editing tools (inpainting, Python editor, vision-guided generation)
        // No Pollinations (generates new images) and no /api/image/redesign (modifies to something else)
        try {
          final editResp = await _api.editImage(
            imageBytes: bytes,
            fileName: imgAttach.name,
            prompt: text,
            sessionId: sessionId,
            timeout: const Duration(minutes: 30),
          );
          final response = editResp['response'] as String? ?? '';
          final imageData = editResp['image_data'] as String? ?? '';
          final fileData = editResp['file_data'] as String? ?? '';
          final fileName = editResp['file_name'] as String? ?? '';
          final fileType = editResp['file_type'] as String? ?? '';
          final filePoster = editResp['file_poster'] as String? ?? '';
          final editType = editResp['type'] as String? ?? 'chat';
          if (imageData.isNotEmpty || fileData.isNotEmpty) {
            return {
              'response': response,
              'image_data': imageData,
              'type': editType,
              'file_data': fileData,
              'file_name': fileName,
              'file_type': fileType,
              'file_poster': filePoster,
            };
          }
          if (response.isNotEmpty) {
            return {'response': response, 'image_data': '', 'type': 'chat'};
          }
        } catch (_) {}
        // No Pollinations fallback — if editing fails, return empty so the
        // caller can show the apology returned by the edit endpoint
        return {
          'response': '',
          'image_data': '',
          'type': 'chat',
        };
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
        'file_data': resp.fileData ?? '',
        'file_name': resp.fileName ?? '',
        'file_type': resp.fileType ?? '',
        'file_poster': resp.filePoster ?? '',
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
      // Forward any generated video/file payload (e.g. converting an attached
      // file into a video) so it renders in the chat bubble.
      return {
        'response': resp.content,
        'image_data': '',
        'file_data': resp.fileData ?? '',
        'file_name': resp.fileName ?? '',
        'file_type': resp.fileType ?? '',
        'file_poster': resp.filePoster ?? '',
        'type': resp.type,
      };
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
            gpsCoords: gpsCoords,
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
      gpsCoords: gpsCoords,
      messages: history,
    );
    return {
      'response': resp.content,
      'image_data': resp.imageBase64 ?? '',
      'type': resp.type,
      'file_data': resp.fileData ?? '',
      'file_name': resp.fileName ?? '',
      'file_type': resp.fileType ?? '',
      'file_poster': resp.filePoster ?? '',
    };
  }

  /// Stream a chat response — returns a map with 'response' key containing
  /// the final accumulated text. Streams tokens to the UI via notifyListeners.
  Future<Map<String, dynamic>> _streamChatResponse({
    required String text,
    required String? sessionId,
    required String? timezone,
    required String? location,
    required String? gpsCoords,
  }) async {
    final history = _buildMessageHistory();
    String accumulated = '';
    String finalSessionId = sessionId ?? 'default';
    String finalType = 'chat';
    String fileData = '';
    String fileName = '';
    String fileType = '';
    String filePoster = '';
    String imageData = '';
    try {
      await for (final event in _api.chatStream(
        message: text,
        sessionId: sessionId,
        timezone: timezone != null && timezone.isNotEmpty ? timezone : null,
        location: location,
        gpsCoords: gpsCoords,
        messages: history,
      )) {
        if (_cancelled) break;
        if (event.done) {
          finalSessionId = event.sessionId.isNotEmpty ? event.sessionId : finalSessionId;
          finalType = event.type.isNotEmpty ? event.type : finalType;
          fileData = event.fileData;
          fileName = event.fileName;
          fileType = event.fileType;
          filePoster = event.filePoster;
          imageData = event.imageData;
          break;
        }
        if (event.content.isNotEmpty) {
          accumulated += event.content;
          // Sanitize live to prevent backend-detail leaks in the streaming bubble
          final sanitized = _sanitizeAssistantText(accumulated);
          // Update the last assistant message in-place for live streaming effect
          if (_currentConversation != null &&
              _currentConversation!.messages.isNotEmpty &&
              _currentConversation!.messages.last.role == 'assistant' &&
              _currentConversation!.messages.last.isStreaming) {
            _currentConversation!.messages.last.content = sanitized;
          }
          notifyListeners();
        }
      }
    } catch (_) {
      // Streaming failed — caller will fall back to non-streaming
      rethrow;
    }
    return {
      'response': accumulated,
      'image_data': imageData,
      'file_data': fileData,
      'file_name': fileName,
      'file_type': fileType,
      'file_poster': filePoster,
      'type': finalType,
      'session_id': finalSessionId,
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
      await _speech.initialize(
        onStatusCallback: (status) {
          if (status == 'notListening' || status == 'done' || status == 'endOfSpeech') {
            if (_isListening) {
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
          }
        },
        onErrorCallback: (_) {
          if (_isListening) {
            _isListening = false;
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
    service.onOverlayTapped = () {
      if (_continuousVoiceEnabled || _continuousVoiceSearchEnabled) {
        onAppResumed();
      }
    };
  }

  bool _continuousVoiceSearchEnabled = false;
  bool get continuousVoiceSearchEnabled => _continuousVoiceSearchEnabled;

  void setContinuousVoiceSearchEnabled(bool v) {
    _continuousVoiceSearchEnabled = v;
    _prefs.saveContinuousVoiceSearch(v);
    if (v) {
      _startContinuousVoiceService();
    } else {
      _stopContinuousVoiceService();
    }
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

  void onAppResumed() {
    if (kIsWeb) return;
    if (_continuousVoiceEnabled && !_isListening) {
      startVoiceInput();
    }
    if (_continuousVoiceSearchEnabled && !_continuousVoiceService.isRunning) {
      _startContinuousVoiceService();
    }
  }

  void onAppPaused() {
    // On web, speech recognition stops when tab is backgrounded
    // On native, the continuous voice service keeps running via its internal loop
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
      _continuousVoiceSearchEnabled = await _prefs.loadContinuousVoiceSearch();
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
      // Auto-start services after prefs are loaded
      WidgetsBinding.instance.addPostFrameCallback((_) {
        _autoStartServicesFromPrefs();
      });
    } catch (_) {}
  }

  void _autoStartServicesFromPrefs() {
    if (kIsWeb) return;
    if (_continuousVoiceEnabled) {
      startVoiceInput();
    }
    if (_continuousVoiceSearchEnabled) {
      _startContinuousVoiceService();
    }
  }

  void _startContinuousVoiceService() {
    _continuousVoiceService.onCommandRecognized = (text) {
      if (text.isNotEmpty) {
        sendMessage(text);
      }
    };
    _continuousVoiceService.onIntentDetected = (action) {
      final query = action.params['query'];
      if (query != null && query.isNotEmpty) {
        sendMessage(query);
      }
    };
    _continuousVoiceService.start();
  }

  void _stopContinuousVoiceService() {
    _continuousVoiceService.stop();
  }
}
