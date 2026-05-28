import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/auth_provider.dart';
import '../providers/chat_provider.dart';
import '../models/message.dart';
import '../models/suggestion.dart';

import '../widgets/chat_input.dart';
import '../widgets/chat_message.dart';
import '../widgets/sidebar.dart';
import 'auth_page.dart';

class ChatPage extends StatefulWidget {
  final ChatProvider chatProvider;
  final AuthProvider authProvider;

  const ChatPage({
    super.key,
    required this.chatProvider,
    required this.authProvider,
  });

  @override
  State<ChatPage> createState() => _ChatPageState();
}

class _ChatPageState extends State<ChatPage> {
  bool _sidebarOpen = false;
  final _scrollController = ScrollController();
  List<Suggestion> _suggestions = [];

  @override
  void initState() {
    super.initState();
    _loadConfig();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      widget.chatProvider.loadTheme();
      if (widget.authProvider.status == AuthStatus.authenticated) {
        widget.chatProvider.loadServerConversations();
      }
    });
    widget.authProvider.addListener(_onAuthChanged);
  }

  @override
  void dispose() {
    widget.authProvider.removeListener(_onAuthChanged);
    _scrollController.dispose();
    super.dispose();
  }

  void _onAuthChanged() {
    if (widget.authProvider.status == AuthStatus.unauthenticated && mounted) {
      Navigator.of(context).pushAndRemoveUntil(
        MaterialPageRoute(builder: (_) => const AuthPage()),
        (route) => false,
      );
    }
  }

  Future<void> _loadConfig() async {
    try {
      final config = await widget.chatProvider.apiClient.getConfig();
      final list = config['suggestions'] as List? ?? [];
      if (list.isNotEmpty) {
        setState(() => _suggestions = list.map((e) => Suggestion.fromJson(e as Map<String, dynamic>)).toList());
        return;
      }
    } catch (_) {}
    _setDefaultSuggestions();
  }

  void _setDefaultSuggestions() {
    if (_suggestions.isNotEmpty) return;
    setState(() => _suggestions = [
      Suggestion(icon: 'book', title: 'Learn Something', desc: 'Explain ML simply', query: 'Explain machine learning in simple terms'),
      Suggestion(icon: 'code', title: 'Write Code', desc: 'Create a Python script', query: 'Write a Python script that scrapes a website'),
      Suggestion(icon: 'image', title: 'Generate Art', desc: 'Draw a landscape', query: 'Draw a serene mountain landscape at sunset'),
      Suggestion(icon: 'search', title: 'Research', desc: 'Latest AI news', query: 'What are the latest developments in artificial intelligence?'),
    ]);
  }

  @override
  Widget build(BuildContext context) {
    final isDark = widget.chatProvider.themeMode == ThemeMode.dark ||
        (widget.chatProvider.themeMode == ThemeMode.system &&
            MediaQuery.of(context).platformBrightness == Brightness.dark);

    return Theme(
      data: isDark ? _buildDarkTheme() : _buildLightTheme(),
      child: Scaffold(
        body: Stack(
          clipBehavior: Clip.hardEdge,
          children: [
            Column(
              children: [
                _buildTopBar(context),
                Expanded(
                  child: Consumer<ChatProvider>(
                    builder: (context, chat, _) {
                      final msgs = chat.currentMessages;
                      WidgetsBinding.instance.addPostFrameCallback((_) {
                        if (_scrollController.hasClients) {
                          _scrollController.animateTo(
                            _scrollController.position.maxScrollExtent,
                            duration: const Duration(milliseconds: 200),
                            curve: Curves.easeOut,
                          );
                        }
                      });
                      return msgs.isEmpty
                          ? _buildWelcomeScreen(context)
                          : _buildMessagesList(context, msgs, chat);
                    },
                  ),
                ),
                _buildInputArea(context),
                if (widget.chatProvider.error != null)
                  _buildErrorToast(widget.chatProvider.error!),
              ],
            ),
            if (_sidebarOpen)
              GestureDetector(
                onTap: () => setState(() => _sidebarOpen = false),
                child: Container(color: Colors.black54),
              ),
            if (_sidebarOpen)
              Positioned(
                left: 0,
                top: 0,
                bottom: 0,
                child: SidebarWidget(
                  chatProvider: widget.chatProvider,
                  authProvider: widget.authProvider,
                  topics: _suggestions,
                  onClose: () => setState(() => _sidebarOpen = false),
                ),
              ),
          ],
        ),
      ),
    );
  }

  Widget _buildTopBar(BuildContext context) {
    return Container(
      padding: EdgeInsets.only(
        top: MediaQuery.of(context).padding.top + 8,
        left: 12,
        right: 12,
        bottom: 8,
      ),
      child: Row(
        children: [
          Material(
            color: Colors.transparent,
            child: InkWell(
              onTap: () => setState(() => _sidebarOpen = !_sidebarOpen),
              borderRadius: BorderRadius.circular(10),
              child: SizedBox(
                width: 34,
                height: 34,
                child: const Icon(Icons.menu,
                    size: 18, color: Color(0xFFB0B0C8)),
              ),
            ),
          ),
          const SizedBox(width: 8),
          const Spacer(),
          Material(
            color: Colors.transparent,
            child: InkWell(
              onTap: () => widget.chatProvider.toggleTheme(),
              borderRadius: BorderRadius.circular(10),
              child: SizedBox(
                width: 34,
                height: 34,
                child: Icon(
                  widget.chatProvider.themeMode == ThemeMode.dark
                      ? Icons.light_mode
                      : Icons.dark_mode,
                  size: 18,
                  color: const Color(0xFFB0B0C8),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildWelcomeScreen(BuildContext context) {
    return Center(
      child: SingleChildScrollView(
        child: Padding(
          padding: const EdgeInsets.only(bottom: 180),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            mainAxisSize: MainAxisSize.min,
            children: [
            ClipRRect(
              borderRadius: BorderRadius.circular(14),
              child: Image.asset(
                'assets/logo.png',
                width: 52,
                height: 52,
                errorBuilder: (_, _, _) => Container(
                  width: 52,
                  height: 52,
                  decoration: BoxDecoration(
                    color: const Color(0xFF7C3AED),
                    borderRadius: BorderRadius.circular(14),
                  ),
                ),
              ),
            ),
            const SizedBox(height: 20),
            const Text(
              'How can I help you today?',
              style: TextStyle(
                fontSize: 20,
                fontWeight: FontWeight.w700,
                color: Color(0xFFE8E8F0),
              ),
            ),
            const SizedBox(height: 6),
            const Text(
              'Ask me anything, I\'m here to assist',
              style: TextStyle(
                fontSize: 15,
                color: Color(0xFF707090),
              ),
            ),
            const SizedBox(height: 28),
            if (_suggestions.isNotEmpty)
              Wrap(
                spacing: 8,
                runSpacing: 8,
                alignment: WrapAlignment.center,
                children: _suggestions.map((s) {
                  return Material(
                    color: const Color(0xFF181830),
                    borderRadius: BorderRadius.circular(14),
                    child: InkWell(
                      onTap: () => widget.chatProvider.handleSendMessage(
                          s.query),
                      borderRadius: BorderRadius.circular(14),
                      child: Container(
                        width: 200,
                        padding: const EdgeInsets.all(14),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Icon(
                              _iconFor(s.icon),
                              size: 20,
                              color: const Color(0xFF7C3AED),
                            ),
                            const SizedBox(height: 6),
                            Text(s.title,
                                style: const TextStyle(
                                    fontSize: 13,
                                    fontWeight: FontWeight.w600,
                                    color: Color(0xFFE8E8F0))),
                            const SizedBox(height: 2),
                            Text(s.desc,
                                style: const TextStyle(
                                    fontSize: 11,
                                    color: Color(0xFF707090))),
                          ],
                        ),
                      ),
                    ),
                  );
                }).toList(),
              ),
           ],
         ),
       ),
        ),
     );
   }

    Widget _buildMessagesList(
       BuildContext context, List<ChatMessage> messages, ChatProvider chat) {
     return ListView.builder(
       key: const ValueKey('messages_list'),
       controller: _scrollController,
       padding: const EdgeInsets.fromLTRB(16, 24, 16, 200),
       itemCount: messages.length + (chat.isLoading ? 1 : 0),
      itemBuilder: (context, index) {
        if (index == messages.length) {
          return Padding(
            padding: const EdgeInsets.all(12),
            child: Row(
              children: [
                 _TypingIndicator(
                   isTakingLong: chat.isTakingLong,
                 ),
              ],
            ),
          );
        }
        return ChatMessageWidget(
          message: messages[index],
        );
      },
    );
  }

  Widget _buildInputArea(BuildContext context) {
    return Align(
      alignment: Alignment.bottomCenter,
      key: const ValueKey('input_area'),
      child: Container(
        width: double.infinity,
        constraints: const BoxConstraints(maxWidth: 720),
        padding: const EdgeInsets.fromLTRB(16, 0, 16, 20),
        child: const ChatInput(key: ValueKey('chat_input')),
      ),
    );
  }

  Widget _buildErrorToast(String error) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 0),
      child: Material(
        color: const Color(0xFFEF4444),
        borderRadius: BorderRadius.circular(12),
        elevation: 8,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
          child: Row(
            children: [
              Expanded(
                child: Text(
                  error,
                  style: const TextStyle(color: Colors.white, fontSize: 14),
                ),
              ),
              GestureDetector(
                onTap: () => widget.chatProvider.setError(null),
                child: const Icon(Icons.close,
                    size: 18, color: Colors.white),
              ),
            ],
          ),
        ),
      ),
    );
  }

  ThemeData _buildDarkTheme() {
    return ThemeData(
      useMaterial3: true,
      brightness: Brightness.dark,
      scaffoldBackgroundColor: const Color(0xFF0F0F1A),
      primaryColor: const Color(0xFF7C3AED),
      colorScheme: const ColorScheme.dark(
        primary: Color(0xFF7C3AED),
        secondary: Color(0xFF8B5CF6),
        surface: Color(0xFF16162A),
        error: Color(0xFFEF4444),
      ),
      cardColor: const Color(0xFF181830),
      dividerColor: const Color(0x14FFFFFF),
      textTheme: const TextTheme(
        bodyLarge: TextStyle(color: Color(0xFFE8E8F0)),
        bodyMedium: TextStyle(color: Color(0xFFB0B0C8)),
        bodySmall: TextStyle(color: Color(0xFF707090)),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: const Color(0xFF1C1C35),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(10),
          borderSide: const BorderSide(color: Color(0x1FFFFFFF)),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(10),
          borderSide: const BorderSide(color: Color(0x1FFFFFFF)),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(10),
          borderSide: const BorderSide(color: Color(0xFF7C3AED), width: 2),
        ),
        hintStyle: const TextStyle(color: Color(0xFF505070)),
      ),
    );
  }

  ThemeData _buildLightTheme() {
    return ThemeData(
      useMaterial3: true,
      brightness: Brightness.light,
      scaffoldBackgroundColor: const Color(0xFFF5F5FA),
      primaryColor: const Color(0xFF7C3AED),
      colorScheme: const ColorScheme.light(
        primary: Color(0xFF7C3AED),
        secondary: Color(0xFF6D28D9),
        surface: Colors.white,
        error: Color(0xFFEF4444),
      ),
      cardColor: Colors.white,
      dividerColor: const Color(0x14000000),
      textTheme: const TextTheme(
        bodyLarge: TextStyle(color: Color(0xFF1A1A2A)),
        bodyMedium: TextStyle(color: Color(0xFF4A4A60)),
        bodySmall: TextStyle(color: Color(0xFF7A7A90)),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: Colors.white,
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(10),
          borderSide: const BorderSide(color: Color(0x14000000)),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(10),
          borderSide: const BorderSide(color: Color(0x14000000)),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(10),
          borderSide: const BorderSide(color: Color(0xFF7C3AED), width: 2),
        ),
        hintStyle: const TextStyle(color: Color(0xFFA0A0B0)),
      ),
    );
  }

  IconData _iconFor(String icon) {
    switch (icon) {
      case 'book':
        return Icons.book;
      case 'code':
        return Icons.code;
      case 'image':
        return Icons.image;
      default:
        return Icons.search;
    }
  }
}

