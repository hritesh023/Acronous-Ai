import 'package:flutter/material.dart';
import 'package:supabase_flutter/supabase_flutter.dart';
import '../services/supabase_service.dart';

enum AuthStatus { uninitialized, authenticated, unauthenticated, loading }

class AuthProvider extends ChangeNotifier {
  final SupabaseService _supabase;
  User? _user;
  AuthStatus _status = AuthStatus.uninitialized;
  String? _error;

  AuthProvider({SupabaseService? supabase})
      : _supabase = supabase ?? SupabaseService.instance {
    _init();
  }

  User? get user => _user;
  AuthStatus get status => _status;
  String? get error => _error;

  void _init() {
    _user = _supabase.currentUser;
    if (_user != null) {
      _status = AuthStatus.authenticated;
    }
    // If user is null, keep uninitialized until onAuthStateChange fires
    notifyListeners();

    _supabase.auth.onAuthStateChange.listen(_onAuthChange);
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
      _error = e.toString();
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

      _user = response.user;
      _status = AuthStatus.authenticated;
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
      _error = e.toString();
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
