import 'package:flutter/material.dart';
import '../providers/auth_provider.dart';
import '../providers/chat_provider.dart';
import '../models/message.dart';
import '../models/suggestion.dart';
import '../api/client.dart' show ApiClient;

class SidebarWidget extends StatefulWidget {
  final ChatProvider chatProvider;
  final AuthProvider authProvider;
  final List<Suggestion> topics;
  final VoidCallback onClose;

  const SidebarWidget({
    super.key,
    required this.chatProvider,
    required this.authProvider,
    required this.topics,
    required this.onClose,
  });

  @override
  State<SidebarWidget> createState() => _SidebarWidgetState();
}

class _SidebarWidgetState extends State<SidebarWidget> {
  bool _showTopics = false;
  bool _showSearch = false;
  final _searchController = TextEditingController();
  final _searchFocusNode = FocusNode();

  @override
  void initState() {
    super.initState();
    _searchFocusNode.addListener(() {
      if (!_searchFocusNode.hasFocus && _searchController.text.isEmpty) {
        setState(() => _showSearch = false);
      }
    });
  }

  @override
  void dispose() {
    _searchController.dispose();
    _searchFocusNode.dispose();
    super.dispose();
  }

  String _truncateTitle(String title, {int max = 28}) {
    return title.length > max ? '${title.substring(0, max)}...' : title;
  }

  IconData _iconFor(String iconName) {
    switch (iconName) {
      case 'search': return Icons.search;
      case 'code': return Icons.code;
      case 'book': return Icons.book;
      default: return Icons.chat_bubble_outline;
    }
  }

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final bgColor = isDark ? const Color(0xFF16162A) : Colors.white;

