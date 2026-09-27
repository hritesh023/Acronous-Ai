// Global paywall bus: any HTTP 402 (quota_exceeded / out_of_credits) anywhere
// in the app funnels here and lands the user on the subscription page.
// Wired once in main.dart via PaywallBus.attach(navigatorKey); producers
// (ChatProvider, image/video flows) just call PaywallBus.handle(e).
import 'package:flutter/material.dart';

import '../api/client.dart';
import '../pages/pricing_page.dart';

class PaywallBus {
  static GlobalKey<NavigatorState>? _nav;
  static DateTime? _lastPush;

  static void attach(GlobalKey<NavigatorState> key) {
    _nav = key;
  }

  /// Returns true when [e] was a paywall AND navigation was triggered.
  /// Throttled to one push per 3s so burst 402s don't stack pricing pages.
  static bool handle(Object e) {
    if (!ApiClient.isPaywall(e)) return false;
    final now = DateTime.now();
    if (_lastPush != null && now.difference(_lastPush!).inSeconds < 3) return true;
    _lastPush = now;
    final nav = _nav?.currentState;
    if (nav == null) return true;
    // Post-frame: producers often call us mid-build (notifyListeners).
    WidgetsBinding.instance.addPostFrameCallback((_) {
      try {
        nav.push(MaterialPageRoute(builder: (_) => const PricingPage()));
      } catch (_) {}
    });
    return true;
  }
}
