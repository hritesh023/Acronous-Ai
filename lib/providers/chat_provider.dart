import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'package:url_launcher/url_launcher.dart';
import '../api/client.dart';
import '../config/app_config.dart';
import '../constants/app_constants.dart';
import '../models/message.dart';
import '../services/file_service.dart';
import '../services/preferences_service.dart';
import '../services/speech_service.dart';
import '../services/tts_service.dart';
import '../services/intent_processor.dart';
import '../services/continuous_voice_service.dart';
import '../services/overlay_service.dart';
import '../widgets/camera_screen.dart';

class ChatProvider extends ChangeNotifier {
  final ApiClient _api;
  final PreferencesService _prefs;
  final FileService _fileService;
  final SpeechService _speech;
  final TtsService _tts;
  final ContinuousVoiceService _continuousVoice;
  final OverlayService _overlayService;

  final List<Conversation> _conversations = [];
  Conversation? _currentConversation;
  bool _isLoading = false;
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
  bool _continuousVoiceEnabled = false;
  bool _backgroundAssistantEnabled = false;
  bool _continuousVoiceSearchEnabled = false;
  bool _systemOverlayEnabled = false;

  ChatProvider({
    ApiClient? api,
    PreferencesService? prefs,
    FileService? fileService,
    SpeechService? speech,
    TtsService? tts,
    ContinuousVoiceService? continuousVoice,
    OverlayService? overlayService,
  })  : _api = api ?? ApiClient(),
        _prefs = prefs ?? PreferencesService(),
        _fileService = fileService ?? FileService(),
        _speech = speech ?? SpeechService(),
        _tts = tts ?? TtsService(),
        _continuousVoice = continuousVoice ?? ContinuousVoiceService(),
        _overlayService = overlayService ?? OverlayService() {
    _init();
  }

