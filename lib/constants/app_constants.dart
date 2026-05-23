class AppDimens {
  AppDimens._();

  static const double avatarSize = 26;
  static const double avatarSizeLarge = 72;
  static const double avatarSizeSidebar = 30;
  static const double avatarRadius = 7;
  static const double avatarRadiusLarge = 18;
  static const double avatarRadiusSidebar = 8;

  static const double bubbleRadius = 18;
  static const double bubbleRadiusSmall = 4;
  static const double bubbleMinPaddingH = 14;
  static const double bubbleMinPaddingV = 9;

  static const double inputBarRadius = 14;
  static const double inputIconSize = 34;
  static const double inputIconInnerSize = 20;
  static const double inputPaddingH = 8;
  static const double inputPaddingB = 6;

  static const double assistantButtonSize = 48;
  static const double assistantIconSize = 22;

  static const double sidebarItemRadius = 8;
  static const double cardRadius = 16;
  static const double sheetRadius = 24;

  static const double iconSmall = 14;
  static const double iconMed = 18;
  static const double iconLarge = 20;
  static const double fontSizeXS = 10;
  static const double fontSizeSM = 11;
  static const double fontSizeMD = 12;
  static const double fontSizeLG = 13;
  static const double fontSizeBase = 14;
  static const double fontSizeBody = 14.5;
  static const double fontSizeTitle = 16;
  static const double fontSizeHeading = 17;

  static const double paddingXS = 3;
  static const double paddingSM = 6;
  static const double paddingMD = 8;
  static const double paddingLG = 12;
  static const double paddingXL = 16;
  static const double paddingXXL = 24;

  static const double gapXS = 2;
  static const double gapSM = 4;
  static const double gapMD = 6;
  static const double gapLG = 8;
  static const double gapXL = 10;
  static const double gapXXL = 12;

  static const double maxBubbleWidthRatio = 0.72;
  static const double maxBubbleWidthRatioAI = 0.68;
}

class AppStrings {
  AppStrings._();

  static const String appName = 'Acronous AI';
  static const String newChat = 'New Chat';
  static const String searchHistory = 'Search history...';
  static const String noConversations = 'No conversations yet';
  static const String noMatching = 'No matching conversations';
  static const String messageHint = 'Message Acronous AI...';
  static const String welcomeTitle = 'How can I help you?';
  static const String welcomeSubtitle = 'Ask me anything or try one of these';

  static const String copied = 'Copied';
  static const String deleteTitle = 'Delete conversation?';
  static const String deleteBody = 'This cannot be undone.';
  static const String cancel = 'Cancel';
  static const String delete = 'Delete';

  static const String listening = 'Listening...';
  static const String tapToSpeak = 'Tap to speak';
  static const String speakNow = 'Speak now...';
  static const String tapMic = 'Tap the mic to start';
  static const String send = 'Send';

  static const String today = 'Today';
  static const String yesterday = 'Yesterday';
  static const String thisWeek = 'Earlier this week';
  static const String thisMonth = 'This month';
  static const String earlier = 'Earlier';

  static const String settings = 'Settings';
  static const String assistant = 'Assistant';
  static const String permissions = 'Permissions';
  static const String about = 'About';
  static const String appearance = 'Appearance';
  static const String theme = 'Theme';
  static const String light = 'Light';
  static const String dark = 'Dark';
  static const String system = 'System';

  static const String backgroundAssistant = 'Background Assistant';
  static const String backgroundAssistantSub = 'Floating quick-access button';

  static const String microphone = 'Microphone';
  static const String microphoneSub = 'Voice input & commands';
  static const String camera = 'Camera';
  static const String cameraSub = 'Image analysis & capture';
  static const String storage = 'Storage';
  static const String storageSub = 'File attachments & saving';
  static const String granted = 'Granted';

  static const String poweredBy = 'Powered by';
  static const String poweredBySub = 'Flutter + Python AI Engine';
  static const String version = 'Version';

  static const String connectionError = 'I\'m having trouble connecting. Please make sure the server is running.';

  static const String cameraBtn = 'Camera';
  static const String galleryBtn = 'Gallery';
  static const String filesBtn = 'Files';
  static const String analyzeBtn = 'Analyze';
  static const String voiceBtn = 'Voice';
  static const String closeBtn = 'Close';
  static const String analyzeImage = 'Analyze Image';
  static const String takePhoto = 'Take Photo';
  static const String captureWithCamera = 'Capture with camera for analysis';
  static const String chooseFromGallery = 'Choose from Gallery';
  static const String selectFromGallery = 'Select existing image for analysis';
  static const String analysisError = 'Analysis error';

  static List<String> welcomeSuggestions = const [
    'What can you help me with?',
    'Write a poem about AI',
    'Explain machine learning simply',
    'Help me debug my code',
  ];
}

class AppPrefKeys {
  AppPrefKeys._();

  static const String themeMode = 'theme_mode';
  static const String ttsSpeed = 'tts_speed';
  static const String ttsPitch = 'tts_pitch';
  static const String continuousVoice = 'continuous_voice';
  static const String autoSendVoice = 'auto_send_voice';
  static const String backgroundAssistant = 'background_assistant';
  static const String continuousVoiceSearch = 'continuous_voice_search';
  static const String systemOverlay = 'system_overlay';
  static const String overlayPermissionGranted = 'overlay_permission_granted';
  static const String conversations = 'conversations';
}

class AppColorValues {
  AppColorValues._();

  static const int seedHex = 0xFF6C5CE7;
  static const int lightBgHex = 0xFFF2F2F7;
  static const int darkBgHex = 0xFF0E0E12;
  static const int lightCardHex = 0xFFFFFFFF;
  static const int darkCardHex = 0xFF1C1C1E;
  static const int lightFgHex = 0xFF1A1A1A;
  static const int darkFgHex = 0xFFE8E8ED;
}
