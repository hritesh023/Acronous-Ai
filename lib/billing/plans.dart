// Acronous AI pricing catalog — mirrors billing/plans.json on acronous.com.
// Checkout is centralized: the app opens https://acronous.com/pricing.html
// (same account, token passed via ?token=) where Razorpay Checkout runs.
// Secrets never ship in the app; orders are created + HMAC-verified server-side.
class AiPlan {
  final String id;
  final String label;
  final int? priceInr;
  final String tagline;
  final List<String> features;
  final bool popular;
  const AiPlan({
    required this.id,
    required this.label,
    required this.priceInr,
    required this.tagline,
    required this.features,
    this.popular = false,
  });
}

const List<AiPlan> acronousAiPlans = [
  AiPlan(id: 'ai_free', label: 'Free', priceInr: 0, tagline: 'Try Acronous', features: [
    'Everyday chat allowance', 'Basic web search', 'Basic memory',
  ]),
  AiPlan(id: 'ai_starter_monthly', label: 'Starter', priceInr: 149, tagline: 'Everyday AI', features: [
    'High everyday chat allowance', 'File analysis', 'Image generation',
    'Voice', 'Basic memory & web search', 'Projects/workspaces',
  ]),
  AiPlan(id: 'ai_plus_monthly', label: 'Plus ⭐', priceInr: 449, tagline: 'Serious users', popular: true, features: [
    'Advanced reasoning', 'Larger context', 'More files & images',
    'Deep research', 'Advanced memory & voice', 'Multimodal + AI projects',
  ]),
  AiPlan(id: 'ai_pro_monthly', label: 'Pro', priceInr: 999, tagline: 'Power users', features: [
    'Much higher limits', 'Premium models', 'Advanced agents',
    'Large documents', 'Automation + priority compute', 'API credits included',
  ]),
  AiPlan(id: 'ai_ultra_monthly', label: 'Ultra', priceInr: 2499, tagline: 'Heavy professional use', features: [
    'Very high allowance (never unlimited)', 'Highest models',
    'Long-running agents', 'API/automation credits', 'Priority infrastructure',
  ]),
];

String formatPlanPrice(int? v) {
  if (v == null) return 'Custom';
  if (v == 0) return '₹0';
  return '₹${v.toString().replaceAllMapped(RegExp(r'\B(?=(\d{3})+(?!\d))'), (m) => ',')}';
}
