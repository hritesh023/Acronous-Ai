import 'dart:async';

import 'package:flutter/material.dart';
import 'package:supabase_flutter/supabase_flutter.dart';
import '../services/supabase_service.dart';

enum AuthStatus { uninitialized, authenticated, unauthenticated, loading }

class AuthProvider extends ChangeNotifier {
  final SupabaseService _supabase;
  User? _user;
  AuthStatus _status = AuthStatus.uninitialized;
  String? _error;
  StreamSubscription<AuthState>? _authSubscription;

  AuthProvider({SupabaseService? supabase})
      : _supabase = supabase ?? SupabaseService.instance {
    _init();
  }

  User? get user => _user;
  AuthStatus get status => _status;
  String? get error => _error;

  @override
  void dispose() {
    _authSubscription?.cancel();
    super.dispose();
  }

  void _init() {
    final session = _supabase.currentSession;
    _user = session?.user;
    _status = _user != null ? AuthStatus.authenticated : AuthStatus.unauthenticated;
    notifyListeners();

    _authSubscription = _supabase.auth.onAuthStateChange.listen(_onAuthChange);
  }

  void _onAuthChange(AuthState state) {
    _user = state.session?.user;
    _status = _user != null
        ? AuthStatus.authenticated
        : AuthStatus.unauthenticated;
    notifyListeners();
  }

  Future<void> signInWithEmail(String email, String password) async {
    try {
      _status = AuthStatus.loading;
      _error = null;
      notifyListeners();

      final response = await _supabase.signInWithEmail(
        email: email.trim(),
        password: password,
      );

      _user = response.user;
      _status = AuthStatus.authenticated;
      notifyListeners();
    } on AuthException catch (e) {
      _error = e.message;
      _status = AuthStatus.unauthenticated;
      notifyListeners();
    } catch (e) {
      _error = 'Sign in failed. Please try again.';
      _status = AuthStatus.unauthenticated;
      notifyListeners();
    }
  }

  Future<void> signUpWithEmail(String email, String password) async {
    try {
      _status = AuthStatus.loading;
      _error = null;
      notifyListeners();

      final response = await _supabase.signUpWithEmail(
        email: email.trim(),
        password: password,
      );

      if (response.session != null) {
        _user = response.user;
        _status = AuthStatus.authenticated;
      } else {
        _status = AuthStatus.unauthenticated;
      }
      notifyListeners();

      if (response.user != null) {
        await _supabase.upsertProfile(
          userId: response.user!.id,
          email: email.trim(),
        );
      }
    } on AuthException catch (e) {
      _error = e.message;
      _status = AuthStatus.unauthenticated;
      notifyListeners();
    } catch (e) {
      _error = 'Sign up failed. Please try again.';
      _status = AuthStatus.unauthenticated;
      notifyListeners();
    }
  }

  Future<void> signOut() async {
    await _supabase.signOut();
    _user = null;
    _status = AuthStatus.unauthenticated;
    notifyListeners();
  }

  void clearError() {
    _error = null;
    notifyListeners();
  }
}
