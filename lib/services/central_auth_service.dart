import 'dart:convert';
// ignore: avoid_web_libraries_in_flutter
import 'dart:html' as html;
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

class CentralAuthService {
  static final CentralAuthService instance = CentralAuthService._();
  CentralAuthService._();

  static const _tokenKey = 'acronous_token';
  static const _userKey = 'acronous_user';

  String? _token;
  String? _userEmail;
  String? _userId;
  String? _userName;

  bool get isSignedIn => _token != null;
  String? get token => _token;
  String? get userEmail => _userEmail;
  String? get userId => _userId;
  String? get userName => _userName;

  String get _authUrl {
    if (kReleaseMode) return 'https://auth.acronous.com';
    return 'https://auth.acronous.com';
  }

  Future<void> initialize() async {
    final prefs = await SharedPreferences.getInstance();

    // Check for token in URL params (callback from auth server)
    _extractTokenFromUrl();

    _token ??= prefs.getString(_tokenKey);

    if (_token != null) {
      final userJson = prefs.getString(_userKey);
      if (userJson != null) {
        try {
          final user = jsonDecode(userJson);
          _userEmail = user['email'];
          _userId = user['id'];
          _userName = user['name'];
        } catch (_) {}
      }
    }
  }

  void _extractTokenFromUrl() {
    try {
      final uri = Uri.parse(html.window.location.href);
      final token = uri.queryParameters['token'];
      if (token != null && token.isNotEmpty) {
        _token = token;
        // Clean URL without reloading
        final cleanUrl = uri.origin + uri.path;
        html.window.history.replaceState(null, '', cleanUrl);
      }
    } catch (_) {}
  }

  Future<void> _persistToken() async {
    if (_token == null) return;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_tokenKey, _token!);
    final userData = jsonEncode({
      'email': _userEmail,
      'id': _userId,
      'name': _userName,
    });
    await prefs.setString(_userKey, userData);
  }

  Future<void> _clearToken() async {
    _token = null;
    _userEmail = null;
    _userId = null;
    _userName = null;
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_tokenKey);
    await prefs.remove(_userKey);
  }

  Future<bool> checkAuth() async {
    if (_token == null) return false;
    try {
      final res = await http.get(
        Uri.parse('$_authUrl/api/auth/verify'),
        headers: {'Authorization': 'Bearer $_token'},
      );
      if (res.statusCode == 200) {
        final data = jsonDecode(res.body);
        if (data['valid'] == true) {
          _userEmail = data['user']['email'];
          _userId = data['user']['id'];
          _userName = data['user']['name'];
          await _persistToken();
          return true;
        }
      }
      await _clearToken();
      return false;
    } catch (_) {
      return _token != null;
    }
  }

  Future<bool> signIn(String email, String password) async {
    try {
      final res = await http.post(
        Uri.parse('$_authUrl/api/auth/login'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'email': email, 'password': password}),
      );
      if (res.statusCode == 200) {
        final data = jsonDecode(res.body);
        if (data['success'] == true) {
          _token = data['token'];
          _userEmail = data['user']['email'];
          _userId = data['user']['id'];
          _userName = data['user']['name'];
          await _persistToken();
          return true;
        }
      }
      return false;
    } catch (e) {
      debugPrint('Sign in error: $e');
      return false;
    }
  }

  Future<bool> signUp(String email, String password, {String? name}) async {
    try {
      final res = await http.post(
        Uri.parse('$_authUrl/api/auth/signup'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({
          'email': email,
          'password': password,
          'name': name ?? email.split('@')[0],
        }),
      );
      if (res.statusCode == 200) {
        final data = jsonDecode(res.body);
        if (data['success'] == true) {
          _token = data['token'];
          _userEmail = data['user']['email'];
          _userId = data['user']['id'];
          _userName = data['user']['name'];
          await _persistToken();
          return true;
        }
      }
      return false;
    } catch (e) {
      debugPrint('Sign up error: $e');
      return false;
    }
  }

  Future<void> signOut() async {
    try {
      await http.post(Uri.parse('$_authUrl/api/auth/logout'));
    } catch (_) {}
    await _clearToken();
  }

  void redirectToLogin() {
    final currentUrl = html.window.location.href;
    html.window.location.href = '$_authUrl/login?redirect=${Uri.encodeComponent(currentUrl)}';
  }
}
