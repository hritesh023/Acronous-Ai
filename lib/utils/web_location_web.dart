import 'package:web/web.dart' as web;

String? getWebLocationHref() => web.window.location.href;

void replaceWebHistoryState(String url) {
  web.window.history.replaceState(null, '', url);
}

void setWebLocationHref(String url) {
  web.window.location.href = url;
}
