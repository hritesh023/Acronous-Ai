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
  Map<String, dynamic> usage = const {};
  Map<String, dynamic> tierQuotas = const {};
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
      // Link any guest-paid plan (paid without sign-in, same email) first —
      // paying never requires an account.
      try {
        if (CentralAuthService.instance.token != null) await api.claimBilling();
      } catch (_) {}
      final s = await api.getBillingStatus();
      isPro = s['pro'] == true;
      apiCredits = (s['api_credits'] as num?)?.toInt() ?? 0;
      final subs = s['subscriptions'] as Map<String, dynamic>?;
      final ai = subs?['acronous_ai'] as Map<String, dynamic>?;
      activePlanId = ai?['plan'] as String? ?? s['ai_plan'] as String?;
      final u = s['usage'];
      if (u is Map<String, dynamic>) usage = u;
      final tq = s['tier_quotas'];
      if (tq is Map<String, dynamic>) tierQuotas = tq;
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
  /// quietly; failures set [error]. API-order 404/502 falls through to the
  /// hosted Razorpay checkout so payment buttons never dead-end.
  /// No sign-in wall: signed-out buyers go straight to the hosted Razorpay
  /// checkout (email links the plan on next sign-in).
  Future<bool> buy(AiPlan plan) async {
    if (busyPlanId != null) return false;
    if (CentralAuthService.instance.token == null) {
      await launchUrl(
        Uri.parse(checkoutFallbackUrl(plan: plan.id)),
        mode: LaunchMode.externalApplication,
      );
      return true;
    }
    busyPlanId = plan.id;
    error = null;
    notifyListeners();
    try {
      Map<String, dynamic> order;
      try {
        order = await api.createBillingOrder(plan: plan.id);
      } catch (e) {
        final code = e is ApiException ? e.statusCode : 0;
        final m = e.toString();
        final unreachable = code == 404 || code == 502 || code == 503 ||
            m.contains('returned a page') || m.contains('temporarily unavailable') ||
            m.contains('Service not found') || m.contains('Bad gateway');
        if (unreachable) {
          await launchUrl(
            Uri.parse(checkoutFallbackUrl(
                token: CentralAuthService.instance.token, plan: plan.id)),
            mode: LaunchMode.externalApplication,
          );
          try {
            await Future.delayed(const Duration(seconds: 2));
            await refresh();
          } catch (_) {}
          return true;
        }
        rethrow;
      }
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
        // Desktop: complete payment on the hosted auto-checkout page, which
        // verifies server-side. Refresh on return so paid users don't loop.
        await launchUrl(
          Uri.parse(checkoutFallbackUrl(
              token: CentralAuthService.instance.token, plan: plan.id)),
          mode: LaunchMode.externalApplication,
        );
        try {
          await Future.delayed(const Duration(seconds: 2));
          await refresh();
        } catch (_) {}
        return true;
      }
      await api.verifyBillingPayment(
        orderId: g.orderId,
        paymentId: g.paymentId,
        signature: g.signature,
        plan: plan.id,
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
      if (e.statusCode == 401) {
        return 'Your session expired. Please sign in again to continue.';
      }
      if (e.statusCode == 402) {
        return ApiClient.paywallMessage(e);
      }
      if (e.statusCode == 429) {
        return 'Too many requests. Please wait a moment and try again.';
      }
      if (e.statusCode >= 500) {
        return 'Payment service is temporarily unavailable. Please try again in a bit.';
      }
      // Use the server's message if it's user-friendly (not a raw code)
      final msg = e.message;
      if (msg.isNotEmpty && !msg.contains('statusCode') && !msg.contains('ApiException')) {
        return msg;
      }
    }
    final m = e.toString().replaceFirst('StateError: ', '');
    if (m.startsWith('Exception: ')) return m.substring('Exception: '.length);
    if (m.startsWith('Bad state: ')) return m.substring('Bad state: '.length);
    return m.isEmpty ? 'Payment failed. Please try again.' : m;
  }
}
