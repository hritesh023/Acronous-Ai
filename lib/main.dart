import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'config/app_config.dart';
import 'providers/auth_provider.dart';
import 'providers/chat_provider.dart';
import 'pages/auth_page.dart';
import 'pages/chat_page.dart';
import 'pages/settings_page.dart';
import 'services/supabase_service.dart';
import 'services/overlay_service.dart';
import 'theme/app_theme.dart';
import 'widgets/background_assistant.dart';

final GlobalKey<NavigatorState> navigatorKey = GlobalKey<NavigatorState>();

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  AppConfig.instance.load();
  await SupabaseService.instance.initialize();
  runApp(
    MultiProvider(
      providers: [
        ChangeNotifierProvider(create: (_) => AuthProvider()),
        ChangeNotifierProvider(create: (_) => ChatProvider()),
        ChangeNotifierProvider<OverlayService>(create: (_) => OverlayService()..initialize()),
      ],
      child: const AcronousAIApp(),
    ),
  );
}

class SplashScreen extends StatefulWidget {
  const SplashScreen({super.key});

  @override
  State<SplashScreen> createState() => _SplashScreenState();
}

class _SplashScreenState extends State<SplashScreen> {
  bool _navigated = false;

  @override
  void initState() {
    super.initState();
    Future.delayed(const Duration(milliseconds: 1500), _onMinimumSplashDone);
  }

  void _onMinimumSplashDone() {
    if (!mounted || _navigated) return;
    final authProv = context.read<AuthProvider>();
    if (authProv.status != AuthStatus.uninitialized) {
      _navigate(authProv.status);
    } else {
      authProv.addListener(_onAuthChanged);
    }
  }

  void _onAuthChanged() {
    if (_navigated) return;
    final authProv = context.read<AuthProvider>();
    if (authProv.status != AuthStatus.uninitialized) {
      authProv.removeListener(_onAuthChanged);
      _navigate(authProv.status);
    }
  }

  void _navigate(AuthStatus status) {
    if (_navigated) return;
    _navigated = true;
    context.read<AuthProvider>().removeListener(_onAuthChanged);
    if (!mounted) return;
    final chatP = context.read<ChatProvider>();
    final authP = context.read<AuthProvider>();
    Navigator.of(context).pushReplacement(
      MaterialPageRoute(
        builder: (_) => status == AuthStatus.authenticated
            ? ChatPage(chatProvider: chatP, authProvider: authP)
            : const AuthPage(),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Scaffold(
      body: Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Container(
              width: 120,
              height: 120,
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(30),
                gradient: LinearGradient(
                  colors: [
                    cs.primary,
                    cs.primary.withValues(alpha: 0.7),
                  ],
                  begin: Alignment.topLeft,
                  end: Alignment.bottomRight,
                ),
              ),
              child: ClipRRect(
                borderRadius: BorderRadius.circular(30),
                child: Image.asset(
                  'assets/logo.png',
                  width: 120,
                  height: 120,
                  fit: BoxFit.contain,
                ),
              ),
            ),
            const SizedBox(height: 24),
            Text(
              AppConfig.instance.appTitle,
              style: Theme.of(context).textTheme.headlineMedium?.copyWith(
                    fontWeight: FontWeight.w700,
                    color: cs.onSurface,
                  ),
            ),
            const SizedBox(height: 32),
            SizedBox(
              width: 24,
              height: 24,
              child: CircularProgressIndicator(
                strokeWidth: 2.5,
                color: cs.primary,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class AcronousAIApp extends StatefulWidget {
  const AcronousAIApp({super.key});

  @override
  State<AcronousAIApp> createState() => _AcronousAIAppState();
}

class _AcronousAIAppState extends State<AcronousAIApp> with WidgetsBindingObserver {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    final overlay = context.read<OverlayService>();
    overlay.onAppLifecycleChanged(state);
  }

  @override
  Widget build(BuildContext context) {
    context.read<ChatProvider>().attachOverlayService(context.read<OverlayService>());
    return Consumer<ChatProvider>(
      builder: (context, chat, _) => MaterialApp(
        navigatorKey: navigatorKey,
        title: AppConfig.instance.appTitle,
        debugShowCheckedModeBanner: false,
        theme: AppTheme.light,
        darkTheme: AppTheme.dark,
        themeMode: chat.themeMode,
        home: const SplashScreen(),
        routes: {
          AppConfig.instance.settingsRoute: (context) => const SettingsPage(),
        },
        builder: (context, child) => BackgroundAssistant(
          navigatorKey: navigatorKey,
          child: child!,
        ),
      ),
    );
  }
}
