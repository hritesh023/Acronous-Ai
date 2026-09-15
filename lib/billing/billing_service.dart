// Centralized billing for Acronous AI.
// Money flow (no redirects, no QR codes, no secrets in the app):
//   1. App creates a Razorpay ORDER server-side (worker holds the secret).
//   2. The REAL Razorpay gateway opens in-app (checkout.js on web, native
//      SDK with UPI/cards on Android/iOS, hosted auto-checkout on desktop).
//   3. App sends payment+signature to /v1/billing/verify; the worker checks
//      HMAC-SHA256 and grants the subscription in KV.
import 'package:flutter/foundation.dart';
import 'package:url_launcher/url_launcher.dart';

import '../api/client.dart';
import '../services/central_auth_service.dart';
import 'pay_gateway.dart';
import 'pay_result.dart';
import 'plans.dart';

class BillingService extends ChangeNotifier {
  final ApiClient api;
  BillingService(this.api);

  bool loading = false;
  bool isPro = false;
  String? activePlanId;
  int apiCredits = 0;
  String? busyPlanId;
  String? error;

  static String checkoutFallbackUrl({String? token, required String plan}) {
    final base = 'https://acronous.com/checkout.html?plan=${Uri.encodeComponent(plan)}';
    if (token != null && token.isNotEmpty) {
      return '$base&token=${Uri.encodeComponent(token)}';
    }
    return base;
  }

  Future<void> refresh() async {
    loading = true;
    error = null;
    notifyListeners();
    try {
      final s = await api.getBillingStatus();
      isPro = s['pro'] == true;
      apiCredits = (s['api_credits'] as num?)?.toInt() ?? 0;
      final subs = s['subscriptions'] as Map<String, dynamic>?;
      final ai = subs?['acronous_ai'] as Map<String, dynamic>?;
      activePlanId = ai?['plan'] as String?;
      notifyListeners();
    } catch (e) {
      error = ApiClient.isPaywall(e)
          ? ApiClient.paywallMessage(e)
          : 'Could not load subscription status.';
      notifyListeners();
    } finally {
      loading = false;
      notifyListeners();
    }
  }

  /// Opens the real Razorpay gateway for [plan] and verifies the payment.
  /// Returns true when the plan is now active. Cancellation returns false
  /// quietly; failures set [error].
  Future<bool> buy(AiPlan plan) async {
    if (busyPlanId != null) return false;
    busyPlanId = plan.id;
    error = null;
    notifyListeners();
    try {
      final order = await api.createBillingOrder(plan: plan.id);
      final orderId = order['order_id'] as String? ?? '';
      final amount = (order['amount'] as num?)?.toInt() ?? 0;
      final keyId = order['key_id'] as String? ?? '';
      if (orderId.isEmpty || keyId.isEmpty || amount <= 0) {
        throw StateError('Could not start checkout. Please try again.');
      }
      late final GatewayResult g;
      try {
        g = await openRazorpayCheckout(
          keyId: keyId,
          amountPaise: amount,
          orderId: orderId,
          planLabel: '${plan.label.replaceAll(' ⭐', '')} (${formatPlanPrice(plan.priceInr)}/mo)',
          themeColor: '#6366f1',
        );
      } on UnsupportedError {
        // Desktop: complete payment on the hosted auto-checkout page.
        await launchUrl(
          Uri.parse(checkoutFallbackUrl(
              token: CentralAuthService.instance.token, plan: plan.id)),
          mode: LaunchMode.externalApplication,
        );
        return true;
      }
      await api.verifyBillingPayment(
        orderId: g.orderId,
        paymentId: g.paymentId,
        signature: g.signature,
      );
      await refresh();
      return true;
    } on PaymentCancelled {
      return false;
    } catch (e) {
      error = _friendly(e);
      notifyListeners();
      return false;
    } finally {
      busyPlanId = null;
      notifyListeners();
    }
  }

  String _friendly(Object e) {
    if (e is ApiException) {
      if (e.statusCode == 503) {
        return 'Payments are being switched on. Please try again in a bit.';
      }
      if (e.message.isNotEmpty) return e.message;
    }
    final m = e.toString().replaceFirst('StateError: ', '');
    if (m.startsWith('Exception: ')) return m.substring('Exception: '.length);
    if (m.startsWith('Bad state: ')) return m.substring('Bad state: '.length);
    return m.isEmpty ? 'Payment failed. Please try again.' : m;
  }
}
