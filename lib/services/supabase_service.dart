import 'package:flutter/foundation.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

class SupabaseService {
  SupabaseService._();

  static final SupabaseService instance = SupabaseService._();

  static const String _supabaseUrl = 'https://gewfhlsjhujqhuqhulek.supabase.co';
  static const String _anonKey =
      'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imdld2ZobHNqaHVqcWh1cWh1bGVrIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Nzk1MzcyOTMsImV4cCI6MjA5NTExMzI5M30.0FCGuHYeP7fao0t7E2lwnztiJqxSqa1X_9ymELSgWpA';

  GoTrueClient get auth => Supabase.instance.client.auth;

  Future<void> initialize() async {
    await Supabase.initialize(
      url: _supabaseUrl,
      anonKey: _anonKey,
      debug: kDebugMode,
    );
  }

  Future<AuthResponse> signUpWithEmail({
    required String email,
    required String password,
  }) async {
    return auth.signUp(email: email, password: password);
  }

  Future<AuthResponse> signInWithEmail({
    required String email,
    required String password,
  }) async {
    return auth.signInWithPassword(email: email, password: password);
  }

  Future<void> signOut() async {
    await auth.signOut();
  }

  Session? get currentSession => auth.currentSession;
  User? get currentUser => auth.currentUser;

  Future<void> upsertProfile({
    required String userId,
    required String email,
    String? displayName,
  }) async {
    await Supabase.instance.client.from('profiles').upsert({
      'id': userId,
      'email': email,
      'display_name': displayName ?? email.split('@').first,
      'updated_at': DateTime.now().toIso8601String(),
    });
  }

  Future<Map<String, dynamic>?> getProfile(String userId) async {
    final response = await Supabase.instance.client
        .from('profiles')
        .select()
        .eq('id', userId)
        .maybeSingle();
    return response;
  }
}
