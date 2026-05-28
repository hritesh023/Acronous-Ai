import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../constants/app_constants.dart';
import '../providers/chat_provider.dart';
import '../services/overlay_service.dart';
import '../widgets/voice_popup.dart';

class SettingsPage extends StatefulWidget {
  const SettingsPage({super.key});

  @override
  State<SettingsPage> createState() => _SettingsPageState();
}

class _SettingsPageState extends State<SettingsPage> {
  void _openVoiceSearch(BuildContext context) {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (_) => VoicePopup(
        searchMode: true,
        onResult: (text) {
          try {
            context.read<ChatProvider>().sendMessage(text);
          } catch (_) {}
        },
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Scaffold(
      appBar: AppBar(
        title: Text(AppStrings.settings),
        centerTitle: true,
      ),
      body: Consumer2<ChatProvider, OverlayService>(
        builder: (context, chat, overlay, _) => Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 800),
            child: ListView(
              padding: const EdgeInsets.symmetric(
                  horizontal: AppDimens.paddingXL, vertical: AppDimens.gapSM),
              children: [
            _SectionHeader(title: AppStrings.appearance, cs: cs),
            _SettingsCard(
              children: [
                _ThemeSelector(chat: chat, cs: cs),
              ],
            ),
            const SizedBox(height: AppDimens.paddingXL + 4),
            _SectionHeader(title: 'Continuous Voice Search', cs: cs),
            _SettingsCard(
              children: [
                _SwitchTile(
                  icon: Icons.mic_rounded,
                  title: 'Always-on Listening',
                  subtitle: 'Continuously listen for voice commands and process them automatically',
                  value: chat.continuousVoiceSearchEnabled,
                  onChanged: (v) => chat.setContinuousVoiceSearchEnabled(v),
                  cs: cs,
                ),
                if (chat.continuousVoiceSearchEnabled) ...[
                  _divider(cs),
                  Padding(
                    padding: const EdgeInsets.fromLTRB(
                      AppDimens.paddingXL,
                      AppDimens.paddingMD,
                      AppDimens.paddingXL,
                      AppDimens.paddingMD,
                    ),
                    child: Row(
                      children: [
                        Icon(Icons.info_outline_rounded, size: 18, color: cs.primary),
                        const SizedBox(width: 8),
                        Expanded(
                          child: Text(
                            'Voice commands like "call John", "send a message", '
                            'or "open a website" will be processed automatically',
                            style: TextStyle(
                              fontSize: AppDimens.fontSizeMD,
                              color: cs.onSurfaceVariant,
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ],
            ),
            const SizedBox(height: AppDimens.paddingXL + 4),
            _SectionHeader(title: 'Voice', cs: cs),
            _SettingsCard(
              children: [
                _SwitchTile(
                  icon: Icons.mic_rounded,
                  title: 'Continuous Voice',
                  subtitle: 'Keep microphone active in background',
                  value: chat.continuousVoiceEnabled,
                  onChanged: (v) => chat.setContinuousVoiceEnabled(v),
                  cs: cs,
                ),
                _divider(cs),
                ListTile(
                  leading: Icon(Icons.search_rounded,
                      color: cs.primary,
                      size: AppDimens.inputIconInnerSize),
                  title: const Text('Voice Search',
                      style: TextStyle(
                          fontWeight: FontWeight.w500,
                          fontSize: AppDimens.fontSizeBase)),
                  subtitle: Text('Open voice input for search',
                      style: TextStyle(
                          fontSize: AppDimens.fontSizeMD,
                          color: cs.onSurfaceVariant)),
                  trailing: FilledButton.tonal(
                    onPressed: () => _openVoiceSearch(context),
                    style: FilledButton.styleFrom(
                      minimumSize: const Size(100, 36),
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(10),
                      ),
                    ),
                    child: const Text('Open',
                        style: TextStyle(fontSize: AppDimens.fontSizeBase)),
                  ),
                ),
              ],
            ),
            const SizedBox(height: AppDimens.paddingXL + 4),
            _SectionHeader(title: AppStrings.assistant, cs: cs),
            _SettingsCard(
              children: [
                _SwitchTile(
                  icon: Icons.smart_toy_rounded,
                  title: AppStrings.backgroundAssistant,
                  subtitle: AppStrings.backgroundAssistantSub,
                  value: chat.backgroundAssistantEnabled,
                  onChanged: (v) => chat.setBackgroundAssistantEnabled(v),
                  cs: cs,
                  leading: Container(
                    width: AppDimens.inputIconInnerSize + 2,
                    height: AppDimens.inputIconInnerSize + 2,
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      gradient: LinearGradient(
                        colors: [
                          cs.primary,
                          cs.primary.withValues(alpha: 0.8),
                        ],
                        begin: Alignment.topLeft,
                        end: Alignment.bottomRight,
                      ),
                    ),
                    child: ClipRRect(
                      borderRadius: BorderRadius.circular(
                          (AppDimens.inputIconInnerSize + 2) / 2),
                      child: Image.asset(
                        'assets/Acronous_Ai_svj_logo.png',
                        width: AppDimens.inputIconInnerSize,
                        height: AppDimens.inputIconInnerSize,
                        fit: BoxFit.contain,
                        errorBuilder: (_, _, _) => Icon(
                          Icons.auto_awesome_rounded,
                          size: AppDimens.inputIconInnerSize,
                          color: cs.onPrimary,
                        ),
                      ),
                    ),
                  ),
                ),
                if (overlay.supportsSystemOverlay) ...[
                  _divider(cs),
                  _SwitchTile(
                    icon: Icons.picture_in_picture_alt_rounded,
                    title: 'System Overlay',
                    subtitle: 'Show floating icon even when app is closed',
                    value: chat.systemOverlayEnabled,
                    onChanged: (v) => chat.setSystemOverlayEnabled(v),
                    cs: cs,
                  ),
                ],
              ],
            ),
            const SizedBox(height: AppDimens.paddingXL + 4),
            _SectionHeader(title: 'Permissions', cs: cs),
            _SettingsCard(
              children: [
                _PermissionTile(
                  icon: Icons.mic_rounded,
                  title: AppStrings.microphone,
                  subtitle: AppStrings.microphoneSub,
                  cs: cs,
                ),
                if (overlay.supportsSystemOverlay) ...[
                  _divider(cs),
                  _PermissionTile(
                    icon: Icons.picture_in_picture_alt_rounded,
                    title: 'Overlay',
                    subtitle: 'Show icon over other apps',
                    cs: cs,
                    trailing: TextButton(
                      onPressed: () => overlay.requestOverlayPermission(),
                      child: Text(
                        overlay.systemOverlayPermissionGranted
                            ? 'Granted'
                            : 'Request',
                        style: TextStyle(
                          color: overlay.systemOverlayPermissionGranted
                              ? Colors.green
                              : cs.primary,
                        ),
                      ),
                    ),
                  ),
                ],
              ],
            ),
            const SizedBox(height: AppDimens.paddingXL * 2),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _divider(ColorScheme cs) {
    return Divider(
      height: 1,
      indent: AppDimens.paddingXL,
      endIndent: AppDimens.paddingXL,
      color: cs.outlineVariant.withValues(alpha: 0.2),
    );
  }
}

class _SectionHeader extends StatelessWidget {
  final String title;
  final ColorScheme cs;

  const _SectionHeader({required this.title, required this.cs});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(
          left: AppDimens.gapSM, bottom: AppDimens.paddingSM, top: AppDimens.gapLG),
      child: Text(
        title,
        style: TextStyle(
          fontSize: AppDimens.fontSizeMD,
          fontWeight: FontWeight.w700,
          color: cs.primary,
          letterSpacing: 0.6,
        ),
      ),
    );
  }
}

class _SettingsCard extends StatelessWidget {
  final List<Widget> children;

  const _SettingsCard({required this.children});

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: EdgeInsets.zero,
      child: Column(children: children),
    );
  }
}

class _ThemeSelector extends StatelessWidget {
  final ChatProvider chat;
  final ColorScheme cs;

  const _ThemeSelector({required this.chat, required this.cs});

  @override
  Widget build(BuildContext context) {
    final label = chat.themeMode == ThemeMode.dark
        ? AppStrings.dark
        : chat.themeMode == ThemeMode.light
            ? AppStrings.light
            : AppStrings.system;
    return Padding(
      padding: const EdgeInsets.symmetric(
          horizontal: AppDimens.paddingXL, vertical: AppDimens.paddingLG),
      child: Row(
        children: [
          Icon(
            chat.themeMode == ThemeMode.dark
                ? Icons.dark_mode_rounded
                : chat.themeMode == ThemeMode.light
                    ? Icons.light_mode_rounded
                    : Icons.settings_brightness_rounded,
            color: cs.primary,
            size: AppDimens.inputIconInnerSize,
          ),
          const SizedBox(width: AppDimens.paddingLG),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(AppStrings.theme,
                    style: const TextStyle(
                        fontWeight: FontWeight.w500,
                        fontSize: AppDimens.fontSizeBase)),
                Text(
                  label,
                  style: TextStyle(
                    color: cs.onSurfaceVariant,
                    fontSize: AppDimens.fontSizeMD,
                  ),
                ),
              ],
            ),
          ),
          SegmentedButton<ThemeMode>(
            segments: const [
              ButtonSegment(
                value: ThemeMode.light,
                icon: Icon(Icons.light_mode_outlined,
                    size: AppDimens.iconSmall + 2),
              ),
              ButtonSegment(
                value: ThemeMode.system,
                icon: Icon(Icons.settings_brightness_outlined,
                    size: AppDimens.iconSmall + 2),
              ),
              ButtonSegment(
                value: ThemeMode.dark,
                icon: Icon(Icons.dark_mode_outlined,
                    size: AppDimens.iconSmall + 2),
              ),
            ],
            selected: {chat.themeMode},
            onSelectionChanged: (set) {
              final mode = set.first;
              if (mode == ThemeMode.dark) {
                chat.setThemeMode(ThemeMode.dark);
              } else if (mode == ThemeMode.light) {
                chat.setThemeMode(ThemeMode.light);
              } else {
                chat.setThemeMode(ThemeMode.system);
              }
            },
            style: ButtonStyle(
              visualDensity: VisualDensity.compact,
              tapTargetSize: MaterialTapTargetSize.shrinkWrap,
            ),
          ),
        ],
      ),
    );
  }
}


class _SwitchTile extends StatelessWidget {
  final IconData icon;
  final String title;
  final String subtitle;
  final bool value;
  final ValueChanged<bool> onChanged;
  final ColorScheme cs;
  final Widget? leading;

  const _SwitchTile({
    required this.icon,
    required this.title,
    required this.subtitle,
    required this.value,
    required this.onChanged,
    required this.cs,
    this.leading,
  });

  @override
  Widget build(BuildContext context) {
    return SwitchListTile(
      secondary: leading ??
          Icon(icon,
              color: cs.primary,
              size: AppDimens.inputIconInnerSize),
      title: Text(title,
          style: const TextStyle(
              fontWeight: FontWeight.w500,
              fontSize: AppDimens.fontSizeBase)),
      subtitle: Text(subtitle,
          style: const TextStyle(fontSize: AppDimens.fontSizeMD)),
      value: value,
      onChanged: onChanged,
      dense: true,
      contentPadding:
          const EdgeInsets.symmetric(horizontal: AppDimens.paddingXL),
    );
  }
}

class _PermissionTile extends StatelessWidget {
  final IconData icon;
  final String title;
  final String subtitle;
  final ColorScheme cs;
  final Widget? trailing;

  const _PermissionTile({
    required this.icon,
    required this.title,
    required this.subtitle,
    required this.cs,
    this.trailing,
  });

  @override
  Widget build(BuildContext context) {
    return ListTile(
      leading: Icon(icon, color: cs.primary, size: AppDimens.inputIconInnerSize),
      title: Text(title,
          style: const TextStyle(
              fontWeight: FontWeight.w500,
              fontSize: AppDimens.fontSizeBase)),
      subtitle: Text(subtitle,
          style: const TextStyle(fontSize: AppDimens.fontSizeMD)),
      trailing: trailing ?? Icon(Icons.check_circle_rounded,
          color: Colors.green, size: 22),
      contentPadding:
          const EdgeInsets.symmetric(horizontal: AppDimens.paddingXL),
    );
  }
}
