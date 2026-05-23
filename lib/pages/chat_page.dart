import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../constants/app_constants.dart';
import '../providers/chat_provider.dart';
import '../widgets/chat_message.dart';
import '../widgets/chat_input.dart';
import '../widgets/typing_indicator.dart';
import 'settings_page.dart';

class ChatPage extends StatefulWidget {
  const ChatPage({super.key});

  @override
  State<ChatPage> createState() => _ChatPageState();
}

class _ChatPageState extends State<ChatPage> {
  final ScrollController _scrollController = ScrollController();
  final TextEditingController _searchController = TextEditingController();
  int _lastMsgCount = 0;

  @override
  void dispose() {
    _scrollController.dispose();
    _searchController.dispose();
    super.dispose();
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _scrollIfNeeded();
  }

  void _scrollIfNeeded() {
    final chat = context.read<ChatProvider>();
    final msgs = chat.currentConversation?.messages ?? [];
    if (msgs.length > _lastMsgCount) {
      _lastMsgCount = msgs.length;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (_scrollController.hasClients) {
          _scrollController.animateTo(
            _scrollController.position.maxScrollExtent,
            duration: const Duration(milliseconds: 250),
            curve: Curves.easeOut,
          );
        }
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: _buildAppBar(context),
      drawer: _buildSidebar(context),
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 900),
          child: Column(
            children: [
              Expanded(child: _buildMessages()),
              const ChatInput(),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildMessages() {
    return Consumer<ChatProvider>(
      builder: (context, chat, _) {
        final msgs = chat.currentConversation?.messages ?? [];
        _scrollIfNeeded();
        if (msgs.isEmpty && !chat.isLoading) {
          return _buildWelcome(context);
        }
        return ListView.builder(
          controller: _scrollController,
          padding: const EdgeInsets.only(top: 6, bottom: 4),
          itemCount: msgs.length + (chat.isLoading ? 1 : 0),
          itemBuilder: (_, i) {
            if (chat.isLoading && i == msgs.length) {
              return const TypingIndicator();
            }
            return ChatMessageWidget(message: msgs[i]);
          },
        );
      },
    );
  }

  PreferredSizeWidget _buildAppBar(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return AppBar(
      leading: Builder(
        builder: (ctx) => IconButton(
          icon: const Icon(Icons.menu_rounded),
          onPressed: () => Scaffold.of(ctx).openDrawer(),
        ),
      ),
      title: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: AppDimens.avatarSize,
            height: AppDimens.avatarSize,
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(AppDimens.avatarRadius),
              color: cs.primaryContainer,
            ),
            child: ClipRRect(
              borderRadius: BorderRadius.circular(AppDimens.avatarRadius),
              child: Image.asset(
                'assets/logo.png',
                width: AppDimens.avatarSize,
                height: AppDimens.avatarSize,
                fit: BoxFit.contain,
                errorBuilder: (_, _, _) => Icon(
                  Icons.auto_awesome,
                  size: AppDimens.iconMed - 3,
                  color: cs.primary,
                ),
              ),
            ),
          ),
          const SizedBox(width: AppDimens.gapSM + 1),
          Text(
            AppStrings.appName,
            style: TextStyle(
              fontWeight: FontWeight.w600,
              fontSize: AppDimens.fontSizeHeading - 1,
            ),
          ),
        ],
      ),
      actions: [
        Consumer<ChatProvider>(
          builder: (context, chat, _) => IconButton(
            icon: Icon(
              chat.themeMode == ThemeMode.dark
                  ? Icons.light_mode_outlined
                  : Icons.dark_mode_outlined,
              size: AppDimens.inputIconInnerSize,
            ),
            onPressed: chat.toggleTheme,
          ),
        ),
        IconButton(
          icon: const Icon(Icons.settings_outlined,
              size: AppDimens.inputIconInnerSize),
          onPressed: () => Navigator.of(context).push(
            MaterialPageRoute(builder: (_) => const SettingsPage()),
          ),
        ),
      ],
    );
  }

  Widget _buildWelcome(BuildContext context) {
    final cs = Theme.of(context).colorScheme;

    return Center(
      child: SingleChildScrollView(
        padding: const EdgeInsets.symmetric(horizontal: AppDimens.paddingXL * 2),
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 650),
          child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Container(
              width: AppDimens.avatarSizeLarge,
              height: AppDimens.avatarSizeLarge,
              decoration: BoxDecoration(
                borderRadius:
                    BorderRadius.circular(AppDimens.avatarRadiusLarge),
                gradient: LinearGradient(
                  colors: [
                    cs.primary,
                    cs.primary.withValues(alpha: 0.7),
                  ],
                  begin: Alignment.topLeft,
                  end: Alignment.bottomRight,
                ),
              ),
              child: ClipRRect(
                borderRadius:
                    BorderRadius.circular(AppDimens.avatarRadiusLarge),
                child: Image.asset(
                  'assets/logo.png',
                  width: 40,
                  height: 40,
                  fit: BoxFit.contain,
                  errorBuilder: (_, _, _) => const Icon(
                    Icons.auto_awesome,
                    size: 36,
                    color: Colors.white,
                  ),
                ),
              ),
            ),
            const SizedBox(height: AppDimens.paddingXL + 4),
            Text(
              AppStrings.welcomeTitle,
              style: Theme.of(context).textTheme.titleLarge?.copyWith(
                    fontWeight: FontWeight.w700,
                    color: cs.onSurface,
                  ),
            ),
            const SizedBox(height: AppDimens.paddingSM),
            Text(
              AppStrings.welcomeSubtitle,
              style: TextStyle(
                color: cs.onSurfaceVariant,
                fontSize: AppDimens.fontSizeLG,
              ),
            ),
            const SizedBox(height: AppDimens.paddingXL + 12),
            Wrap(
              spacing: AppDimens.gapLG,
              runSpacing: AppDimens.gapLG,
              alignment: WrapAlignment.center,
              children: AppStrings.welcomeSuggestions
                  .map((s) => ActionChip(
                        label: Text(s,
                            style: TextStyle(
                                fontSize: AppDimens.fontSizeMD + 0.5,
                                color: cs.onSurface)),
                        onPressed: () =>
                            context.read<ChatProvider>().sendMessage(s),
                        shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(18),
                        ),
                        visualDensity: VisualDensity.compact,
                      ))
                  .toList(),
            ),
          ],
          ),
        ),
      ),
    );
  }

  Widget _buildSidebar(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final paddingTop = MediaQuery.of(context).padding.top;
    return Drawer(
      child: Column(
        children: [
          Container(
            width: double.infinity,
            padding: EdgeInsets.only(
              top: paddingTop + 14,
              bottom: AppDimens.paddingLG,
              left: AppDimens.paddingXL,
              right: AppDimens.paddingLG,
            ),
            decoration: BoxDecoration(
              border: Border(
                bottom: BorderSide(
                  color: cs.outlineVariant.withValues(alpha: 0.1),
                ),
              ),
            ),
            child: Row(
              children: [
                Container(
                  width: AppDimens.avatarSizeSidebar,
                  height: AppDimens.avatarSizeSidebar,
                  decoration: BoxDecoration(
                    borderRadius:
                        BorderRadius.circular(AppDimens.avatarRadiusSidebar),
                    color: cs.primaryContainer,
                  ),
                  child: ClipRRect(
                    borderRadius: BorderRadius.circular(
                        AppDimens.avatarRadiusSidebar),
                    child: Image.asset(
                      'assets/logo.png',
                      width: AppDimens.iconMed + 2,
                      height: AppDimens.iconMed + 2,
                      fit: BoxFit.contain,
                      errorBuilder: (_, _, _) => const Icon(
                        Icons.auto_awesome,
                        size: AppDimens.iconMed,
                      ),
                    ),
                  ),
                ),
                const SizedBox(width: AppDimens.gapLG),
                Text(
                  AppStrings.appName,
                  style: TextStyle(
                    fontSize: AppDimens.fontSizeHeading,
                    fontWeight: FontWeight.w700,
                  ),
                ),
                const Spacer(),
                IconButton(
                  icon: const Icon(Icons.close_rounded,
                      size: AppDimens.inputIconInnerSize),
                  onPressed: () => Navigator.pop(context),
                ),
              ],
            ),
          ),
          Padding(
            padding: const EdgeInsets.all(AppDimens.gapXL),
            child: Consumer<ChatProvider>(
              builder: (context, chat, _) => FilledButton.icon(
                onPressed: () {
                  chat.newChat();
                  Navigator.pop(context);
                },
                icon: const Icon(Icons.add_rounded,
                    size: AppDimens.iconMed),
                label: Text(AppStrings.newChat),
                style: FilledButton.styleFrom(
                  minimumSize: const Size(200, 40),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(10),
                  ),
                ),
              ),
            ),
          ),
          Padding(
            padding: const EdgeInsets.symmetric(
                horizontal: AppDimens.gapXL, vertical: AppDimens.gapXS),
            child: TextField(
              controller: _searchController,
              onChanged: (v) =>
                  context.read<ChatProvider>().setSearchQuery(v),
              decoration: InputDecoration(
                hintText: AppStrings.searchHistory,
                prefixIcon: const Icon(Icons.search_rounded,
                    size: AppDimens.iconMed),
                filled: true,
                fillColor: cs.surfaceContainerHighest
                    .withValues(alpha: 0.15),
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(10),
                  borderSide: BorderSide.none,
                ),
                contentPadding: const EdgeInsets.symmetric(
                  horizontal: AppDimens.gapXL,
                  vertical: AppDimens.gapLG - 4,
                ),
                isDense: true,
              ),
            ),
          ),
          const Divider(height: 1),
          Expanded(
            child: Consumer<ChatProvider>(
              builder: (context, chat, _) {
                final convos = chat.filteredConversations;
                if (convos.isEmpty) {
                  return Center(
                    child: Text(
                      chat.searchQuery.isNotEmpty
                          ? AppStrings.noMatching
                          : AppStrings.noConversations,
                      style: TextStyle(
                          color: cs.onSurfaceVariant,
                          fontSize: AppDimens.fontSizeLG),
                    ),
                  );
                }
                return ListView(
                  padding: const EdgeInsets.symmetric(
                      vertical: AppDimens.gapSM),
                  children: _groupByDate(convos, cs, chat, context),
                );
              },
            ),
          ),
        ],
      ),
    );
  }

  List<Widget> _groupByDate(
    List<dynamic> convos,
    ColorScheme cs,
    ChatProvider chat,
    BuildContext context,
  ) {
    final now = DateTime.now();
    final today = DateTime(now.year, now.month, now.day);
    final yesterday = today.subtract(const Duration(days: 1));
    final thisWeek =
        today.subtract(Duration(days: today.weekday - 1));
    final thisMonth = DateTime(today.year, today.month, 1);

    final dateLabels = {
      'today': AppStrings.today,
      'yesterday': AppStrings.yesterday,
      'week': AppStrings.thisWeek,
      'month': AppStrings.thisMonth,
      'earlier': AppStrings.earlier,
    };

    List<Widget> items = [];
    String? lastLabel;

    for (final c in convos) {
      final date = c.updatedAt;
      String label;
      if (date.isAfter(today)) {
        label = dateLabels['today']!;
      } else if (date.isAfter(yesterday)) {
        label = dateLabels['yesterday']!;
      } else if (date.isAfter(thisWeek)) {
        label = dateLabels['week']!;
      } else if (date.isAfter(thisMonth)) {
        label = dateLabels['month']!;
      } else {
        label = dateLabels['earlier']!;
      }

      if (label != lastLabel) {
        items.add(
          Padding(
            padding: const EdgeInsets.fromLTRB(
                AppDimens.paddingXL, AppDimens.gapXL, AppDimens.paddingXL, AppDimens.gapSM),
            child: Text(
              label,
              style: TextStyle(
                fontSize: AppDimens.fontSizeSM,
                fontWeight: FontWeight.w600,
                color: cs.onSurfaceVariant.withValues(alpha: 0.6),
                letterSpacing: 0.3,
              ),
            ),
          ),
        );
        lastLabel = label;
      }

      final active = c.id == chat.currentConversation?.id;
      items.add(
        Container(
          margin: const EdgeInsets.symmetric(
              horizontal: AppDimens.paddingSM, vertical: 1),
          decoration: BoxDecoration(
            borderRadius:
                BorderRadius.circular(AppDimens.sidebarItemRadius),
            color: active
                ? cs.primaryContainer.withValues(alpha: 0.2)
                : Colors.transparent,
          ),
          child: ListTile(
            dense: true,
            leading: Icon(
              Icons.chat_outlined,
              size: AppDimens.iconMed,
              color: active
                  ? cs.primary
                  : cs.onSurfaceVariant.withValues(alpha: 0.5),
            ),
            title: Text(
              c.displayTitle,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(
                fontSize: AppDimens.fontSizeLG,
                fontWeight:
                    active ? FontWeight.w600 : FontWeight.normal,
                color: active
                    ? cs.onSurface
                    : cs.onSurfaceVariant,
              ),
            ),
            trailing: IconButton(
              icon: Icon(
                Icons.delete_outline,
                size: AppDimens.iconSmall + 2,
                color: cs.onSurfaceVariant.withValues(alpha: 0.4),
              ),
              onPressed: () {
                showDialog(
                  context: context,
                  builder: (ctx) => AlertDialog(
                    title: Text(AppStrings.deleteTitle),
                    content: Text(AppStrings.deleteBody),
                    actions: [
                      TextButton(
                        onPressed: () => Navigator.pop(ctx),
                        child: Text(AppStrings.cancel),
                      ),
                      TextButton(
                        onPressed: () {
                          chat.deleteConversation(c.id);
                          Navigator.pop(ctx);
                        },
                        child: Text(AppStrings.delete,
                            style:
                                TextStyle(color: cs.error)),
                      ),
                    ],
                  ),
                );
              },
            ),
            onTap: () {
              chat.switchConversation(c.id);
              Navigator.pop(context);
            },
            shape: RoundedRectangleBorder(
              borderRadius:
                  BorderRadius.circular(AppDimens.sidebarItemRadius),
            ),
            contentPadding: const EdgeInsets.symmetric(
                horizontal: AppDimens.gapXL),
            visualDensity: VisualDensity.compact,
          ),
        ),
      );
    }
    return items;
  }
}
