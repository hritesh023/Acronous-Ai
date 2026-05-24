import 'package:flutter/material.dart';

class MarkdownRenderer extends StatelessWidget {
  final String content;

  const MarkdownRenderer({super.key, required this.content});

  @override
  Widget build(BuildContext context) {
    final html = _parseMarkdown(content);
    return SizedBox(
      width: double.infinity,
      child: _buildWidgetTree(html, context),
    );
  }

  List<_MdNode> _parseMarkdown(String text) {
    final nodes = <_MdNode>[];
    final lines = text.split('\n');
    _MdNode? current;
    bool inCodeBlock = false;
    final codeLines = <String>[];
    String codeLang = '';

    for (final line in lines) {
      if (inCodeBlock) {
        if (line.startsWith('```')) {
          inCodeBlock = false;
          nodes.add(_MdNode(
            type: 'code_block',
            text: codeLines.join('\n'),
            lang: codeLang,
          ));
          codeLines.clear();
          codeLang = '';
        } else {
          codeLines.add(line);
        }
        continue;
      }

      if (line.startsWith('```')) {
        inCodeBlock = true;
        codeLang = line.replaceAll('```', '').trim();
        continue;
      }

      if (line.trim().isEmpty) {
        if (current != null) {
          nodes.add(current);
          current = null;
        }
        continue;
      }

      if (line.startsWith('### ')) {
        if (current != null) nodes.add(current);
        current = _MdNode(type: 'h3', text: line.substring(4));
        continue;
      }
      if (line.startsWith('## ')) {
        if (current != null) nodes.add(current);
        current = _MdNode(type: 'h2', text: line.substring(3));
        continue;
      }
      if (line.startsWith('# ')) {
        if (current != null) nodes.add(current);
        current = _MdNode(type: 'h1', text: line.substring(2));
        continue;
      }
      if (RegExp(r'^>\s').hasMatch(line)) {
        if (current?.type != 'blockquote') {
          if (current != null) nodes.add(current);
          current = _MdNode(type: 'blockquote', text: '');
        }
        current!.text += '${line.replaceFirst(RegExp(r'^>\s?'), '')}\n';
        continue;
      }
      if (RegExp(r'^-\s').hasMatch(line) || RegExp(r'^\*\s').hasMatch(line)) {
        if (current?.type != 'unordered_list') {
          if (current != null) nodes.add(current);
          current = _MdNode(type: 'unordered_list', text: '');
        }
        current!.text +=
            '• ${line.replaceFirst(RegExp(r'^[-*]\s'), '')}\n';
        continue;
      }
      if (RegExp(r'^\d+\.\s').hasMatch(line)) {
        if (current?.type != 'ordered_list') {
          if (current != null) nodes.add(current);
          current = _MdNode(type: 'ordered_list', text: '');
        }
        current!.text += '$line\n';
        continue;
      }
      if (RegExp(r'^\|.+\|$').hasMatch(line)) {
        if (line.contains('---') && current?.type == 'table_header') {
          continue;
        }
        if (current?.type == 'table_header' || current?.type == 'table') {
          current!.text += '$line\n';
          current.type = 'table';
        } else {
          if (current != null) nodes.add(current);
          current = _MdNode(type: 'table_header', text: '$line\n');
        }
        continue;
      }

      if (current != null && current.type == 'paragraph') {
        current.text += ' $line';
      } else {
        if (current != null) nodes.add(current);
        current = _MdNode(type: 'paragraph', text: line);
      }
    }

    if (inCodeBlock) {
      nodes.add(_MdNode(
        type: 'code_block',
        text: codeLines.join('\n'),
        lang: codeLang,
      ));
    }
    if (current != null) nodes.add(current);

    return nodes;
  }

  Widget _buildWidgetTree(List<_MdNode> nodes, BuildContext context) {
    final children = <Widget>[];
    for (final node in nodes) {
      children.add(_buildNode(node, context));
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: children,
    );
  }

