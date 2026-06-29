import 'dart:async';
import 'package:flutter/material.dart';
import '../services/aws_cognito_service.dart';

enum AuthStatus { uninitialized, authenticated, unauthenticated, loading }

class AuthProvider extends ChangeNotifier {
  final AwsCognitoService _cognito;
  String? _userEmail;
  String? _userId;
  AuthStatus _status = AuthStatus.uninitialized;
  String? _error;

  AuthProvider({AwsCognitoService? cognito})
      : _cognito = cognito ?? AwsCognitoService.instance {
    _init();
  }

  String? get userEmail => _userEmail;
  String? get userId => _userId;
  AuthStatus get status => _status;
  String? get error => _error;

  Future<void> _init() async {
    _cognito.initialize();
    final signedIn = await _cognito.isSignedIn();
    if (signedIn) {
      _userEmail = _cognito.userEmail;
      _userId = _cognito.userId;
      _status = AuthStatus.authenticated;
    } else {
      _status = AuthStatus.unauthenticated;
    }
    notifyListeners();
  }

  Future<void> signInWithEmail(String email, String password) async {
    try {
      _status = AuthStatus.loading;
      _error = null;
      notifyListeners();

      final session = await _cognito.signIn(
        email: email.trim(),
        password: password,
      );

      if (session != null) {
        _userEmail = _cognito.userEmail;
        _userId = _cognito.userId;
        _status = AuthStatus.authenticated;
      } else {
        _status = AuthStatus.unauthenticated;
      }
      notifyListeners();
    } catch (e) {
      _error = e.toString().replaceFirst('Exception: ', '');
      _status = AuthStatus.unauthenticated;
      notifyListeners();
    }
  }

  Future<void> signUpWithEmail(String email, String password) async {
    try {
      _status = AuthStatus.loading;
      _error = null;
      notifyListeners();

      final session = await _cognito.signUp(
        email: email.trim(),
        password: password,
      );

      if (session != null) {
        _userEmail = _cognito.userEmail;
        _userId = _cognito.userId;
        _status = AuthStatus.authenticated;
      } else {
        _status = AuthStatus.unauthenticated;
      }
      notifyListeners();
    } catch (e) {
      _error = e.toString().replaceFirst('Exception: ', '');
      _status = AuthStatus.unauthenticated;
      notifyListeners();
    }
  }

  Future<void> signOut() async {
    await _cognito.signOut();
    _userEmail = null;
    _userId = null;
    _status = AuthStatus.unauthenticated;
    notifyListeners();
  }

  void clearError() {
    _error = null;
    notifyListeners();
  }
}
