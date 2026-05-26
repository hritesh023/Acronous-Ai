import 'dart:io' show Platform;
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../constants/app_constants.dart';
import '../providers/auth_provider.dart';
import '../providers/chat_provider.dart';
import 'voice_popup.dart';
import 'voice_command_widget.dart';

class BackgroundAssistant extends StatefulWidget {
  final Widget child;
  final GlobalKey<NavigatorState> navigatorKey;

  const BackgroundAssistant({
    super.key,
    required this.child,
    required this.navigatorKey,
  });

  @override
  State<BackgroundAssistant> createState() => _BackgroundAssistantState();
}

class _BackgroundAssistantState extends State<BackgroundAssistant>
    with SingleTickerProviderStateMixin {
  double _posX = 16;
  double _posY = 0.3;
  bool _isHovered = false;
  bool _isDragging = false;
  late AnimationController _pulseController;

  static const double _buttonSize = 48;
  static const double _edgeSnapThreshold = 40;
  static const double _hiddenStrip = 6;
  static const double _popOutWidth = 56;

  bool get _isDesktop =>
      !kIsWeb && (Platform.isWindows || Platform.isMacOS || Platform.isLinux);

  @override
  void initState() {
    super.initState();
    _pulseController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 2000),
    )..repeat(reverse: true);
  }

  @override
  void dispose() {
    _pulseController.dispose();
    super.dispose();
  }

  void _openVoice() {
    final navContext = widget.navigatorKey.currentContext;
    if (navContext == null) return;
    final chat = navContext.read<ChatProvider>();

    if (_isDesktop) {
      _openVoiceFullScreen(chat, navContext);
    } else {
      _openVoiceSheet(chat, navContext);
    }
  }

  void _openVoiceSheet(ChatProvider chat, BuildContext navContext) {
    showModalBottomSheet(
      context: navContext,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (_) => VoicePopup(
        searchMode: true,
        continuous: chat.continuousVoiceEnabled,
        onResult: (text) {
          if (text.isNotEmpty) {
            chat.sendMessage(text);
          }
        },
      ),
    );
  }

  void _openVoiceFullScreen(ChatProvider chat, BuildContext navContext) {
    Navigator.of(navContext).push(
      PageRouteBuilder(
        pageBuilder: (context, animation, secondaryAnimation) =>
            VoiceCommandWidget(
              onResult: (text) {},
              onIntent: (action) {
                final query = action.params['query'];
                if (query != null && query.isNotEmpty) {
                  chat.sendMessage(query);
                }
              },
              onDismiss: () => Navigator.of(context).pop(),
            ),
        transitionsBuilder: (context, animation, secondaryAnimation, child) {
          return FadeTransition(opacity: animation, child: child);
        },
        opaque: false,
        barrierDismissible: true,
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final size = MediaQuery.of(context).size;

    return Consumer2<ChatProvider, AuthProvider>(
      builder: (context, chat, auth, _) {
        if (!chat.backgroundAssistantEnabled ||
            auth.status != AuthStatus.authenticated) {
          return widget.child;
        }

        final posY = _posY.clamp(0.05, 0.85);
        final isNearRightEdge =
            _posX > size.width - _buttonSize - _edgeSnapThreshold;
        final isSnapped = isNearRightEdge && !_isHovered && !_isDragging;
        final double displayX = isSnapped
            ? size.width - _hiddenStrip
            : _posX.clamp(0, size.width - _popOutWidth).toDouble();
        final double snappedOpacity = isSnapped ? 0.35 : 1.0;

        final iconWidget = AnimatedBuilder(
          animation: _pulseController,
          builder: (context, child) {
            final pulse = 0.92 + 0.08 * _pulseController.value;
            final scale = isSnapped ? 0.85 : (_isHovered ? 1.1 : pulse);
            return Transform.scale(
              scale: scale,
              child: AnimatedOpacity(
                duration: const Duration(milliseconds: 300),
                opacity: snappedOpacity,
                child: Container(
                  width: _buttonSize,
                  height: _buttonSize,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    gradient: LinearGradient(
                      colors: [cs.primary, cs.primary.withValues(alpha: 0.8)],
                      begin: Alignment.topLeft,
                      end: Alignment.bottomRight,
                    ),
                    boxShadow: isSnapped
                        ? []
                        : [
                            BoxShadow(
                              color: cs.primary.withValues(alpha: 0.4),
                              blurRadius: 12,
                              spreadRadius: 1,
                            ),
                            BoxShadow(
                              color: cs.primary.withValues(alpha: 0.2),
                              blurRadius: 24,
                              offset: const Offset(0, 4),
                            ),
                          ],
                  ),
                  child: ClipRRect(
                    borderRadius: BorderRadius.circular(_buttonSize / 2),
                    child: isSnapped
                        ? Icon(Icons.mic_rounded, color: cs.onPrimary, size: 18)
                        : Image.asset(
                            'assets/Acronous_Ai_svj_logo.png',
                            width: _buttonSize * 0.65,
                            height: _buttonSize * 0.65,
                            fit: BoxFit.contain,
                            errorBuilder: (_, _, _) => Icon(
                              Icons.auto_awesome_rounded,
                              color: cs.onPrimary,
                              size: AppDimens.assistantIconSize,
                            ),
                          ),
                  ),
                ),
              ),
            );
          },
        );

        Widget draggableIcon = GestureDetector(
          onPanStart: (_) => setState(() => _isDragging = true),
          onPanEnd: (_) {
            setState(() => _isDragging = false);
            if (_posX > size.width - _buttonSize - _edgeSnapThreshold) {
              setState(() => _posX = size.width - _hiddenStrip);
            }
          },
          onPanUpdate: (details) {
            setState(() {
              _posY = (posY + details.delta.dy / size.height).clamp(0.05, 0.85);
              _posX = (_posX + details.delta.dx).clamp(
                0,
                size.width - _hiddenStrip,
              );
            });
          },
          onTap: () => _openVoice(),
          child: iconWidget,
        );

        if (_isDesktop) {
          draggableIcon = MouseRegion(
            cursor: SystemMouseCursors.click,
            onEnter: (_) => setState(() => _isHovered = true),
            onExit: (_) => setState(() => _isHovered = false),
            child: draggableIcon,
          );
        }

        return Stack(
          children: [
            widget.child,
            Positioned(
              left: displayX,
              top: size.height * posY,
              child: draggableIcon,
            ),
          ],
        );
      },
    );
  }
}