  Widget _buildNode(_MdNode node, BuildContext context) {
    switch (node.type) {
      case 'h1':
        return Padding(
          padding: const EdgeInsets.only(top: 16, bottom: 8),
          child: Text(
            _applyInlineFormatting(node.text),
            style: Theme.of(context).textTheme.headlineSmall?.copyWith(
              fontWeight: FontWeight.w700,
            ),
          ),
        );
      case 'h2':
        return Padding(
          padding: const EdgeInsets.only(top: 14, bottom: 6),
          child: Text(
            _applyInlineFormatting(node.text),
            style: Theme.of(context).textTheme.titleLarge?.copyWith(
              fontWeight: FontWeight.w700,
            ),
          ),
        );
      case 'h3':
        return Padding(
          padding: const EdgeInsets.only(top: 12, bottom: 6),
          child: Text(
            _applyInlineFormatting(node.text),
            style: Theme.of(context).textTheme.titleMedium?.copyWith(
              fontWeight: FontWeight.w600,
            ),
          ),
        );
      case 'code_block':
        return Container(
          width: double.infinity,
          margin: const EdgeInsets.symmetric(vertical: 12),
          decoration: BoxDecoration(
            color: const Color(0xFF12122A),
            border: Border.all(color: const Color(0x14FFFFFF)),
            borderRadius: BorderRadius.circular(10),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (node.lang.isNotEmpty)
                Container(
                  width: double.infinity,
                  padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
                  decoration: BoxDecoration(
                    color: const Color(0xFF1C1C35),
                    border: const Border(
                      bottom: BorderSide(color: Color(0x14FFFFFF)),
                    ),
                  ),
                  child: Text(
                    node.lang,
                    style: const TextStyle(
                      fontSize: 11,
                      fontWeight: FontWeight.w600,
                      color: Color(0xFF505070),
                      letterSpacing: 0.5,
                    ),
                  ),
                ),
              SingleChildScrollView(
                scrollDirection: Axis.horizontal,
                padding: const EdgeInsets.all(14),
                child: SelectableText(
                  node.text,
                  style: const TextStyle(
                    fontFamily: 'monospace',
                    fontSize: 13,
                    color: Color(0xFFA78BFA),
                    height: 1.55,
                  ),
                ),
              ),
            ],
          ),
        );
      case 'blockquote':
        return Container(
          width: double.infinity,
          margin: const EdgeInsets.symmetric(vertical: 8),
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: const Color(0x1E7C3AED),
            border: const Border(
              left: BorderSide(color: Color(0xFF7C3AED), width: 3),
            ),
            borderRadius: BorderRadius.circular(4),
          ),
          child: Text(
            _applyInlineFormatting(node.text.trim()),
            style: Theme.of(context).textTheme.bodyMedium?.copyWith(
              color: const Color(0xFFB0B0C8),
            ),
          ),
        );
      case 'unordered_list':
        return Padding(
          padding: const EdgeInsets.symmetric(vertical: 4),
          child: _buildListItems(node.text, context),
        );
      case 'ordered_list':
        return Padding(
          padding: const EdgeInsets.symmetric(vertical: 4),
          child: _buildListItems(node.text, context),
        );
      case 'table':
        return _buildTable(node.text, context);
      default:
        return Padding(
          padding: const EdgeInsets.only(bottom: 8),
          child: SelectableText.rich(
            TextSpan(
              style: const TextStyle(fontSize: 15, height: 1.65, color: Color(0xFFE8E8F0)),
              children: _buildInlineSpans(node.text),
            ),
          ),
        );
    }
  }

  Widget _buildListItems(String text, BuildContext context) {
    final items = text.split('\n').where((l) => l.trim().isNotEmpty).toList();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: items.map((item) {
        final isOrdered = RegExp(r'^\d+\.').hasMatch(item);
        final prefix = isOrdered ? item.split('.').first : '•';
        final content = isOrdered ? item.replaceFirst(RegExp(r'^\d+\.\s'), '') : item.replaceFirst(RegExp(r'^•\s'), '');
        return Padding(
          padding: const EdgeInsets.symmetric(vertical: 2),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              SizedBox(
                width: 24,
                child: Text(
                  prefix,
                  style: Theme.of(context).textTheme.bodyLarge?.copyWith(
                    color: const Color(0xFF707090),
                  ),
                ),
              ),
              Expanded(
                child: RichText(
                  text: TextSpan(
                    style: const TextStyle(fontSize: 15, height: 1.65, color: Color(0xFFE8E8F0)),
                    children: _buildInlineSpans(content),
                  ),
                ),
              ),
            ],
          ),
        );
      }).toList(),
    );
  }

  Widget _buildTable(String text, BuildContext context) {
    final rows = text.split('\n').where((l) => l.trim().isNotEmpty).toList();
    if (rows.isEmpty) return const SizedBox.shrink();

    final tableRows = <TableRow>[];
    for (int i = 0; i < rows.length; i++) {
      if (rows[i].contains('---')) continue;
      final cells = rows[i]
          .split('|')
          .where((c) => c.trim().isNotEmpty)
          .map((c) => c.trim())
          .toList();
      tableRows.add(TableRow(
        children: cells
            .map((c) => Padding(
                  padding: const EdgeInsets.all(8),
                  child: Text(
                    c,
                    style: TextStyle(
                      fontWeight: i == 0 ? FontWeight.w600 : FontWeight.normal,
                      fontSize: 13,
                      color: i == 0
                          ? const Color(0xFFB0B0C8)
                          : const Color(0xFFE8E8F0),
                    ),
                  ),
                ))
            .toList(),
      ));
    }

    return Container(
      width: double.infinity,
      margin: const EdgeInsets.symmetric(vertical: 12),
      decoration: BoxDecoration(
        border: Border.all(color: const Color(0x14FFFFFF)),
        borderRadius: BorderRadius.circular(10),
      ),
      child: SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        child: Table(
          border: TableBorder(
            horizontalInside: BorderSide(color: const Color(0x14FFFFFF)),
          ),
          columnWidths: _calculateColumnWidths(rows),
          children: tableRows,
        ),
      ),
    );
  }

  Map<int, TableColumnWidth> _calculateColumnWidths(List<String> rows) {
    final widths = <int, double>{};
    for (final row in rows) {
      if (row.contains('---')) continue;
      final cells = row.split('|').where((c) => c.trim().isNotEmpty).toList();
      for (int i = 0; i < cells.length; i++) {
        final w = cells[i].trim().length * 10.0;
        if (!widths.containsKey(i) || w > widths[i]!) {
          widths[i] = w.clamp(60.0, 200.0);
        }
      }
    }
    return widths.map((k, v) => MapEntry(k, FixedColumnWidth(v)));
  }

  String _applyInlineFormatting(String text) {
    return text
        .replaceAllMapped(RegExp(r'\*\*\*(.*?)\*\*\*'), (m) => m.group(1)!)
        .replaceAllMapped(RegExp(r'\*\*(.*?)\*\*'), (m) => m.group(1)!)
        .replaceAllMapped(RegExp(r'\*(.*?)\*'), (m) => m.group(1)!)
        .replaceAllMapped(RegExp(r'~~(.*?)~~'), (m) => m.group(1)!)
        .replaceAllMapped(RegExp(r'`([^`]+)`'), (m) => m.group(1)!)
        .replaceAllMapped(RegExp(r'\[([^\]]+)\]\([^)]+\)'), (m) => m.group(1)!);
  }

  List<InlineSpan> _buildInlineSpans(String text) {
    final spans = <InlineSpan>[];
    final regex = RegExp(
        r'(\*\*\*(.*?)\*\*\*|\*\*(.*?)\*\*|\*(.*?)\*|~~(.*?)~~|`([^`]+)`|\[([^\]]+)\]\(([^)]+)\)|!\[([^\]]*)\]\(([^)]+)\))');
    int lastEnd = 0;

    for (final match in regex.allMatches(text)) {
      if (match.start > lastEnd) {
        spans.add(TextSpan(
          text: text.substring(lastEnd, match.start),
          style: const TextStyle(fontSize: 15, height: 1.65, color: Color(0xFFE8E8F0)),
        ));
      }

      if (match.group(1)?.startsWith('***') == true) {
        spans.add(TextSpan(
          text: match.group(2),
          style: const TextStyle(fontSize: 15, height: 1.65, color: Color(0xFFE8E8F0), fontWeight: FontWeight.w700, fontStyle: FontStyle.italic),
        ));
      } else if (match.group(1)?.startsWith('**') == true) {
        spans.add(TextSpan(
          text: match.group(3),
          style: const TextStyle(fontSize: 15, height: 1.65, color: Color(0xFFE8E8F0), fontWeight: FontWeight.w700),
        ));
      } else if (match.group(1)?.startsWith('*') == true) {
        spans.add(TextSpan(
          text: match.group(4),
          style: const TextStyle(fontSize: 15, height: 1.65, color: Color(0xFFE8E8F0), fontStyle: FontStyle.italic),
        ));
      } else if (match.group(1)?.startsWith('~~') == true) {
        spans.add(TextSpan(
          text: match.group(5),
          style: const TextStyle(fontSize: 15, height: 1.65, color: Color(0xFF707090), decoration: TextDecoration.lineThrough),
        ));
      } else if (match.group(1)?.startsWith('`') == true) {
        spans.add(WidgetSpan(
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
            decoration: BoxDecoration(
              color: const Color(0xFF12122A),
              borderRadius: BorderRadius.circular(4),
            ),
            child: Text(
              match.group(6)!,
              style: const TextStyle(fontSize: 13, color: Color(0xFFA78BFA), fontFamily: 'monospace'),
            ),
          ),
        ));
      } else if (match.group(1)?.startsWith('[') == true) {
        spans.add(WidgetSpan(
          child: GestureDetector(
            onTap: () {},
            child: Text(
              match.group(7)!,
              style: const TextStyle(fontSize: 15, height: 1.65, color: Color(0xFF7C3AED), decoration: TextDecoration.underline),
            ),
          ),
        ));
      }

      lastEnd = match.end;
    }

    if (lastEnd < text.length) {
      spans.add(TextSpan(
        text: text.substring(lastEnd),
        style: const TextStyle(fontSize: 15, height: 1.65, color: Color(0xFFE8E8F0)),
      ));
    }

    return spans;
  }
}

class _MdNode {
  String type;
  String text;
  String lang;

  _MdNode({required this.type, required this.text, this.lang = ''});
}