    return Container(
      width: 280,
      color: bgColor,
      child: Column(
        children: [
          _buildHeader(context),
          _buildSearch(context),
          _buildConversationList(context),
          _buildFooter(context),
        ],
      ),
    );
  }

  Widget _buildHeader(BuildContext context) {
    return Container(
      padding: const EdgeInsets.fromLTRB(10, 12, 10, 10),
      decoration: BoxDecoration(
        border: Border(bottom: BorderSide(color: Color(0x14FFFFFF))),
      ),
      child: Row(
        children: [
          ClipRRect(
            borderRadius: BorderRadius.circular(6),
            child: Image.asset(
              'assets/logo.png',
              width: 20,
              height: 20,
              errorBuilder: (_, _, _) => Container(
                width: 20,
                height: 20,
                decoration: BoxDecoration(
                  color: const Color(0xFF7C3AED),
                  borderRadius: BorderRadius.circular(6),
                ),
              ),
            ),
          ),
          const SizedBox(width: 10),
          ShaderMask(
            shaderCallback: (bounds) => const LinearGradient(
              colors: [Color(0xFF7C3AED), Color(0xFFA78BFA)],
            ).createShader(bounds),
            child: const Text(
              'Acronous AI',
              style: TextStyle(
                fontSize: 18,
                fontWeight: FontWeight.w700,
                color: Colors.white,
              ),
            ),
          ),
          const Spacer(),
          _buildNewChatButton(context),
        ],
      ),
    );
  }

  Widget _buildNewChatButton(BuildContext context) {
    return Stack(
      children: [
          Material(
            color: const Color(0xFF7C3AED),
            borderRadius: BorderRadius.circular(10),
            child: InkWell(
              onTap: () {
                widget.chatProvider.newChat();
                widget.onClose();
              },
              borderRadius: BorderRadius.circular(10),
            child: SizedBox(
              width: 34,
              height: 34,
              child: const Icon(Icons.add, size: 18, color: Colors.white),
            ),
          ),
        ),
        if (_showTopics && widget.topics.isNotEmpty)
          Positioned(
            top: 42,
            left: 0,
            child: _buildTopicPopover(context),
          ),
      ],
    );
  }

  Widget _buildTopicPopover(BuildContext context) {
    return Material(
      elevation: 24,
      color: Colors.transparent,
      borderRadius: BorderRadius.circular(14),
      child: Container(
        width: 320,
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: const Color(0xFF222240),
          borderRadius: BorderRadius.circular(14),
          border: Border.all(color: const Color(0x1FFFFFFF)),
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Container(
              padding: const EdgeInsets.only(left: 4, bottom: 10),
              decoration: const BoxDecoration(
                border: Border(bottom: BorderSide(color: Color(0x14FFFFFF))),
              ),
              child: const Text(
                'Start a conversation',
                style: TextStyle(
                  fontSize: 12,
                  fontWeight: FontWeight.w600,
                  letterSpacing: 0.6,
                  color: Color(0xFF505070),
                ),
              ),
            ),
            const SizedBox(height: 10),
            Wrap(
              spacing: 6,
              runSpacing: 6,
              children: widget.topics.map<Widget>((Suggestion topic) {
                return SizedBox(
                  width: (320 - 24 - 6) / 2,
                  child: Material(
                    color: const Color(0xFF1C1C35),
                    borderRadius: BorderRadius.circular(10),
                    child: InkWell(
                      onTap: () {
                        _showTopics = false;
                        widget.chatProvider.handleSendMessage(topic.query);
                        widget.onClose();
                      },
                      borderRadius: BorderRadius.circular(10),
                      child: Container(
                        padding: const EdgeInsets.all(10),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Icon(
                              _iconFor(topic.icon),
                              size: 16,
                              color: const Color(0xFF7C3AED),
                            ),
                            const SizedBox(height: 4),
                            Text(
                              topic.title,
                              style: const TextStyle(
                                fontSize: 13,
                                fontWeight: FontWeight.w600,
                                color: Color(0xFFE8E8F0),
                              ),
                            ),
                            const SizedBox(height: 2),
                            Text(
                              topic.desc,
                              style: const TextStyle(
                                fontSize: 11,
                                color: Color(0xFF707090),
                              ),
                              maxLines: 2,
                              overflow: TextOverflow.ellipsis,
                            ),
                          ],
                        ),
                      ),
                    ),
                  ),
                );
              }).toList(),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildSearch(BuildContext context) {
    return Container(
      padding: const EdgeInsets.fromLTRB(10, 8, 10, 4),
      child: _showSearch
          ? Container(
              padding: const EdgeInsets.symmetric(horizontal: 10),
              decoration: BoxDecoration(
                color: const Color(0xFF1C1C35),
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: const Color(0x1FFFFFFF)),
              ),
              child: Row(
                children: [
                  const Icon(Icons.search, size: 14, color: Color(0xFF505070)),
                  const SizedBox(width: 8),
                  Expanded(
                    child: TextField(
                      controller: _searchController,
                      focusNode: _searchFocusNode,
                      style: const TextStyle(fontSize: 13, color: Color(0xFFE8E8F0)),
                      decoration: const InputDecoration(
                        hintText: 'Search conversations...',
                        hintStyle: TextStyle(color: Color(0xFF505070)),
                        border: InputBorder.none,
                        enabledBorder: InputBorder.none,
                        focusedBorder: InputBorder.none,
                        contentPadding: EdgeInsets.symmetric(vertical: 8),
                        isDense: true,
                      ),
                      onChanged: (_) => setState(() {}),
                    ),
                  ),
                  if (_searchController.text.isNotEmpty)
                    InkWell(
                      onTap: () {
                        _searchController.clear();
                        setState(() {});
                      },
                      borderRadius: BorderRadius.circular(10),
                      child: Container(
                        width: 20,
                        height: 20,
                        decoration: BoxDecoration(
                          color: const Color(0xFF2A2A4A),
                          shape: BoxShape.circle,
                        ),
                        child: const Icon(Icons.close, size: 12, color: Color(0xFF505070)),
                      ),
                    ),
                ],
              ),
            )
          : InkWell(
              onTap: () => setState(() => _showSearch = true),
              borderRadius: BorderRadius.circular(8),
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
                child: Row(
                  children: [
                    const Icon(Icons.search, size: 16, color: Color(0xFF505070)),
                    const SizedBox(width: 8),
                    const Text(
                      'Search',
                      style: TextStyle(fontSize: 13, color: Color(0xFF505070)),
                    ),
                  ],
                ),
              ),
            ),
    );
  }

  Widget _buildConversationList(BuildContext context) {
    final convs = widget.chatProvider.conversations;
    final searchText = _searchController.text.toLowerCase();
    final filtered = searchText.isNotEmpty
        ? convs.where((c) =>
            c.displayTitle.toLowerCase().contains(searchText))
            .toList()
        : convs;

    return Expanded(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Padding(
            padding: EdgeInsets.fromLTRB(14, 8, 14, 6),
            child: Text(
              'Conversations',
              style: TextStyle(
                fontSize: 11,
                fontWeight: FontWeight.w600,
                letterSpacing: 0.8,
                color: Color(0xFF505070),
              ),
            ),
          ),
          Expanded(
            child: filtered.isEmpty
                ? Center(
                    child: Padding(
                      padding: const EdgeInsets.all(24),
                      child: Text(
                        searchText.isNotEmpty
                            ? 'No matching conversations'
                            : 'No conversations yet',
                        style: const TextStyle(fontSize: 13, color: Color(0xFF505070)),
                      ),
                    ),
                  )
                : ListView.builder(
                    padding: const EdgeInsets.symmetric(horizontal: 8),
                    itemCount: filtered.length,
                    itemBuilder: (context, index) {
                      final conv = filtered[index];
                      final isActive = conv.id == widget.chatProvider.currentConversationId;
                      return _buildConversationItem(context, conv.id, conv, isActive);
                    },
                  ),
          ),
        ],
      ),
    );
  }

  Widget _buildConversationItem(BuildContext context, String id, Conversation conv, bool isActive) {
    return MouseRegion(
      child: StatefulBuilder(
        builder: (context, setLocalState) {
          return Container(
            margin: const EdgeInsets.symmetric(vertical: 1),
            decoration: BoxDecoration(
              color: isActive
                  ? const Color(0x1E7C3AED)
                  : Colors.transparent,
              borderRadius: BorderRadius.circular(10),
            ),
            child: InkWell(
              onTap: () {
                widget.chatProvider.switchConversation(id);
                widget.onClose();
              },
              borderRadius: BorderRadius.circular(10),
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                child: Row(
                  children: [
                    Expanded(
                      child: Padding(
                        padding: const EdgeInsets.symmetric(vertical: 7),
                        child: Row(
                          children: [
                            Icon(
                              Icons.chat_bubble_outline,
                              size: 14,
                              color: isActive
                                  ? const Color(0xFF7C3AED)
                                  : const Color(0xFF707090),
                            ),
                            const SizedBox(width: 10),
                            Expanded(
                              child: Text(
                                _truncateTitle(conv.displayTitle),
                                style: TextStyle(
                                  fontSize: 13,
                                  color: isActive
                                      ? const Color(0xFF7C3AED)
                                      : const Color(0xFFB0B0C8),
                                ),
                                overflow: TextOverflow.ellipsis,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                    Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        _buildSmallIconBtn(
                          Icons.download,
                          () => _exportConversation(id),
                          const Color(0xFF505070),
                        ),
                        if (id != 'default')
                          _buildSmallIconBtn(
                            Icons.delete_outline,
                            () {
                              widget.chatProvider.deleteConversation(id);
                            },
                            const Color(0xFF505070),
                            hoverColor: const Color(0xFFEF4444),
                          ),
                      ],
                    ),
                  ],
                ),
              ),
            ),
          );
        },
      ),
    );
  }

  Widget _buildSmallIconBtn(IconData icon, VoidCallback onTap, Color color, {Color? hoverColor}) {
    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(6),
        child: SizedBox(
          width: 24,
          height: 24,
          child: Icon(icon, size: 14, color: color),
        ),
      ),
    );
  }

  void _exportConversation(String id) async {
    try {
      final client = ApiClient(baseUrl: widget.chatProvider.apiClient.baseUrl);
      await client.exportConversation(id);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Conversation exported'), duration: Duration(seconds: 2)),
        );
      }
    } catch (_) {}
  }

  Widget _buildFooter(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        border: Border(top: BorderSide(color: Color(0x14FFFFFF))),
      ),
      child: Column(
        children: [
          if (widget.authProvider.user != null)
            Padding(
              padding: const EdgeInsets.only(bottom: 4),
              child: Text(
                widget.authProvider.user!.email ?? '',
                style: const TextStyle(fontSize: 12, color: Color(0xFF505070)),
                overflow: TextOverflow.ellipsis,
              ),
            ),
          InkWell(
            onTap: () => widget.chatProvider.toggleTheme(),
            borderRadius: BorderRadius.circular(10),
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
              child: Row(
                children: [
                  Icon(
                    isDark ? Icons.light_mode : Icons.dark_mode,
                    size: 16,
                    color: const Color(0xFFB0B0C8),
                  ),
                  const SizedBox(width: 10),
                  Text(
                    isDark ? 'Light mode' : 'Dark mode',
                    style: const TextStyle(fontSize: 13, color: Color(0xFFB0B0C8)),
                  ),
                ],
              ),
            ),
          ),
          InkWell(
            onTap: () => Navigator.pushNamed(context, '/settings'),
            borderRadius: BorderRadius.circular(10),
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
              child: Row(
                children: [
                  const Icon(Icons.settings, size: 16, color: Color(0xFFB0B0C8)),
                  const SizedBox(width: 10),
                  const Text(
                    'Settings',
                    style: TextStyle(fontSize: 13, color: Color(0xFFB0B0C8)),
                  ),
                ],
              ),
            ),
          ),
          InkWell(
            onTap: () => widget.authProvider.signOut(),
            borderRadius: BorderRadius.circular(10),
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
              child: Row(
                children: [
                  const Icon(Icons.logout, size: 16, color: Color(0xFFEF4444)),
                  const SizedBox(width: 10),
                  const Text(
                    'Sign out',
                    style: TextStyle(fontSize: 13, color: Color(0xFFEF4444)),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}
