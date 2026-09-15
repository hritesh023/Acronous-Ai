// Shared result/exception types for in-app Razorpay checkout.
class GatewayResult {
  final String orderId;
  final String paymentId;
  final String signature;
  const GatewayResult({
    required this.orderId,
    required this.paymentId,
    required this.signature,
  });
}

/// User closed the gateway without paying. Not an error — no toast needed.
class PaymentCancelled implements Exception {
  @override
  String toString() => 'Payment cancelled';
}
