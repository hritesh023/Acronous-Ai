import 'dart:io';

class AppConfig {
  AppConfig._();

  static final AppConfig instance = AppConfig._();

  late final String apiBaseUrl;
  late final Duration apiChatTimeout;
  late final Duration apiImageTimeout;
  late final Duration apiFileTimeout;
  late final Duration apiImageGenTimeout;
  late final String apiChatPath;
  late final String apiImageChatPath;
  late final String apiFilePath;
  late final String apiImageGeneratePath;
  late final String apiImageEditPath;

  late final String appTitle;
  late final String appVersion;

  late final double imagePickerMaxWidth;
  late final double imagePickerMaxHeight;
  late final int imagePickerQuality;
  late final double imageMaxDimension;

  late final Duration speechListenDuration;
  late final Duration speechPauseDuration;
  late final String speechLocale;
  late final bool speechPartialResults;

  late final String ttsLanguage;
  late final double ttsDefaultSpeed;
  late final double ttsDefaultPitch;

  late final List<String> allowedFileExtensions;

  late final int conversationTitleMaxLength;

  late final String defaultSessionId;
  late final String cameraAnalysisPrompt;

  late final String settingsRoute;

  void load() {
    apiBaseUrl = _env('API_BASE_URL', 'http://localhost:8000');
    apiChatTimeout = Duration(seconds: _envInt('API_CHAT_TIMEOUT', 0));
    apiImageTimeout = Duration(seconds: _envInt('API_IMAGE_TIMEOUT', 0));
    apiFileTimeout = Duration(seconds: _envInt('API_FILE_TIMEOUT', 0));
    apiImageGenTimeout = Duration(seconds: _envInt('API_IMAGE_GEN_TIMEOUT', 0));
    apiChatPath = '/v1/chat';
    apiImageChatPath = '/v1/chat/image';
    apiFilePath = '/v1/chat/file';
    apiImageGeneratePath = '/v1/image/generate';
    apiImageEditPath = '/v1/image/edit';

    appTitle = 'Acronous AI';
    appVersion = _env('APP_VERSION', '1.1.0');

    imagePickerMaxWidth = _envDouble('IMAGE_MAX_WIDTH', 1920);
    imagePickerMaxHeight = _envDouble('IMAGE_MAX_HEIGHT', 1920);
    imagePickerQuality = _envInt('IMAGE_QUALITY', 85);
    imageMaxDimension = _envDouble('IMAGE_MAX_DIMENSION', 1920);

    speechListenDuration =
        Duration(seconds: _envInt('SPEECH_LISTEN_SECONDS', 60));
    speechPauseDuration = Duration(seconds: _envInt('SPEECH_PAUSE_SECONDS', 3));
    speechLocale = _env('SPEECH_LOCALE', 'en_US');
    speechPartialResults = true;

    ttsLanguage = _env('TTS_LANGUAGE', 'en-US');
    ttsDefaultSpeed = _envDouble('TTS_DEFAULT_SPEED', 0.5);
    ttsDefaultPitch = _envDouble('TTS_DEFAULT_PITCH', 1.0);

    allowedFileExtensions = [
      'txt', 'pdf', 'doc', 'docx', 'odt', 'rtf',
      'csv', 'json', 'xml', 'yaml', 'yml', 'toml', 'ini', 'cfg',
      'md', 'log',
      'py', 'js', 'ts', 'jsx', 'tsx', 'html', 'css', 'scss', 'sass',
      'dart', 'go', 'rs', 'rb', 'php', 'java', 'cpp', 'c', 'h', 'hpp',
      'swift', 'kt', 'scala', 'pl', 'lua', 'r', 'sql', 'sh', 'bat', 'ps1',
      'mp3', 'wav', 'ogg', 'aac', 'flac',
      'mp4', 'avi', 'mkv', 'mov', 'webm',
      'zip', 'tar', 'gz', 'rar', '7z',
      'png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp', 'svg',
    ];

    conversationTitleMaxLength = 50;

    defaultSessionId = 'default';
    cameraAnalysisPrompt = _env('CAMERA_ANALYSIS_PROMPT', '');

    settingsRoute = '/settings';
  }

  static String _env(String key, String fallback) {
    try {
      return Platform.environment[key] ?? fallback;
    } catch (_) {
      return fallback;
    }
  }

  static int _envInt(String key, int fallback) {
    try {
      final v = Platform.environment[key];
      return v != null ? int.tryParse(v) ?? fallback : fallback;
    } catch (_) {
      return fallback;
    }
  }

  static double _envDouble(String key, double fallback) {
    try {
      final v = Platform.environment[key];
      return v != null ? double.tryParse(v) ?? fallback : fallback;
    } catch (_) {
      return fallback;
    }
  }
}