class _TypingIndicator extends StatefulWidget {
  final bool isTakingLong;

  const _TypingIndicator({this.isTakingLong = false});

  @override
  State<_TypingIndicator> createState() => _TypingIndicatorState();
}

class _TypingIndicatorState extends State<_TypingIndicator>
    with SingleTickerProviderStateMixin {
  late AnimationController _controller;
  late List<Animation<double>> _animations;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1200),
    )..repeat();
    _animations = List.generate(3, (i) {
      return Tween<double>(begin: 0.3, end: 1.0).animate(
        CurvedAnimation(
          parent: _controller,
          curve: Interval(i * 0.2, 0.6 + i * 0.2, curve: Curves.easeInOut),
        ),
      );
    });
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: cs.brightness == Brightness.dark
                ? const Color(0xFF1A1A30)
                : Colors.white,
            borderRadius: BorderRadius.circular(16),
            border: Border.all(color: const Color(0x14FFFFFF)),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: List.generate(3, (index) {
              return Padding(
                padding: const EdgeInsets.symmetric(horizontal: 2),
                child: AnimatedBuilder(
                  animation: _animations[index],
                  builder: (context, child) {
                    return Opacity(
                      opacity: _animations[index].value,
                      child: Container(
                        width: 7,
                        height: 7,
                        decoration: const BoxDecoration(
                          color: Color(0xFF707090),
                          shape: BoxShape.circle,
                        ),
                      ),
                    );
                  },
                ),
              );
            }),
          ),
        ),
        if (widget.isTakingLong)
          Padding(
            padding: const EdgeInsets.only(top: 8, left: 4),
            child: Text(
              'Still working on it…',
              style: TextStyle(
                fontSize: 12,
                color: cs.onSurfaceVariant.withValues(alpha: 0.7),
              ),
            ),
          ),
      ],
    );
  }
}
