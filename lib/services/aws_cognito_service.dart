import 'dart:async';
import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:amazon_cognito_identity_dart_2/cognito.dart';
import '../config/app_config.dart';

class AwsCognitoService {
  AwsCognitoService._();

  static final AwsCognitoService instance = AwsCognitoService._();

  CognitoUserPool? _userPool;
  CognitoUser? _cognitoUser;
  CognitoUserSession? _session;
  bool _initialized = false;

  static const _keyIdToken = 'cognito_id_token';
  static const _keyAccessToken = 'cognito_access_token';
  static const _keyRefreshToken = 'cognito_refresh_token';
  static const _keyUserEmail = 'cognito_user_email';

  bool get isAvailable => _initialized && _userPool != null;
  CognitoUserPool? get userPool => _userPool;
  CognitoUser? get cognitoUser => _cognitoUser;
  CognitoUserSession? get currentSession => _session;
  String? get userId => _session?.getIdToken().payload['sub'] as String?;
  String? get userEmail => _session?.getIdToken().payload['email'] as String?;
  String? get userDisplayName => _session?.getIdToken().payload['name'] as String?;
  String? get accessToken => _session?.getAccessToken().getJwtToken();
  String? get idToken => _session?.getIdToken().getJwtToken();

  void initialize() {
    final config = AppConfig.instance;
    final poolId = config.cognitoUserPoolId;
    final clientId = config.cognitoClientId;
    if (poolId.isEmpty || clientId.isEmpty) {
      if (kDebugMode) debugPrint('Cognito: poolId or clientId not configured');
      return;
    }
    try {
      _userPool = CognitoUserPool(poolId, clientId);
      _initialized = true;
      if (kDebugMode) debugPrint('Cognito: initialized pool=$poolId client=$clientId');
    } catch (e) {
      if (kDebugMode) debugPrint('Cognito: init error $e');
      _userPool = null;
      _initialized = false;
    }
  }

  Future<CognitoUserSession?> signUp({
    required String email,
    required String password,
  }) async {
    if (_userPool == null) throw Exception('Cognito not configured');
    try {
      final result = await _userPool!.signUp(email, password);
      _cognitoUser = result.user;
      if (result.session != null) {
        _session = result.session;
        await _persistSession();
      }
      return _session;
    } catch (e) {
      throw Exception('Sign up failed: $e');
    }
  }

  Future<CognitoUserSession?> signIn({
    required String email,
    required String password,
  }) async {
    if (_userPool == null) throw Exception('Cognito not configured');
    try {
      _cognitoUser = CognitoUser(email, _userPool!);
      final authDetails = AuthenticationDetails(
        username: email,
        password: password,
      );
      _session = await _cognitoUser!.authenticateUser(authDetails);
      await _persistSession();
      return _session;
    } catch (e) {
      _session = null;
      _cognitoUser = null;
      throw Exception('Sign in failed: $e');
    }
  }

  Future<void> signOut() async {
    try {
      await _cognitoUser?.signOut();
    } catch (_) {}
    _cognitoUser = null;
    _session = null;
    await _clearPersistedSession();
  }

  Future<bool> isSignedIn() async {
    if (_session != null && _session!.isValid()) return true;
    return _restorePersistedSession();
  }

  Future<void> refreshSession() async {
    if (_session == null) {
      await _restorePersistedSession();
    }
    if (_session == null) return;
    final refreshToken = _session!.getRefreshToken();
    if (refreshToken == null || (refreshToken.getToken()?.isEmpty ?? true)) return;
    if (_cognitoUser == null) return;
    try {
      _session = await _cognitoUser!.refreshSession(refreshToken);
      await _persistSession();
    } catch (_) {
      _session = null;
      await _clearPersistedSession();
    }
  }

  Future<void> _persistSession() async {
    if (_session == null) return;
    final prefs = await SharedPreferences.getInstance();
    final idTokenVal = _session!.getIdToken().getJwtToken();
    if (idTokenVal != null) {
      await prefs.setString(_keyIdToken, idTokenVal);
    }
    final accessTokenVal = _session!.getAccessToken().getJwtToken();
    if (accessTokenVal != null) {
      await prefs.setString(_keyAccessToken, accessTokenVal);
    }
    final rt = _session!.getRefreshToken();
    if (rt != null) {
      final rtVal = rt.getToken();
      if (rtVal != null && rtVal.isNotEmpty) {
        await prefs.setString(_keyRefreshToken, rtVal);
      }
    }
    final email = _session!.getIdToken().payload['email'] as String?;
    if (email != null) {
      await prefs.setString(_keyUserEmail, email);
    }
  }

  Future<bool> _restorePersistedSession() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final idTokenStr = prefs.getString(_keyIdToken);
      final accessTokenStr = prefs.getString(_keyAccessToken);
      if (idTokenStr == null || accessTokenStr == null) return false;
      final idToken = CognitoIdToken(idTokenStr);
      final accessToken = CognitoAccessToken(accessTokenStr);
      final refreshTokenStr = prefs.getString(_keyRefreshToken) ?? '';
      CognitoRefreshToken? refreshToken;
      if (refreshTokenStr.isNotEmpty) {
        refreshToken = CognitoRefreshToken(refreshTokenStr);
      }
      _session = CognitoUserSession(idToken, accessToken, refreshToken: refreshToken);
      if (!_session!.isValid()) {
        if (refreshToken != null && (refreshToken.getToken()?.isNotEmpty ?? false)) {
          _cognitoUser = CognitoUser(prefs.getString(_keyUserEmail) ?? '', _userPool!);
          try {
            _session = await _cognitoUser!.refreshSession(refreshToken);
            await _persistSession();
            return true;
          } catch (_) {}
        }
        _session = null;
        return false;
      }
      final email = prefs.getString(_keyUserEmail) ?? '';
      _cognitoUser = CognitoUser(email, _userPool!);
      return true;
    } catch (_) {
      _session = null;
      return false;
    }
  }

  Future<void> _clearPersistedSession() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_keyIdToken);
    await prefs.remove(_keyAccessToken);
    await prefs.remove(_keyRefreshToken);
    await prefs.remove(_keyUserEmail);
  }
}
