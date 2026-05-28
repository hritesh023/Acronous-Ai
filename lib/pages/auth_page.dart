import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../constants/app_constants.dart';
import '../providers/auth_provider.dart' as auth;
import '../providers/chat_provider.dart';
import 'chat_page.dart';

class AuthPage extends StatefulWidget {
  const AuthPage({super.key});

  @override
  State<AuthPage> createState() => _AuthPageState();
}

class _AuthPageState extends State<AuthPage>
    with SingleTickerProviderStateMixin {
  final _emailController = TextEditingController();
  final _passwordController = TextEditingController();
  final _formKey = GlobalKey<FormState>();
  bool _isSignUp = false;
  bool _obscurePassword = true;
  late AnimationController _fadeController;
  late Animation<double> _fadeAnimation;

  @override
  void initState() {
    super.initState();
    _fadeController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 800),
    );
    _fadeAnimation = CurvedAnimation(
      parent: _fadeController,
      curve: Curves.easeIn,
    );
    _fadeController.forward();
  }

  @override
  void dispose() {
    _emailController.dispose();
    _passwordController.dispose();
    _fadeController.dispose();
    super.dispose();
  }

  void _submit() {
    if (!_formKey.currentState!.validate()) return;

    final authProv = context.read<auth.AuthProvider>();
    final email = _emailController.text.trim();
    final password = _passwordController.text;

    if (_isSignUp) {
      authProv.signUpWithEmail(email, password);
    } else {
      authProv.signInWithEmail(email, password);
    }
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final size = MediaQuery.of(context).size;
    final authProv = context.watch<auth.AuthProvider>();

    if (authProv.status == auth.AuthStatus.authenticated) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) {
          final chat = context.read<ChatProvider>();
          final aProv = context.read<auth.AuthProvider>();
          Navigator.of(context).pushAndRemoveUntil(
            MaterialPageRoute(
              builder: (_) => ChatPage(
                chatProvider: chat,
                authProvider: aProv,
              ),
            ),
            (_) => false,
          );
        }
      });
    }

    return Scaffold(
      body: SafeArea(
        child: FadeTransition(
          opacity: _fadeAnimation,
          child: Center(
            child: SingleChildScrollView(
              padding: const EdgeInsets.symmetric(
                horizontal: AppDimens.paddingXXL,
              ),
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 400),
                child: Form(
                  key: _formKey,
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      SizedBox(height: size.height * 0.05),
                      Container(
                        width: 100,
                        height: 100,
                        decoration: BoxDecoration(
                          borderRadius: BorderRadius.circular(25),
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
                          borderRadius: BorderRadius.circular(25),
                          child: Image.asset(
                            'assets/logo.png',
                            width: 100,
                            height: 100,
                            fit: BoxFit.contain,
                          ),
                        ),
                      ),
                      const SizedBox(height: 20),
                      Text(
                        AppStrings.appName,
                        style:
                            Theme.of(context).textTheme.headlineSmall?.copyWith(
                                  fontWeight: FontWeight.w700,
                                  color: cs.onSurface,
                                ),
                      ),
                      const SizedBox(height: 6),
                      Text(
                        _isSignUp ? 'Create your account' : 'Welcome back',
                        style: TextStyle(
                          color: cs.onSurfaceVariant,
                          fontSize: AppDimens.fontSizeBase,
                        ),
                      ),
                      const SizedBox(height: 36),
                      TextFormField(
                        controller: _emailController,
                        keyboardType: TextInputType.emailAddress,
                        textInputAction: TextInputAction.next,
                        decoration: InputDecoration(
                          labelText: 'Email',
                          prefixIcon: const Icon(Icons.email_outlined),
                          border: OutlineInputBorder(
                            borderRadius: BorderRadius.circular(12),
                          ),
                        ),
                        validator: (v) {
                          if (v == null || v.trim().isEmpty) {
                            return 'Please enter your email';
                          }
                          if (!v.contains('@')) {
                            return 'Please enter a valid email';
                          }
                          return null;
                        },
                      ),
                      const SizedBox(height: 14),
                      TextFormField(
                        controller: _passwordController,
                        obscureText: _obscurePassword,
                        textInputAction: TextInputAction.done,
                        onFieldSubmitted: (_) => _submit(),
                        decoration: InputDecoration(
                          labelText: 'Password',
                          prefixIcon: const Icon(Icons.lock_outlined),
                          suffixIcon: IconButton(
                            icon: Icon(
                              _obscurePassword
                                  ? Icons.visibility_outlined
                                  : Icons.visibility_off_outlined,
                            ),
                            onPressed: () => setState(
                                () => _obscurePassword = !_obscurePassword),
                          ),
                          border: OutlineInputBorder(
                            borderRadius: BorderRadius.circular(12),
                          ),
                        ),
                        validator: (v) {
                          if (v == null || v.isEmpty) {
                            return 'Please enter your password';
                          }
                          if (v.length < 6) {
                            return 'Password must be at least 6 characters';
                          }
                          return null;
                        },
                      ),
                      const SizedBox(height: 24),
                      Consumer<auth.AuthProvider>(
                        builder: (context, authProv, _) {
                          if (authProv.error != null) {
                            return Padding(
                              padding:
                                  const EdgeInsets.only(bottom: AppDimens.paddingLG),
                              child: Container(
                                padding: const EdgeInsets.symmetric(
                                  horizontal: 16,
                                  vertical: 10,
                                ),
                                decoration: BoxDecoration(
                                  color: cs.errorContainer,
                                  borderRadius: BorderRadius.circular(10),
                                ),
                                child: Row(
                                  children: [
                                    Icon(Icons.error_outline,
                                        size: 18, color: cs.error),
                                    const SizedBox(width: 8),
                                    Expanded(
                                      child: Text(
                                        authProv.error!,
                                        style: TextStyle(
                                          color: cs.onErrorContainer,
                                          fontSize: AppDimens.fontSizeLG,
                                        ),
                                      ),
                                    ),
                                    IconButton(
                                      icon: Icon(Icons.close,
                                          size: 16, color: cs.error),
                                      onPressed: authProv.clearError,
                                      visualDensity: VisualDensity.compact,
                                    ),
                                  ],
                                ),
                              ),
                            );
                          }
                          return const SizedBox.shrink();
                        },
                      ),
                      Consumer<auth.AuthProvider>(
                        builder: (context, authProv, _) {
                          final loading = authProv.status ==
                              auth.AuthStatus.loading;
                          return SizedBox(
                            width: double.infinity,
                            height: 48,
                            child: FilledButton(
                              onPressed: loading ? null : _submit,
                              child: loading
                                  ? const SizedBox(
                                      width: 20,
                                      height: 20,
                                      child: CircularProgressIndicator(
                                        strokeWidth: 2,
                                        color: Colors.white,
                                      ),
                                    )
                                  : Text(
                                      _isSignUp ? 'Sign Up' : 'Sign In',
                                      style: const TextStyle(fontSize: 16),
                                    ),
                            ),
                          );
                        },
                      ),
                      const SizedBox(height: 16),
                      TextButton(
                        onPressed: () {
                          setState(() {
                            _isSignUp = !_isSignUp;
                            _formKey.currentState?.reset();
                          });
                          context.read<auth.AuthProvider>().clearError();
                        },
                        child: RichText(
                          text: TextSpan(
                            text: _isSignUp
                                ? 'Already have an account? '
                                : "Don't have an account? ",
                            style: TextStyle(
                              color: cs.onSurfaceVariant,
                              fontSize: AppDimens.fontSizeBase,
                            ),
                            children: [
                              TextSpan(
                                text: _isSignUp ? 'Sign In' : 'Sign Up',
                                style: TextStyle(
                                  color: cs.primary,
                                  fontWeight: FontWeight.w600,
                                ),
                              ),
                            ],
                          ),
                        ),
                      ),
                      SizedBox(height: size.height * 0.05),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
