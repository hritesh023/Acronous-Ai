import 'dart:async';
import 'package:flutter/material.dart';
import '../services/central_auth_service.dart';

enum AuthStatus { uninitialized, authenticated, unauthenticated, loading }

class AuthProvider extends ChangeNotifier {
  final CentralAuthService _authService;

  String? _userEmail;
  String? _userId;
  AuthStatus _status = AuthStatus.uninitialized;
  String? _error;

  AuthProvider({CentralAuthService? authService})
      : _authService = authService ?? CentralAuthService.instance {
    _init();
  }

  String? get userEmail => _userEmail;
  String? get userId => _userId;
  AuthStatus get status => _status;
  String? get error => _error;

  Future<void> _init() async {
    await _authService.initialize();
    // If token was just extracted from redirect URL, trust it directly
    // without a cross-origin API call (avoids CORS preflight failure).
    if (_authService.tokenFromUrl && _authService.token != null) {
      _userEmail = _authService.userEmail;
      _userId = _authService.userId;
      _status = AuthStatus.authenticated;
    } else {
      final authenticated = await _authService.checkAuth();
      if (authenticated) {
        _userEmail = _authService.userEmail;
        _userId = _authService.userId;
        _status = AuthStatus.authenticated;
      } else {
        _status = AuthStatus.unauthenticated;
      }
    }
    notifyListeners();
  }

  Future<void> signInWithEmail(String email, String password) async {
    try {
      _status = AuthStatus.loading;
      _error = null;
      notifyListeners();

      final success = await _authService.signIn(email, password);

      if (success) {
        _userEmail = _authService.userEmail;
        _userId = _authService.userId;
        _status = AuthStatus.authenticated;
      } else {
        _error = _authService.lastError;
        _status = AuthStatus.unauthenticated;
      }
      notifyListeners();
    } catch (e) {
      debugPrint('Sign in exception: $e');
      _error = _authService.lastError ?? 'An unexpected error occurred';
      _status = AuthStatus.unauthenticated;
      notifyListeners();
    }
  }

  Future<void> signUpWithEmail(String email, String password) async {
    try {
      _status = AuthStatus.loading;
      _error = null;
      notifyListeners();

      final success = await _authService.signUp(email, password);

      if (success) {
        _userEmail = _authService.userEmail;
        _userId = _authService.userId;
        _status = AuthStatus.authenticated;
      } else {
        _error = _authService.lastError;
        _status = AuthStatus.unauthenticated;
      }
      notifyListeners();
    } catch (e) {
      debugPrint('Sign up exception: $e');
      _error = _authService.lastError ?? 'An unexpected error occurred';
      _status = AuthStatus.unauthenticated;
      notifyListeners();
    }
  }

  Future<void> signOut() async {
    await _authService.signOut();
    _userEmail = null;
    _userId = null;
    _status = AuthStatus.unauthenticated;
    notifyListeners();
  }

  void redirectToLogin() {
    _authService.redirectToLogin();
  }

  void clearError() {
    _error = null;
    notifyListeners();
  }
}