  Future<void> _init() async {
    await _loadPrefs();
    await _initTts();
    await _overlayService.initialize();
    _continuousVoice.addListener(_onContinuousVoiceChanged);
    _continuousVoice.onIntentDetected = _onContinuousIntent;
    _newConversation();
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
  bool get continuousVoiceSearchEnabled => _continuousVoiceSearchEnabled;
  bool get systemOverlayEnabled => _systemOverlayEnabled;
  OverlayService get overlayService => _overlayService;
  ContinuousVoiceService get continuousVoiceService => _continuousVoice;

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
      _themeMode =
          _themeMode == ThemeMode.dark ? ThemeMode.light : ThemeMode.dark;
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
    _prefs.saveConversations(_conversations);
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

  void setContinuousVoiceSearchEnabled(bool v) {
    _continuousVoiceSearchEnabled = v;
    _prefs.saveContinuousVoiceSearch(v);
    if (v) {
      _continuousVoice.start();
    } else {
      _continuousVoice.stop();
    }
    notifyListeners();
  }

  void setSystemOverlayEnabled(bool v) {
    _systemOverlayEnabled = v;
    _prefs.saveSystemOverlay(v);
    if (v && _overlayService.supportsSystemOverlay) {
      if (!_overlayService.systemOverlayPermissionGranted) {
        _overlayService.requestOverlayPermission();
      }
      _overlayService.showSystemOverlay();
    } else {
      _overlayService.hideSystemOverlay();
    }
    notifyListeners();
  }

  void _onContinuousVoiceChanged() {
    notifyListeners();
  }

  void _onContinuousIntent(IntentAction action) {
    executeIntent(action);
  }

  Future<void> executeIntent(IntentAction action) async {
    switch (action.type) {
      case IntentType.call:
        final contact = action.params['contact']!;
        final uri = Uri.parse('tel:${Uri.encodeComponent(contact)}');
        if (await canLaunchUrl(uri)) {
          await launchUrl(uri);
        } else {
          sendMessage('Call $contact');
        }
      case IntentType.openLink:
        final url = action.params['url']!;
        final uri = Uri.parse(url);
        if (await canLaunchUrl(uri)) {
          await launchUrl(uri, mode: LaunchMode.externalApplication);
        } else {
          sendMessage(url);
        }
      case IntentType.openApp:
        final target = action.params['target']!;
        final appUri = Uri.parse('$target://');
        if (await canLaunchUrl(appUri)) {
          await launchUrl(appUri, mode: LaunchMode.externalApplication);
        } else {
          sendMessage('Open $target');
        }
      case IntentType.sendMessage:
        final contact = action.params['contact']!;
        final message = action.params['message'] ?? '';
        if (RegExp(r'^\+?[\d\s\-\(\)]{7,}$').hasMatch(contact)) {
          final uri = Uri.parse(
            'sms:$contact${message.isNotEmpty ? '?body=${Uri.encodeComponent(message)}' : ''}',
          );
          if (await canLaunchUrl(uri)) {
            await launchUrl(uri);
          } else {
            sendMessage('Send message to $contact: $message');
          }
        } else {
          sendMessage('Send message to $contact${message.isNotEmpty ? ': $message' : ''}');
        }
      case IntentType.sendWhatsApp:
        final contact = action.params['contact']!;
        final message = action.params['message'] ?? '';
        final uri = Uri.parse(
          'https://wa.me/${Uri.encodeComponent(contact)}?text=${Uri.encodeComponent(message)}',
        );
        if (await canLaunchUrl(uri)) {
          await launchUrl(uri, mode: LaunchMode.externalApplication);
        } else {
          sendMessage('Send WhatsApp to $contact: $message');
        }
      case IntentType.search:
        final query = action.params['query']!;
        final uri = Uri.parse(
          'https://www.google.com/search?q=${Uri.encodeComponent(query)}',
        );
        if (await canLaunchUrl(uri)) {
          await launchUrl(uri, mode: LaunchMode.externalApplication);
        } else {
          sendMessage(query);
        }
      case IntentType.aiQuery:
        sendMessage(action.params['query']!);
    }
  }

  Future<void> sendMessage(String text) async {
    if (text.trim().isEmpty && _pendingAttachments.isEmpty) return;

    _isLoading = true;
    notifyListeners();

    final userMsg = ChatMessage(
      role: 'user',
      content: text,
      attachments: List.from(_pendingAttachments),
    );
    _currentConversation?.messages.add(userMsg);
    _currentConversation?.updatedAt = DateTime.now();
    _pendingAttachments.clear();
    notifyListeners();

    try {
      final resp = await _callApi(userMsg, text);
      final imageData = resp['image_data'] as String? ?? '';
      final assistantMsg = ChatMessage(
        role: 'assistant',
        content: resp['response'] as String? ?? '',
        imageData: imageData,
      );
      _currentConversation?.messages.add(assistantMsg);
    } catch (e) {
      final msg = _shouldShowConnectionError(e)
          ? AppStrings.connectionError
          : e.toString();
      _currentConversation?.messages
          .add(ChatMessage(role: 'assistant', content: msg));
    }

    _isLoading = false;
    _prefs.saveConversations(_conversations);
    notifyListeners();
  }

  bool _isImageGenRequest(String text) {
    final t = text.trim().toLowerCase();
    if (t.length < 4) return false;
    final prefixes = ['draw ', 'paint ', 'sketch ', 'generate ', 'create '];
    for (final p in prefixes) {
      if (t.startsWith(p)) return true;
    }
    final patterns = [
      'generate an image', 'generate a picture', 'generate a photo',
      'create an image', 'create a picture', 'create a photo',
      'make an image', 'make a picture', 'make a photo',
      'generate image of', 'generate picture of',
      'create image of', 'create picture of',
      'image of a', 'image of an', 'picture of a', 'picture of an',
      'draw me a', 'draw me an', 'paint me a',
    ];
    for (final pat in patterns) {
      if (t.contains(pat)) return true;
    }
    return false;
  }

  Future<Map<String, dynamic>> _callApi(
      ChatMessage userMsg, String text) async {
    final hasImage =
        userMsg.attachments.any((a) => a.type == AttachmentType.image);
    final sessionId = _currentConversation?.id;

    if (hasImage) {
      final imgAttach =
          userMsg.attachments.firstWhere((a) => a.type == AttachmentType.image);
      final bytes = await FileService.readAttachmentBytes(imgAttach);
      return _api.chatWithImage(
        message: text,
        imageBytes: bytes,
        fileName: imgAttach.name,
        sessionId: sessionId,
      );
    } else if (userMsg.attachments.isNotEmpty) {
      final attach = userMsg.attachments.first;
      final bytes = await FileService.readAttachmentBytes(attach);
      return _api.uploadFile(
        fileBytes: bytes,
        fileName: attach.name,
        message: text,
        sessionId: sessionId,
      );
    }
    if (_isImageGenRequest(text)) {
      return _api.generateImage(prompt: text, sessionId: sessionId);
    }
    return _api.chat(message: text, sessionId: sessionId);
  }

  bool _shouldShowConnectionError(Object e) {
    final msg = e.toString();
    return msg.contains('Connection refused') ||
        msg.contains('SocketException') ||
        msg.contains('Failed to fetch') ||
        msg.contains('ClientException');
  }

  Future<void> pickImageForAnalysis(BuildContext context) async {
    try {
      final attachment = await _fileService.pickImageFromGallery();
      if (attachment != null) {
        _pendingAttachments.add(attachment);
        notifyListeners();
        await sendMessage(AppConfig.instance.cameraAnalysisPrompt);
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
      final imagePath = await Navigator.push<String>(
        context,
        MaterialPageRoute(builder: (_) => const CameraScreen()),
      );
      if (imagePath == null) return;
      final attachment = MessageAttachment(
        name: 'camera_${DateTime.now().millisecondsSinceEpoch}.jpg',
        path: imagePath,
        type: AttachmentType.image,
      );
      _pendingAttachments.add(attachment);
      notifyListeners();
      await sendMessage(AppConfig.instance.cameraAnalysisPrompt);
    } catch (e) {
      debugPrint('Camera plugin unavailable, trying ImagePicker: $e');
      try {
        final image = await _fileService.pickImageFromCamera();
        if (image == null) return;
        _pendingAttachments.add(image);
        notifyListeners();
        await sendMessage(AppConfig.instance.cameraAnalysisPrompt);
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

  Future<void> startVoiceInput() async {
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
  }

  void stopVoiceInput() {
    _speech.stopListening();
    _isListening = false;
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
          final imagePath = await Navigator.push<String>(
            context,
            MaterialPageRoute(builder: (_) => const CameraScreen()),
          );
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
        await sendMessage(AppConfig.instance.cameraAnalysisPrompt);
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

  Future<void> _loadPrefs() async {
    try {
      _themeMode = await _prefs.loadThemeMode();
      _ttsSpeed = await _prefs.loadTtsSpeed();
      _ttsPitch = await _prefs.loadTtsPitch();
      _continuousVoiceEnabled = await _prefs.loadContinuousVoice();
      _autoSendVoice = await _prefs.loadAutoSendVoice();
      _backgroundAssistantEnabled = await _prefs.loadBackgroundAssistant();
      _continuousVoiceSearchEnabled = await _prefs.loadContinuousVoiceSearch();
      _systemOverlayEnabled = await _prefs.loadSystemOverlay();
      final loaded = await _prefs.loadConversations();
      _conversations.addAll(loaded);
      if (_conversations.isNotEmpty) {
        _currentConversation = _conversations.first;
      }
      notifyListeners();
    } catch (_) {}
  }
}
