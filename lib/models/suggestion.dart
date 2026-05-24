class Suggestion {
  final String icon;
  final String title;
  final String desc;
  final String query;

  Suggestion({
    required this.icon,
    required this.title,
    required this.desc,
    required this.query,
  });

  factory Suggestion.fromJson(Map<String, dynamic> json) => Suggestion(
        icon: json['icon'] as String? ?? '',
        title: json['title'] as String? ?? '',
        desc: json['desc'] as String? ?? '',
        query: json['query'] as String? ?? '',
      );
}
