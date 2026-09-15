# Acronous billing — Razorpay paywall + $41 indie budget

## The verdict (why this shape)

$500/mo always-on GPU before revenue = death for an indie dev. $41 (~₹3,400)
**one-time** works if costs scale with revenue instead of time:

- **Free users cost you $0.** They run on Contabo VPS CPU + Cloudflare free
  tier, capped at 20 chats / 3 images / 1 video per day. Worst case a free user
  costs ~$0.005/day in electricity you don't pay for (it's Contabo's free tier).
- **GPU spend happens only for Pro users** (`GPU_PRO_ONLY=true`). No Pro users
  → $0 GPU bill. Each ₹299 subscriber covers ~1,500 GPU chats or ~30 GPU images
  at serverless rates — margin is ~95%+.
- **Break-even math:** serverless at your early traffic = $10-40/mo
  (₹850-3,400). At ₹299/mo net ~₹292 after Razorpay fees → **3-12 paying users
  cover all infra**. The $500/mo always-on pod needs ~145 paying users — that
  comes AFTER product-market fit, not before.

## $41 budget sheet (one-time)

| Item | Cost |
|---|---|
| Domain `acronous.com` (1 yr, if not owned) | ~$12 |
| RunPod signup credit (free) + first test spend (4090 × ~15 hrs incl. cold starts) | ~$7-10 |
| First-month serverless buffer (only consumed if Pro users actually use GPU) | ~$15 buffer, mostly unspent |
| Contabo + Cloudflare + KV | $0 |
| Razorpay test mode | $0 (live needs KYC, no fee to activate) |
| **Total** | **~$35-40** |

## Razorpay setup (30 min, test → live)

1. Sign up at razorpay.com → complete KYC (PAN + bank account for live; test
   mode works immediately with test keys `rzp_test_...`).
2. Dashboard → Settings → API Keys → generate Key ID + Secret.
3. Worker config (never commit secrets):
   ```
   # vars (wrangler.toml already has RAZORPAY_KEY_ID=""):
   RAZORPAY_KEY_ID = "rzp_test_xxxx"     # or via secret; public key, safe in file
   PRO_PRICE_INR = "299"
   npx wrangler secret put RAZORPAY_KEY_SECRET
   npx wrangler deploy cloudflare-worker.js --name acronous-ai
   ```
4. Until keys are set, billing endpoints return 503 and **everything stays on
   free-tier caps** — safe to deploy now.
5. Go live: swap to `rzp_live_...` keys, same commands. Razorpay fee ~2% + GST
   domestic UPI/cards; settlement T+2 to your bank.

## How the paywall works (code map)

- Identity: `quotaIdFromRequest` — JWT `sub` when signed in (`u:<id>`), else
  `CF-Connecting-IP` (`ip:<x>`), else shared `anon`. Anonymous users MUST sign
  in to buy Pro (order/verify return 401 otherwise) — this is also your
  signup funnel.
- Caps: `FREE_CHAT_PER_DAY=20`, `FREE_IMAGE_PER_DAY=3`, `FREE_VIDEO_PER_DAY=1`
  (wrangler vars). Counters in USER_MEMORY KV: `usage:<day>:<kind>:<id>`,
  3-day TTL. Hot path = 1 KV read; increment via `ctx.waitUntil` (never blocks).
- Over-quota → HTTP 402 `{type:'paywall', kind, used, limit, plan,
  price_inr}`. In-chat image/video intents consume 1 chat unit (documented
  simplification; dedicated image/video endpoints consume image/video units).
- GPU money guard: `tryGpuChat`/`tryGpuImageGen` return null unless
  `env._isPro` (resolved once per request in `fetch`) when `GPU_PRO_ONLY=true`.
  Kill-switches: `GPU_ENABLED=false` (CPU-only), unset GPU URLs (same effect).
- Pro flag: `pro:<quotaId>` → `{until, plan, payment_id}`, 45-day TTL.
  Verified via Razorpay HMAC-SHA256 (`order_id|payment_id`, WebCrypto).

## API contract (for the app / future checkout page)

- `GET /v1/billing/status` → `{pro, pro_until, usage:{chat:{used,limit},
  image:{...}, video:{...}}, plans:[{id:'pro_monthly', price_inr, ...}]}`.
  `limit:-1` = unlimited (Pro).
- `POST /v1/billing/order {plan}` → `{order_id, amount, currency, key_id}`.
  Pass `order_id + key_id` to Razorpay Checkout (web) / razorpay_flutter (app).
- `POST /v1/billing/verify {razorpay_order_id, razorpay_payment_id,
  razorpay_signature}` → `{ok, pro, pro_until}`. Call after Checkout success,
  then refresh status.

## Flutter wiring (done, minimal)

- `lib/api/client.dart`: `isPaywall(e)`, `paywallMessage(e)`,
  `getBillingStatus/createBillingOrder/verifyBillingPayment`. Stream path now
  attaches the parsed 402 body so the exact upgrade text shows.
- `lib/providers/chat_provider.dart`: 402 short-circuits the 3-attempt retry
  loop (retries would burn quota units) and renders the paywall message as the
  assistant reply. Smart-edit rethrows 402 instead of falling into legacy flow.
- TODO (checkout UI, not built yet): Pro screen calling the 3 billing methods
  + `razorpay_flutter` for native UPI/cards + web Checkout via
  `https://checkout.razorpay.com/v1/checkout.js`. The backend is ready for it.

## Abuse notes (known limits, acceptable for launch)

- IP-based free quota can be dodged by VPNs — fine at your scale; per-user
  (signed-in) quotas are the real gate and purchases require sign-in.
- `anon` bucket is shared and tiny by design — it pushes toward sign-in.
- KV is eventually consistent: a burst of parallel requests can overshoot caps
  by a few units. Units cost fractions of a cent on CPU — irrelevant.
- Raise caps/prices via vars only (`FREE_*`, `PRO_PRICE_INR`) — no code change.
