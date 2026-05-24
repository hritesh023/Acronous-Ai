
enum IntentType {
  call,
  openApp,
  openLink,
  sendMessage,
  sendWhatsApp,
  search,
  aiQuery,
}

class IntentAction {
  final IntentType type;
  final Map<String, String> params;

  const IntentAction({required this.type, required this.params});

  @override
  String toString() => 'IntentAction($type, $params)';
}

class IntentProcessor {
  const IntentProcessor();

  IntentAction process(String text) {
    final trimmed = text.trim();
    if (trimmed.isEmpty) {
      return IntentAction(type: IntentType.aiQuery, params: {'query': ''});
    }

    if (_isUrl(trimmed)) {
      return IntentAction(
        type: IntentType.openLink,
        params: {'url': _normalizeUrl(trimmed)},
      );
    }

    IntentAction? action;
    action ??= _parseCall(trimmed);
    action ??= _parseMessage(trimmed);
    action ??= _parseWhatsApp(trimmed);
    action ??= _parseOpen(trimmed);
    action ??= _parseSearch(trimmed);

    return action ?? IntentAction(type: IntentType.aiQuery, params: {'query': trimmed});
  }

  IntentAction? _parseCall(String text) {
    final patterns = [
      r'^(?:call|dial|phone|ring)\s+(?:the\s+)?(?:number\s+)?(.+)$',
      r'^(?:make|place)\s+(?:a\s+)?(?:phone\s+|video\s+)?call\s+to\s+(.+)$',
    ];
    for (final pattern in patterns) {
      final match = RegExp(pattern, caseSensitive: false).firstMatch(text);
      if (match != null) {
        return IntentAction(
          type: IntentType.call,
          params: {'contact': match.group(1)!.trim()},
        );
      }
    }
    return null;
  }

  IntentAction? _parseMessage(String text) {
    final patterns = [
      r'^(?:send|text|message)\s+(?:a\s+)?(?:message|text|sms)\s+to\s+(.+?)(?:\s+(?:saying|with\s+message|that\s+says?|message\s+is|:)\s+(.+))?$',
      r'^(?:text|message)\s+(.+?)(?:\s+(?:saying|about|:)\s+(.+))?$',
    ];
    for (final pattern in patterns) {
      final match = RegExp(pattern, caseSensitive: false).firstMatch(text);
      if (match != null) {
        return IntentAction(
          type: IntentType.sendMessage,
          params: {
            'contact': match.group(1)!.trim(),
            if (match.group(2) != null) 'message': match.group(2)!.trim(),
          },
        );
      }
    }
    return null;
  }

  IntentAction? _parseWhatsApp(String text) {
    final match = RegExp(
      r'^(?:send\s+)?(?:whatsapp|wa)\s+(?:a\s+)?(?:message\s+)?(?:to\s+)?(.+?)(?:\s+(?:saying|:)\s+(.+))?$',
      caseSensitive: false,
    ).firstMatch(text);
    if (match != null) {
      return IntentAction(
        type: IntentType.sendWhatsApp,
        params: {
          'contact': match.group(1)!.trim(),
          if (match.group(2) != null) 'message': match.group(2)!.trim(),
        },
      );
    }
    return null;
  }

  IntentAction? _parseOpen(String text) {
    final match = RegExp(
      r'^(?:open|launch|start|run|go\s+to)\s+(.+)$',
      caseSensitive: false,
    ).firstMatch(text);
    if (match != null) {
      final target = match.group(1)!.trim();
      if (_isUrl(target)) {
        return IntentAction(
          type: IntentType.openLink,
          params: {'url': _normalizeUrl(target)},
        );
      }
      return IntentAction(
        type: IntentType.openApp,
        params: {'target': target},
      );
    }
    return null;
  }

  IntentAction? _parseSearch(String text) {
    final match = RegExp(
      r'^(?:search|look\s+up|find|google)\s+(?:for\s+)?(.+)$',
      caseSensitive: false,
    ).firstMatch(text);
    if (match != null) {
      return IntentAction(
        type: IntentType.search,
        params: {'query': match.group(1)!.trim()},
      );
    }
    return null;
  }

  bool _isUrl(String text) {
    return RegExp(
      r'^[a-zA-Z][a-zA-Z0-9.-]*\.[a-zA-Z]{2,}(?:/[^\s]*)?$',
    ).hasMatch(text) ||
        text.startsWith('http://') ||
        text.startsWith('https://');
  }

  String _normalizeUrl(String text) {
    if (text.startsWith('http://') || text.startsWith('https://')) return text;
    return 'https://$text';
  }
}
