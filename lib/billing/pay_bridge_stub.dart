// Non-web stub: web checkout is unavailable off the browser.
bool get webCheckoutAvailable => false;

Future<Map<String, String>> openWebCheckout({
  required String keyId,
  required int amountPaise,
  required String orderId,
  required String description,
  required String themeColor,
}) =>
    Future.error(
        UnsupportedError('Web checkout is only available in the browser.'));
