import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';
import 'package:web/web.dart' as web;

class CentralAuthService {
  static final CentralAuthService instance = CentralAuthService._();
  CentralAuthService._();

  static const _tokenKey = 'acronous_token';
  static const _userKey = 'acronous_user';

  String? _token;
  String? _userEmail;
  String? _userId;
  String? _userName;
  String? lastError;
  bool _tokenFromUrl = false;

  bool get isSignedIn => _token != null;
  String? get token => _token;
  String? get userEmail => _userEmail;
  String? get userId => _userId;
  String? get userName => _userName;
  bool get tokenFromUrl => _tokenFromUrl;

  String get _authUrl {
    try {
      final uri = Uri.parse(web.window.location.href);
      final host = uri.host;
      // Local dev: use current origin. Production: centralized auth at acronous.com.
      if (host == 'localhost' || host == '127.0.0.1') {
        final origin = '${uri.scheme}://${uri.host}${uri.port == 80 || uri.port == 443 || uri.port <= 0 ? '' : ':${uri.port}'}';
        return origin;
      }
      return 'https://acronous.com';
    } catch (_) {
      return 'https://acronous.com';
    }
  }

  Map<String, dynamic>? _decodeJwtPayload(String token) {
    try {
      final parts = token.split('.');
      if (parts.length != 3) return null;
      final normalized = parts[1].padRight(parts[1].length + (4 - parts[1].length % 4) % 4, '=');
      return jsonDecode(utf8.fuse(base64Url).decode(normalized)) as Map<String, dynamic>;
    } catch (_) {
      return null;
    }
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
      // If token came fresh from redirect URL, parse user info from JWT payload
      // to avoid a CORS-blocked API call to verify an already-valid token.
      if (_tokenFromUrl && (_userEmail == null || _userId == null)) {
        final payload = _decodeJwtPayload(_token!);
        if (payload != null) {
          _userEmail = payload['email'] as String?;
          _userId = payload['id'] as String?;
          _userName = payload['name'] as String?;
        }
        await _persistToken();
      }
    }
  }

  void _extractTokenFromUrl() {
    try {
      final uri = Uri.parse(web.window.location.href);
      final token = uri.queryParameters['token'];
      if (token != null && token.isNotEmpty) {
        _token = token;
        _tokenFromUrl = true;
        // Clean URL without reloading
        final cleanUrl = uri.origin + uri.path;
        web.window.history.replaceState(null, '', cleanUrl);
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
      ).timeout(const Duration(seconds: 10));
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
      await _clearToken();
      return false;
    }
  }

  Future<bool> signIn(String email, String password) async {
    lastError = null;
    try {
      final res = await http.post(
        Uri.parse('$_authUrl/api/auth/login'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'email': email, 'password': password}),
      ).timeout(const Duration(seconds: 15));
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
      try {
        final data = jsonDecode(res.body);
        final backendMsg = (data['error'] as String?) ?? '';
        debugPrint('Sign in failed: $backendMsg');
        lastError = res.statusCode == 401 ? 'Invalid email or password' : 'Login failed';
      } catch (_) {
        lastError = 'Login failed (${res.statusCode})';
      }
      return false;
    } catch (e) {
      lastError = 'Network error — could not reach auth server';
      debugPrint('Sign in error: $e');
      return false;
    }
  }

  Future<bool> signUp(String email, String password, {String? name}) async {
    lastError = null;
    try {
      final res = await http.post(
        Uri.parse('$_authUrl/api/auth/signup'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({
          'email': email,
          'password': password,
          'name': name ?? email.split('@')[0],
        }),
      ).timeout(const Duration(seconds: 15));
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
      try {
        final data = jsonDecode(res.body);
        final backendMsg = (data['error'] as String?) ?? '';
        debugPrint('Sign up failed: $backendMsg');
        lastError = 'Sign up failed';
      } catch (_) {
        lastError = 'Sign up failed (${res.statusCode})';
      }
      return false;
    } catch (e) {
      lastError = 'Network error — could not reach auth server';
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
    final currentUrl = web.window.location.href;
    web.window.location.href = '$_authUrl/login?_=${DateTime.now().millisecondsSinceEpoch}&redirect=${Uri.encodeComponent(currentUrl)}';
  }

  String get authUrl => _authUrl;
}
