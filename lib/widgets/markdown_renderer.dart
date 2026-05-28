import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

class MarkdownRenderer extends StatelessWidget {
  final String content;

  const MarkdownRenderer({super.key, required this.content});

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final nodes = _parseMarkdown(content);
    return SizedBox(
      width: double.infinity,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: nodes.map((node) => _buildNode(node, context, cs)).toList(),
      ),
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
        current!.text += '• ${line.replaceFirst(RegExp(r'^[-*]\s'), '')}\n';
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

  Widget _buildNode(_MdNode node, BuildContext context, ColorScheme cs) {
    switch (node.type) {
      case 'h1':
        return Padding(
          padding: const EdgeInsets.only(top: 16, bottom: 8),
          child: Text(
            _applyInlineFormatting(node.text),
            style: Theme.of(context).textTheme.headlineSmall?.copyWith(
              fontWeight: FontWeight.w700,
              color: cs.onSurface,
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
              color: cs.onSurface,
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
              color: cs.onSurface,
            ),
          ),
        );
      case 'code_block':
        return _buildCodeBlock(node, context, cs);
      case 'blockquote':
        return Container(
          width: double.infinity,
          margin: const EdgeInsets.symmetric(vertical: 8),
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: cs.primary.withValues(alpha: 0.08),
            border: Border(
              left: BorderSide(color: cs.primary, width: 3),
            ),
            borderRadius: BorderRadius.circular(4),
          ),
          child: Text(
            _applyInlineFormatting(node.text.trim()),
            style: Theme.of(context).textTheme.bodyMedium?.copyWith(
              color: cs.onSurfaceVariant,
            ),
          ),
        );
      case 'unordered_list':
        return Padding(
          padding: const EdgeInsets.symmetric(vertical: 4),
          child: _buildListItems(node.text, context, cs),
        );
      case 'ordered_list':
        return Padding(
          padding: const EdgeInsets.symmetric(vertical: 4),
          child: _buildListItems(node.text, context, cs),
        );
      case 'table':
        return _buildTable(node.text, context, cs);
      default:
        return Padding(
          padding: const EdgeInsets.only(bottom: 8),
          child: SelectableText.rich(
            TextSpan(
              style: TextStyle(
                fontSize: 15,
                height: 1.65,
                color: cs.onSurface,
              ),
              children: _buildInlineSpans(node.text, cs),
            ),
          ),
        );
    }
  }

  Widget _buildCodeBlock(_MdNode node, BuildContext context, ColorScheme cs) {
    final isDark = cs.brightness == Brightness.dark;
    final bgColor = isDark ? const Color(0xFF12122A) : const Color(0xFFF0EEF8);
    final headerColor = isDark ? const Color(0xFF1C1C35) : const Color(0xFFE4E1F2);
    final langColor = isDark ? const Color(0xFF505070) : const Color(0xFF6B6890);
    final codeColor = isDark ? const Color(0xFFA78BFA) : const Color(0xFF6D28D9);

    return Container(
      width: double.infinity,
      margin: const EdgeInsets.symmetric(vertical: 10),
      decoration: BoxDecoration(
        color: bgColor,
        border: Border.all(color: cs.outlineVariant.withValues(alpha: 0.3)),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: double.infinity,
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
            decoration: BoxDecoration(
              color: headerColor,
              border: Border(
                bottom: BorderSide(color: cs.outlineVariant.withValues(alpha: 0.2)),
              ),
            ),
            child: Row(
              children: [
                Text(
                  node.lang.isNotEmpty ? node.lang : 'code',
                  style: TextStyle(
                    fontSize: 11,
                    fontWeight: FontWeight.w600,
                    color: langColor,
                    letterSpacing: 0.5,
                  ),
                ),
                const Spacer(),
                GestureDetector(
                  onTap: () {
                    Clipboard.setData(ClipboardData(text: node.text));
                    ScaffoldMessenger.of(context).showSnackBar(
                      SnackBar(
                        content: const Text('Code copied'),
                        behavior: SnackBarBehavior.floating,
                        duration: const Duration(seconds: 1),
                        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                        shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(8),
                        ),
                      ),
                    );
                  },
                  child: Icon(
                    Icons.content_copy_rounded,
                    size: 14,
                    color: langColor,
                  ),
                ),
              ],
            ),
          ),
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.all(14),
            child: SelectableText(
              node.text,
              style: TextStyle(
                fontFamily: 'monospace',
                fontSize: 13,
                color: codeColor,
                height: 1.55,
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildListItems(String text, BuildContext context, ColorScheme cs) {
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
                    color: cs.onSurfaceVariant,
                  ),
                ),
              ),
              Expanded(
                child: RichText(
                  text: TextSpan(
                    style: TextStyle(fontSize: 15, height: 1.65, color: cs.onSurface),
                    children: _buildInlineSpans(content, cs),
                  ),
                ),
              ),
            ],
          ),
        );
      }).toList(),
    );
  }

  Widget _buildTable(String text, BuildContext context, ColorScheme cs) {
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
                      color: i == 0 ? cs.onSurfaceVariant : cs.onSurface,
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
        border: Border.all(color: cs.outlineVariant.withValues(alpha: 0.3)),
        borderRadius: BorderRadius.circular(10),
      ),
      child: SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        child: Table(
          border: TableBorder(
            horizontalInside: BorderSide(color: cs.outlineVariant.withValues(alpha: 0.2)),
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

  List<InlineSpan> _buildInlineSpans(String text, ColorScheme cs) {
    final spans = <InlineSpan>[];
    final regex = RegExp(
        r'(\*\*\*(.*?)\*\*\*|\*\*(.*?)\*\*|\*(.*?)\*|~~(.*?)~~|`([^`]+)`|\[([^\]]+)\]\(([^)]+)\))');
    int lastEnd = 0;

    for (final match in regex.allMatches(text)) {
      if (match.start > lastEnd) {
        spans.add(TextSpan(
          text: text.substring(lastEnd, match.start),
          style: TextStyle(fontSize: 15, height: 1.65, color: cs.onSurface),
        ));
      }

      if (match.group(1)?.startsWith('***') == true) {
        spans.add(TextSpan(
          text: match.group(2),
          style: TextStyle(fontSize: 15, height: 1.65, color: cs.onSurface, fontWeight: FontWeight.w700, fontStyle: FontStyle.italic),
        ));
      } else if (match.group(1)?.startsWith('**') == true) {
        spans.add(TextSpan(
          text: match.group(3),
          style: TextStyle(fontSize: 15, height: 1.65, color: cs.onSurface, fontWeight: FontWeight.w700),
        ));
      } else if (match.group(1)?.startsWith('*') == true) {
        spans.add(TextSpan(
          text: match.group(4),
          style: TextStyle(fontSize: 15, height: 1.65, color: cs.onSurface, fontStyle: FontStyle.italic),
        ));
      } else if (match.group(1)?.startsWith('~~') == true) {
        spans.add(TextSpan(
          text: match.group(5),
          style: TextStyle(fontSize: 15, height: 1.65, color: cs.onSurfaceVariant, decoration: TextDecoration.lineThrough),
        ));
      } else if (match.group(1)?.startsWith('`') == true) {
        final isDark = cs.brightness == Brightness.dark;
        spans.add(WidgetSpan(
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
            decoration: BoxDecoration(
              color: isDark ? const Color(0xFF12122A) : const Color(0xFFF0EEF8),
              borderRadius: BorderRadius.circular(4),
            ),
            child: Text(
              match.group(6)!,
              style: TextStyle(
                fontSize: 13,
                color: isDark ? const Color(0xFFA78BFA) : const Color(0xFF6D28D9),
                fontFamily: 'monospace',
              ),
            ),
          ),
        ));
      } else if (match.group(1)?.startsWith('[') == true) {
        spans.add(WidgetSpan(
          child: GestureDetector(
            onTap: () {},
            child: Text(
              match.group(7)!,
              style: TextStyle(fontSize: 15, height: 1.65, color: cs.primary, decoration: TextDecoration.underline),
            ),
          ),
        ));
      }

      lastEnd = match.end;
    }

    if (lastEnd < text.length) {
      spans.add(TextSpan(
        text: text.substring(lastEnd),
        style: TextStyle(fontSize: 15, height: 1.65, color: cs.onSurface),
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
