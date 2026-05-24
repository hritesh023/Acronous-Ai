import 'dart:typed_data';

enum AttachmentType { image, audio, video, text, pdf, other }

class MessageAttachment {
  final String name;
  final String path;
  final AttachmentType type;
  final Uint8List? bytes;

  MessageAttachment({
    required this.name,
    required this.path,
    required this.type,
    this.bytes,
  });

  String get iconLabel {
    switch (type) {
      case AttachmentType.image:
        return '📷';
      case AttachmentType.audio:
        return '🎵';
      case AttachmentType.video:
        return '🎬';
      case AttachmentType.text:
        return '📄';
      case AttachmentType.pdf:
        return '📕';
      case AttachmentType.other:
        return '📎';
    }
  }

  Map<String, dynamic> toJson() => {
        'name': name,
        'path': path,
        'type': type.name,
      };

  factory MessageAttachment.fromJson(Map<String, dynamic> json) =>
      MessageAttachment(
        name: json['name'] as String,
        path: json['path'] as String,
        type: AttachmentType.values.firstWhere(
          (e) => e.name == json['type'],
          orElse: () => AttachmentType.other,
        ),
      );
}

class ChatMessage {
  final String role;
  final String content;
  final DateTime timestamp;
  final List<MessageAttachment> attachments;
  final String id;
  final String imageData;

  ChatMessage({
    required this.role,
    required this.content,
    DateTime? timestamp,
    List<MessageAttachment>? attachments,
    String? id,
    this.imageData = '',
  }) : timestamp = timestamp ?? DateTime.now(),
       attachments = attachments ?? [],
       id = id ?? DateTime.now().microsecondsSinceEpoch.toString();

  Map<String, dynamic> toJson() => {
        'role': role,
        'content': content,
        'timestamp': timestamp.toIso8601String(),
        'attachments': attachments.map((a) => a.toJson()).toList(),
        'id': id,
        'imageData': imageData,
      };

  factory ChatMessage.fromJson(Map<String, dynamic> json) => ChatMessage(
        role: json['role'] as String,
        content: json['content'] as String,
        timestamp: DateTime.parse(json['timestamp'] as String),
        attachments: (json['attachments'] as List<dynamic>?)
                ?.map((a) =>
                    MessageAttachment.fromJson(a as Map<String, dynamic>))
                .toList() ??
            [],
        id: json['id'] as String?,
        imageData: json['imageData'] as String? ?? '',
      );
}

class Conversation {
  final String id;
  final List<ChatMessage> messages;
  final DateTime createdAt;
  DateTime updatedAt;

  Conversation({
    required this.id,
    List<ChatMessage>? messages,
    DateTime? createdAt,
    DateTime? updatedAt,
  }) : messages = messages ?? [],
       createdAt = createdAt ?? DateTime.now(),
       updatedAt = updatedAt ?? DateTime.now();

  String get displayTitle =>
      messages.isNotEmpty
          ? messages.first.content
              .substring(0, _min(50, messages.first.content.length))
              .replaceAll('\n', ' ')
          : 'New Chat';

  static int _min(int a, int b) => a < b ? a : b;

  Map<String, dynamic> toJson() => {
        'id': id,
        'messages': messages.map((m) => m.toJson()).toList(),
        'createdAt': createdAt.toIso8601String(),
        'updatedAt': updatedAt.toIso8601String(),
      };

  factory Conversation.fromJson(Map<String, dynamic> json) => Conversation(
        id: json['id'] as String,
        messages: (json['messages'] as List<dynamic>)
            .map((m) => ChatMessage.fromJson(m as Map<String, dynamic>))
            .toList(),
        createdAt: DateTime.parse(json['createdAt'] as String),
        updatedAt: DateTime.parse(json['updatedAt'] as String),
      );
}
