import 'dart:ui' show PointerDeviceKind;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

class MarkdownRenderer extends StatelessWidget {
  final String content;

  const MarkdownRenderer({super.key, required this.content});

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final fixed = _preprocessCodeBlocks(content);
    final nodes = _parseMarkdown(fixed);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: nodes.map((node) => _buildNode(node, context, cs)).toList(),
    );
  }

  static final _codeIndicator = RegExp(
    r'[{}();=]|=>|===|!==|(?:public|private|class|def|function|import|from|const|let|var|if|for|while|return)\b',
  );

  String _preprocessCodeBlocks(String text) {
    // Step 0: If the entire response looks like raw code without fences, wrap it
    text = _wrapBareCode(text);
    // Step 0.5: Expand compressed code blocks (few lines with long content)
    text = _expandCompressedCodeBlocks(text);
    // Step 0.7: Unwrap code blocks that contain natural language prose
    text = _unwrapProseCodeBlocks(text);
    final lines = text.split('\n');
    final result = <String>[];
    int i = 0;
    while (i < lines.length) {
      final line = lines[i];
      if (line.trim() == '```') {
        // Check if this is an orphaned closing fence
        bool hasCodeAbove = false;
        for (int j = result.length - 1; j >= 0 && j >= result.length - 80; j--) {
          final prev = result[j].trim();
          if (prev.isEmpty || prev.startsWith('```')) continue;
          if (_codeIndicator.hasMatch(prev) || prev.length > 80 ||
              (prev.contains('(') && prev.contains(')'))) {
            hasCodeAbove = true;
            break;
          }
        }
        bool hasCodeBelow = false;
        for (int j = i + 1; j < lines.length && j < i + 80; j++) {
          final next = lines[j].trim();
          if (next.isEmpty || next == '```') continue;
          if (_codeIndicator.hasMatch(next) || next.length > 80 ||
              (next.contains('(') && next.contains(')'))) {
            hasCodeBelow = true;
            break;
          }
        }
        if (hasCodeAbove && !hasCodeBelow) {
          // Orphaned closing fence — skip it
          i++;
          continue;
        }
      }
      result.add(line);
      i++;
    }
    return result.join('\n');
  }

  /// Unwrap code blocks that contain natural language prose instead of code.
  /// The LLM sometimes wraps general knowledge answers in ``` blocks.
  String _unwrapProseCodeBlocks(String text) {
    return text.replaceAllMapped(
      RegExp(r'```(\w*)\n([\s\S]*?)```', multiLine: true),
      (match) {
        final lang = match.group(1) ?? '';
        final code = match.group(2) ?? '';
        final trimmed = code.trim();
        if (trimmed.isEmpty) return match.group(0)!;

        final lines = trimmed.split('\n');
        final nonEmptyLines = lines.where((l) => l.trim().isNotEmpty).toList();
        if (nonEmptyLines.isEmpty) return match.group(0)!;

        // If the content has natural language patterns, it's likely prose
        final fullText = nonEmptyLines.join(' ');
        final hasNaturalLanguage = RegExp(
          r'\b(?:the|a|an|is|are|was|were|has|have|had|can|could|would|should|will|shall|may|might|must|for|and|but|or|not|with|from|to|in|on|at|by|as|of|that|this|which|who|where|when|how|what|why|because|since|while|although|however|therefore|moreover|furthermore|nevertheless|consequently|accordingly)\b',
          caseSensitive: false,
        ).hasMatch(fullText);

        if (!hasNaturalLanguage) return match.group(0)!;

        // Count prose vs code lines
        int proseLineCount = 0;
        int codeLikeCount = 0;
        for (final line in nonEmptyLines) {
          final l = line.trim();
          // Strong code indicators
          if (RegExp(r'[{}();=]').hasMatch(l) && l.length > 10) {
            codeLikeCount++;
            continue;
          }
          if (RegExp(r'^(?:#include|#define|import |from |export |const |let |var |function |class |def |public |private |protected |static |void |int |float |double |return |if |else|for |while |switch |case |try |catch )').hasMatch(l)) {
            codeLikeCount++;
            continue;
          }
          if (RegExp(r'^\s*(?://|#|/\*|\*/|<!--)').hasMatch(l)) {
            codeLikeCount++;
            continue;
          }
          // Prose indicators
          if (l.length > 15 && RegExp(r'^[A-Z]').hasMatch(l) && RegExp(r'[.!?]\s*$').hasMatch(l)) {
            proseLineCount++;
            continue;
          }
          if (RegExp(r'^[-•*]\s+[A-Z]').hasMatch(l)) {
            proseLineCount++;
            continue;
          }
          if (l.length > 30 && !RegExp(r'[{};=<>]').hasMatch(l) && RegExp(r'[a-z]{4,}').hasMatch(l)) {
            proseLineCount++;
          }
        }

        final total = nonEmptyLines.length;
        final proseRatio = total > 0 ? proseLineCount / total : 0;
        final codeRatio = total > 0 ? codeLikeCount / total : 0;

        // Unwrap if majority is prose or very low code ratio
        // Preserve surrounding newlines so adjacent text doesn't merge
        if (proseRatio > 0.35 || codeRatio < 0.30) {
          return '\n$trimmed\n';
        }
        return match.group(0)!;
      },
    );
  }

  /// Detects raw code that has no markdown fences and wraps it in ``` blocks.
  /// This handles the case where the LLM returns code starting with { or
  /// other code tokens without surrounding ``` fences.
  String _wrapBareCode(String text) {
    final trimmed = text.trim();
    if (trimmed.isEmpty) return text;
    // Already has code fences — nothing to do
    if (trimmed.contains('```')) return text;

    final lines = trimmed.split('\n');
    // Check if content looks like code (not prose)
    // Require structural syntax indicators, not just keywords
    // (words like "if", "for", "return" appear in natural language)
    final hasStructuralSyntax = RegExp(r'[{}();=]|=>|===|!==');
    int codeLineCount = 0;
    int totalLines = 0;
    for (final line in lines) {
      final l = line.trim();
      if (l.isEmpty) continue;
      totalLines++;
      // A line is only "code" if it has structural syntax OR is a comment/pragma
      // Keywords alone are NOT enough — "if you have a question" is not code
      if (hasStructuralSyntax.hasMatch(l) ||
          l.startsWith('//') ||
          l.startsWith('#!/') ||
          l.startsWith('/*') ||
          l.startsWith('* ') ||
          (l.startsWith('{') && l.endsWith('}')) ||
          (l.startsWith('(') && l.endsWith(')'))) {
        codeLineCount++;
      }
    }
    // Very strict: >80% of lines must have structural syntax to auto-wrap
    // This prevents false positives on natural language with occasional keywords
    if (totalLines >= 2 && codeLineCount / totalLines > 0.8) {
      final lang = _detectLanguage(trimmed);
      return '```$lang\n$trimmed\n```';
    }
    // Single line: only wrap if it's long AND has braces/semicolons (actual code)
    if (totalLines == 1 && codeLineCount == 1 && trimmed.length > 80 &&
        (trimmed.contains('{') || trimmed.contains(';'))) {
      final lang = _detectLanguage(trimmed);
      return '```$lang\n$trimmed\n```';
    }
    return text;
  }

  /// Expands compressed code blocks where code is crammed into few lines.
  /// E.g., ```java\n{ line1(); line2(); }\n``` → properly formatted code.
  String _expandCompressedCodeBlocks(String text) {
    return text.replaceAllMapped(
      RegExp(r'```(\w*)\n([\s\S]*?)```', multiLine: true),
      (match) {
        final lang = match.group(1) ?? '';
        final code = match.group(2) ?? '';
        final trimmed = code.trim();
        if (trimmed.isEmpty) return match.group(0)!;

        // NEVER touch Python — it is indentation-based and any brace/semicolon
        // rewriting destroys its structure
        final lowerLang = lang.toLowerCase();
        if (lowerLang == 'python' || lowerLang == 'py') {
          return match.group(0)!;
        }

        final lines = trimmed.split('\n');
        final nonEmpty = lines.where((l) => l.trim().isNotEmpty).toList();
        if (nonEmpty.isEmpty) return match.group(0)!;
        final maxLineLen = nonEmpty.map((l) => l.length).reduce((a, b) => a > b ? a : b);

        // Already properly formatted: multiple short lines with good indentation
        final hasIndentation = nonEmpty.any((l) => l.startsWith('  ') || l.startsWith('    '));
        if (nonEmpty.length > 4 && maxLineLen < 100 && hasIndentation) {
          return match.group(0)!;
        }

        // Detect compression: either few lines with long content, or code with braces crammed together
        final braceCount = trimmed.split('').where((c) => c == '{' || c == '}').length;
        final semicolonCount = trimmed.split('').where((c) => c == ';').length;
        final isCompressed = nonEmpty.length <= 4 && maxLineLen > 60;
        final isCrammed = braceCount >= 4 && nonEmpty.length <= 3;
        final hasSemicolonCompression = semicolonCount >= 3 && nonEmpty.length <= 3;

        if (!isCompressed && !isCrammed && !hasSemicolonCompression) {
          return match.group(0)!;
        }

        // Step-by-step expansion for brace-heavy code
        String expanded = trimmed;

        // 1. Split "else {" and "} else" onto proper lines
        expanded = expanded.replaceAllMapped(
          RegExp(r'\}\s*else\s*\{'),
          (m) => '}\nelse {',
        );
        expanded = expanded.replaceAllMapped(
          RegExp(r'\}\s*else\s*if\s*\('),
          (m) => '}\nelse if (',
        );
        expanded = expanded.replaceAllMapped(
          RegExp(r'\}\s*catch\s*\('),
          (m) => '}\ncatch (',
        );
        expanded = expanded.replaceAllMapped(
          RegExp(r'\}\s*finally\s*\{'),
          (m) => '}\nfinally {',
        );

        // 2. Put opening braces on their own line (but NOT after keywords like if/for/while/else/function/class)
        expanded = expanded.replaceAllMapped(
          RegExp(r'(?<=\))\s*\{'),
          (m) => ' {',
        );
        expanded = expanded.replaceAllMapped(
          RegExp(r'(?<=\w)\s*\{\s*(?=[a-zA-Z$_/\n])'),
          (m) => ' {\n',
        );

        // 3. Put closing braces on their own line
        expanded = expanded.replaceAllMapped(
          RegExp(r';\s*\}'),
          (m) => ';\n}',
        );
        expanded = expanded.replaceAllMapped(
          RegExp(r'(?<=[a-zA-Z$_\d)\]])\s*\}(?!\s*[,])'),
          (m) => '\n}',
        );

        // 4. Split semicolons into new lines — but only OUTSIDE parentheses,
        // brackets and string literals, so for-loop headers like
        // "for (i = 0; i < n; i++)" stay intact and URLs never get mangled
        {
          final buf = StringBuffer();
          int parenDepth = 0;
          var i = 0;
          while (i < expanded.length) {
            final ch = expanded[i];
            if (ch == '"' || ch == "'" || ch == '`') {
              buf.write(ch);
              i++;
              while (i < expanded.length && expanded[i] != ch) {
                if (expanded[i] == '\\') {
                  buf.write(expanded[i]);
                  i++;
                  if (i < expanded.length) buf.write(expanded[i]);
                  i++;
                  continue;
                }
                buf.write(expanded[i]);
                i++;
              }
              if (i < expanded.length) {
                buf.write(expanded[i]);
                i++;
              }
              continue;
            }
            if (ch == '/' && i + 1 < expanded.length && expanded[i + 1] == '/') {
              final end = expanded.indexOf('\n', i);
              final stop = end == -1 ? expanded.length : end;
              buf.write(expanded.substring(i, stop));
              i = stop;
              continue;
            }
            if (ch == '(' || ch == '[') parenDepth++;
            if (ch == ')' || ch == ']') parenDepth = (parenDepth - 1).clamp(0, 999);
            if (ch == ';' && parenDepth == 0) {
              buf.write(';\n');
              i++;
              while (i < expanded.length && expanded[i] == ' ') {
                i++;
              }
              continue;
            }
            buf.write(ch);
            i++;
          }
          expanded = buf.toString();
        }

        // 5. Indentation pass
        final outLines = expanded.split('\n');
        final indented = <String>[];
        int indent = 0;
        final indentStr = '    ';
        for (var line in outLines) {
          final trimmedLine = line.trim();
          if (trimmedLine.isEmpty) { indented.add(''); continue; }
          // Decrease indent for closing braces
          if (trimmedLine.startsWith('}') || trimmedLine.startsWith('catch') || trimmedLine.startsWith('else') || trimmedLine.startsWith('finally')) {
            indent = (indent - 1).clamp(0, 20);
          }
          indented.add(indentStr * indent + trimmedLine);
          // Increase indent for opening braces at end of line
          if (trimmedLine.endsWith('{')) {
            indent++;
          }
          // Handle "else {" and "} else {"
          if (trimmedLine.endsWith('{') && (trimmedLine.startsWith('else') || trimmedLine.startsWith('catch') || trimmedLine.startsWith('finally'))) {
            // Already incremented above, which is correct
          }
        }

        // Clean up multiple newlines
        final result = indented.join('\n').replaceAll(RegExp(r'\n{3,}'), '\n\n').trim();
        return '```$lang\n$result\n```';
      },
    );
  }

  String _detectLanguage(String code) {
    if (RegExp(r'#include\s*[<"]').hasMatch(code)) return 'c';
    if (RegExp(r'\bimport\s+(?:java|javax)\b').hasMatch(code)) return 'java';
    if (RegExp(r'\bpublic\s+class\b').hasMatch(code)) return 'java';
    if (RegExp(r'\bSystem\.out\.').hasMatch(code)) return 'java';
    if (RegExp(r'\bdef\s+\w+\s*\(').hasMatch(code) || RegExp(r'\bself\.').hasMatch(code)) return 'python';
    if (RegExp(r'\bimport\s+.*from\s+').hasMatch(code) || RegExp(r'\brequire\s*\(').hasMatch(code)) return 'javascript';
    if (RegExp(r'\bfunction\s+\w+').hasMatch(code) || RegExp(r'\bconst\s+\w+\s*=').hasMatch(code)) return 'javascript';
    if (RegExp(r'\bconsole\.log\s*\(').hasMatch(code)) return 'javascript';
    if (RegExp(r'\bfunc\s+\w+').hasMatch(code)) return 'go';
    if (RegExp(r'\bfn\s+\w+').hasMatch(code)) return 'rust';
    if (RegExp(r'\bprintf\s*\(').hasMatch(code) || RegExp(r'\bscanf\s*\(').hasMatch(code)) return 'c';
    if (RegExp(r'<html', caseSensitive: false).hasMatch(code)) return 'html';
    if (RegExp(r'\bSELECT\b.*\bFROM\b', caseSensitive: false).hasMatch(code)) return 'sql';
    return '';
  }

  static const _validLangs = {
    'python', 'py', 'javascript', 'js', 'typescript', 'ts', 'java', 'c', 'cpp',
    'csharp', 'cs', 'c#', 'go', 'rust', 'ruby', 'php', 'swift', 'kotlin',
    'dart', 'r', 'matlab', 'perl', 'haskell', 'lua', 'html', 'css', 'scss',
    'sql', 'bash', 'sh', 'shell', 'zsh', 'powershell', 'ps1', 'batch',
    'yaml', 'yml', 'json', 'xml', 'toml', 'ini', 'cfg', 'conf',
    'markdown', 'md', 'latex', 'tex', 'dockerfile', 'makefile', 'cmake',
    'graphql', 'gql', 'protobuf', 'proto', 'thrift',
    'scala', 'groovy', 'clojure', 'elixir', 'erlang', 'ocaml', 'fsharp',
    'fortran', 'cobol', 'assembly', 'asm', 'nasm', 'x86',
    'jsx', 'tsx', 'vue', 'svelte', 'astro',
    'zig', 'nim', 'v', 'odin', 'jang', 'julia',
  };

  String _sanitizeCodeLang(String raw) {
    final cleaned = raw.replaceAll('```', '').trim();
    if (cleaned.isEmpty) return '';
    if (cleaned.length > 30) return '';
    if (cleaned.contains(' ')) return '';
    final lower = cleaned.toLowerCase();
    if (_validLangs.contains(lower)) return lower;
    return '';
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
          final codeContent = codeLines.join('\n').trim();
          if (codeContent.isNotEmpty) {
            nodes.add(_MdNode(
              type: 'code_block',
              text: codeContent,
              lang: _sanitizeCodeLang(codeLang),
            ));
          }
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
      final codeContent = codeLines.join('\n').trim();
      if (codeContent.isNotEmpty) {
        nodes.add(_MdNode(
          type: 'code_block',
          text: codeContent,
          lang: _sanitizeCodeLang(codeLang),
        ));
      }
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
    return _CodeBlockWidget(node: node, cs: cs);
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

class _CodeBlockWidget extends StatefulWidget {
  final _MdNode node;
  final ColorScheme cs;

  const _CodeBlockWidget({required this.node, required this.cs});

  @override
  State<_CodeBlockWidget> createState() => _CodeBlockWidgetState();
}

class _CodeBlockWidgetState extends State<_CodeBlockWidget> {
  late final ScrollController _horizontalScrollController;
  late final ScrollController _verticalScrollController;

  @override
  void initState() {
    super.initState();
    _horizontalScrollController = ScrollController();
    _verticalScrollController = ScrollController();
  }

  @override
  void dispose() {
    _horizontalScrollController.dispose();
    _verticalScrollController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final node = widget.node;
    final cs = widget.cs;
    final isDark = cs.brightness == Brightness.dark;
    final bgColor = isDark ? const Color(0xFF12122A) : const Color(0xFFF0EEF8);
    final headerColor = isDark ? const Color(0xFF1C1C35) : const Color(0xFFE4E1F2);
    final langColor = isDark ? const Color(0xFF505070) : const Color(0xFF6B6890);
    final codeColor = isDark ? const Color(0xFFA78BFA) : const Color(0xFF6D28D9);
    final borderColor = cs.outlineVariant.withValues(alpha: 0.3);

    final codeText = Text(
      node.text,
      style: TextStyle(
        fontFamily: 'monospace',
        fontSize: 13,
        color: codeColor,
        height: 1.55,
      ),
    );

    return Container(
      constraints: const BoxConstraints(maxWidth: 416, maxHeight: 416),
      margin: const EdgeInsets.symmetric(vertical: 10),
      decoration: BoxDecoration(
        color: bgColor,
        border: Border.all(color: borderColor),
        borderRadius: BorderRadius.circular(10),
      ),
      clipBehavior: Clip.antiAlias,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
            decoration: BoxDecoration(
              color: headerColor,
              borderRadius: const BorderRadius.only(
                topLeft: Radius.circular(9),
                topRight: Radius.circular(9),
              ),
              border: Border(
                bottom: BorderSide(color: borderColor),
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
          Expanded(
            child: ScrollConfiguration(
              behavior: ScrollConfiguration.of(context).copyWith(
                dragDevices: {
                  PointerDeviceKind.mouse,
                  PointerDeviceKind.touch,
                  PointerDeviceKind.trackpad,
                  PointerDeviceKind.stylus,
                },
              ),
              // Vertical scrollbar OUTERMOST — pinned to the right (max) end of
              // the code block instead of riding along the content width.
              child: Scrollbar(
                controller: _verticalScrollController,
                thumbVisibility: true,
                radius: const Radius.circular(5),
                thickness: 7,
                child: Scrollbar(
                  controller: _horizontalScrollController,
                  thumbVisibility: true,
                  radius: const Radius.circular(5),
                  thickness: 7,
                  // Horizontal notifications bubble up at depth 1 because they
                  // pass through the vertical scroll view first.
                  notificationPredicate: (notice) => notice.depth == 1,
                  child: SingleChildScrollView(
                    controller: _horizontalScrollController,
                    scrollDirection: Axis.horizontal,
                    child: SingleChildScrollView(
                      controller: _verticalScrollController,
                      scrollDirection: Axis.vertical,
                      child: Padding(
                        padding: const EdgeInsets.all(14),
                        child: codeText,
                      ),
                    ),
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _MdNode {
  String type;
  String text;
  String lang;

  _MdNode({required this.type, required this.text, this.lang = ''});
}
