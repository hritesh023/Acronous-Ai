// Single entry point for the REAL Razorpay gateway from Flutter.
//   Web             → Razorpay checkout.js via window.AcronousPay bridge.
//   Android / iOS   → Razorpay native SDK (UPI intent, cards, netbanking).
//   Desktop         → throws UnsupportedError; callers fall back to the hosted
//                     auto-checkout page (acronous.com/checkout.html).
// The order is always created server-side first; no secret ever enters the app.
import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:razorpay_flutter/razorpay_flutter.dart';

import 'pay_bridge.dart';
import 'pay_result.dart';

Future<GatewayResult> openRazorpayCheckout({
  required String keyId,
  required int amountPaise,
  required String orderId,
  required String planLabel,
  required String themeColor,
}) async {
  if (kIsWeb) {
    if (!webCheckoutAvailable) {
      throw UnsupportedError('Web checkout unavailable');
    }
    final r = await openWebCheckout(
      keyId: keyId,
      amountPaise: amountPaise,
      orderId: orderId,
      description: planLabel,
      themeColor: themeColor,
    );
    final paymentId = r['razorpay_payment_id'] ?? '';
    final signature = r['razorpay_signature'] ?? '';
    if (paymentId.isEmpty || signature.isEmpty) {
      throw StateError('Payment verification data missing. Please try again.');
    }
    return GatewayResult(
      orderId: r['razorpay_order_id'] ?? orderId,
      paymentId: paymentId,
      signature: signature,
    );
  }

  if (defaultTargetPlatform == TargetPlatform.android ||
      defaultTargetPlatform == TargetPlatform.iOS) {
    final rzp = Razorpay();
    try {
      final completer = Completer<GatewayResult>();
      void onSuccess(PaymentSuccessResponse r) {
        if (completer.isCompleted) return;
        if ((r.paymentId ?? '').isEmpty || (r.signature ?? '').isEmpty) {
          completer.completeError(StateError(
              'Payment verification data missing. Please try again.'));
          return;
        }
        completer.complete(GatewayResult(
          orderId: r.orderId ?? orderId,
          paymentId: r.paymentId!,
          signature: r.signature!,
        ));
      }

      void onError(PaymentFailureResponse r) {
        if (completer.isCompleted) return;
        // Razorpay Android code 2 == user cancelled the payment screen.
        if (r.code == 2) {
          completer.completeError(PaymentCancelled());
          return;
        }
        completer.completeError(StateError(
            (r.message?.isNotEmpty ?? false)
                ? r.message!
                : 'Payment failed. No money was deducted for a failed payment.'));
      }

      // External wallets hand off outside the SDK; the success/error event
      // still fires afterwards, so just keep waiting for it.
      void onWallet(ExternalWalletResponse r) {}
      rzp.on(Razorpay.EVENT_PAYMENT_SUCCESS, onSuccess);
      rzp.on(Razorpay.EVENT_PAYMENT_ERROR, onError);
      rzp.on(Razorpay.EVENT_EXTERNAL_WALLET, onWallet);
      rzp.open({
        'key': keyId,
        'amount': amountPaise,
        'currency': 'INR',
        'name': 'Acronous',
        'description': planLabel,
        'order_id': orderId,
        'theme.color': themeColor,
      });
      return await completer.future;
    } finally {
      rzp.clear();
    }
  }

  throw UnsupportedError('Native checkout unavailable on this platform');
}
