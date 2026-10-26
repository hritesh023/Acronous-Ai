import 'dart:js_interop';
import 'package:web/web.dart' as web;
import 'dart:async';

Future<List<double>?> getBrowserGps() async {
  final completer = Completer<List<double>?>();
  try {
    final geoObj = web.window.navigator.geolocation;
    geoObj.getCurrentPosition(
      ((web.GeolocationPosition pos) {
        if (!completer.isCompleted) {
          completer.complete([
            pos.coords.latitude,
            pos.coords.longitude,
          ]);
        }
      }).toJS,
      ((web.GeolocationPositionError err) {
        if (!completer.isCompleted) {
          completer.complete(null);
        }
      }).toJS,
    );
    return completer.future.timeout(const Duration(seconds: 15));
  } catch (_) {
    return null;
  }
}
