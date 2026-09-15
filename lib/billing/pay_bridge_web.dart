// Web implementation: drives window.AcronousPay (defined in web/index.html,
// which lazily loads Razorpay checkout.js) through dart:js_interop.
import 'dart:async';
import 'dart:js_interop';
import 'dart:js_interop_unsafe';

import 'pay_result.dart';

bool get webCheckoutAvailable => true;

@JS('AcronousPay')
external JSObject? get _payBridge;

String _str(JSObject o, String key) =>
    ((o.getProperty(key.toJS) as JSString?)?.toDart ?? '');

Future<Map<String, String>> openWebCheckout({
  required String keyId,
  required int amountPaise,
  required String orderId,
  required String description,
  required String themeColor,
}) {
  final completer = Completer<Map<String, String>>();
  final bridge = _payBridge;
  if (bridge == null) {
    return Future.error(StateError(
        'Payment gateway failed to load. Check your connection and retry.'));
  }
  void fail(Object e) {
    if (!completer.isCompleted) completer.completeError(e);
  }

  late final JSFunction onOk;
  late final JSFunction onErr;
  onOk = ((JSAny? r) {
    try {
      final o = r as JSObject;
      if (!completer.isCompleted) {
        completer.complete({
          'razorpay_order_id': _str(o, 'razorpay_order_id'),
          'razorpay_payment_id': _str(o, 'razorpay_payment_id'),
          'razorpay_signature': _str(o, 'razorpay_signature'),
        });
      }
    } catch (e) {
      fail(e);
    }
  }).toJS;
  onErr = ((JSAny? r) {
    try {
      final o = r as JSObject?;
      final cancelled =
          (o?.getProperty('cancelled'.toJS) as JSBoolean?)?.toDart ?? false;
      if (cancelled) {
        fail(PaymentCancelled());
        return;
      }
      final msg = o != null
          ? _str(o, 'message')
          : 'Payment failed. Please try again.';
      fail(StateError(msg.isEmpty ? 'Payment failed. Please try again.' : msg));
    } catch (e) {
      fail(e);
    }
  }).toJS;

  final opts = <String, Object>{
    'key': keyId,
    'amount': amountPaise,
    'currency': 'INR',
    'order_id': orderId,
    'description': description,
    'color': themeColor,
  }.jsify()!;
  try {
    bridge.callMethod('open'.toJS, opts, onOk, onErr);
  } catch (e) {
    fail(e);
  }
  return completer.future;
}
