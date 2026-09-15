// Web-only Razorpay bridge, reached through pay_bridge.dart's conditional
// export so mobile/desktop builds never compile dart:js_interop.
export 'pay_bridge_stub.dart' if (dart.library.js_interop) 'pay_bridge_web.dart';
