import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../constants/app_constants.dart';
import '../models/message.dart';

class PreferencesService {
  Future<ThemeMode> loadThemeMode() async {
    final prefs = await SharedPreferences.getInstance();
    final value = prefs.getString(AppPrefKeys.themeMode) ?? 'system';
    switch (value) {
      case 'dark':
        return ThemeMode.dark;
      case 'light':
        return ThemeMode.light;
      default:
        return ThemeMode.system;
    }
  }

  Future<void> saveThemeMode(ThemeMode mode) async {
    final prefs = await SharedPreferences.getInstance();
    final value = mode == ThemeMode.dark
        ? 'dark'
        : mode == ThemeMode.light
            ? 'light'
            : 'system';
    await prefs.setString(AppPrefKeys.themeMode, value);
  }

  Future<double> loadTtsSpeed() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getDouble(AppPrefKeys.ttsSpeed) ?? 0.5;
  }

  Future<void> saveTtsSpeed(double value) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setDouble(AppPrefKeys.ttsSpeed, value);
  }

  Future<double> loadTtsPitch() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getDouble(AppPrefKeys.ttsPitch) ?? 1.0;
  }

  Future<void> saveTtsPitch(double value) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setDouble(AppPrefKeys.ttsPitch, value);
  }

  Future<bool> loadContinuousVoice() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getBool(AppPrefKeys.continuousVoice) ?? false;
  }

  Future<void> saveContinuousVoice(bool value) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(AppPrefKeys.continuousVoice, value);
  }

  Future<void> saveContinuousVoiceEnabled(bool value) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(AppPrefKeys.continuousVoice, value);
  }

  Future<bool> loadAutoSendVoice() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getBool(AppPrefKeys.autoSendVoice) ?? false;
  }

  Future<void> saveAutoSendVoice(bool value) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(AppPrefKeys.autoSendVoice, value);
  }

  Future<bool> loadBackgroundAssistant() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getBool(AppPrefKeys.backgroundAssistant) ?? true;
  }

  Future<void> saveBackgroundAssistant(bool value) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(AppPrefKeys.backgroundAssistant, value);
  }

  Future<bool> loadContinuousVoiceSearch() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getBool(AppPrefKeys.continuousVoiceSearch) ?? false;
  }

  Future<void> saveContinuousVoiceSearch(bool value) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(AppPrefKeys.continuousVoiceSearch, value);
  }

  Future<bool> loadSystemOverlay() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getBool(AppPrefKeys.systemOverlay) ?? false;
  }

  Future<void> saveSystemOverlay(bool value) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(AppPrefKeys.systemOverlay, value);
  }

  Future<bool> loadOverlayPermissionGranted() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getBool(AppPrefKeys.overlayPermissionGranted) ?? false;
  }

  Future<void> saveOverlayPermissionGranted(bool value) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(AppPrefKeys.overlayPermissionGranted, value);
  }

  Future<List<Conversation>> loadConversations() async {
    final prefs = await SharedPreferences.getInstance();
    final data = prefs.getString(AppPrefKeys.conversations);
    if (data == null) return [];
    final list = jsonDecode(data) as List<dynamic>;
    return list
        .map((item) =>
            Conversation.fromJson(item as Map<String, dynamic>))
        .toList();
  }

  Future<void> saveConversations(List<Conversation> conversations) async {
    final prefs = await SharedPreferences.getInstance();
    final data = conversations.map((c) => c.toJson()).toList();
    await prefs.setString(AppPrefKeys.conversations, jsonEncode(data));
  }

  Future<String> loadServerUrl() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString(AppPrefKeys.serverUrl) ?? '';
  }

  Future<void> saveServerUrl(String url) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(AppPrefKeys.serverUrl, url);
  }

}
