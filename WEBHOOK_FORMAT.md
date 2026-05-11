# Website purchase webhook

Endpoint:

```text
POST /webhook/purchase
Content-Type: application/json
X-Webhook-Secret: your_secret_from_WEBHOOK_SECRET
```

Example JSON sent by the website:

```json
{
  "event_id": "ord_20260422_000123",
  "payment_system": "stripe",
  "product_key": "monthly",
  "subscription_days": 30,
  "email": "client@example.com",
  "amount": 10.0,
  "currency": "EUR",
  "paid_at": "2026-04-22T15:30:00Z"
}
```

Required fields for one purchase:

- `email`: client e-mail. If the user has not registered in the bot yet, the purchase is saved as pending and will be attached after `/start` + e-mail registration.
- `payment_system`: payment provider used on the website, for example `stripe`, `paypal`, `bank`, `crypto`.
- `product_key`: use `monthly` for the 1-month VIP subscription, or a custom key if `subscription_days` is provided.
- `subscription_days`: how many access days should be added. If `product_key` is a known bot plan and this field is missing, the bot uses the configured plan duration.

Bulk import / migration:

Send all old subscriber e-mails in one request. Top-level fields are used as defaults for every subscriber, and each item can override them.

```json
{
  "batch_id": "legacy_import_2026_05",
  "payment_system": "legacy_import",
  "product_key": "vip_chat_lv",
  "expires_at": "2026-06-15",
  "subscribers": [
    {
      "email": "client1@example.com",
      "amount": 10.0
    },
    {
      "email": "client2@example.com",
      "product_key": "scanner_chat",
      "expires_at": "2026-07-01",
      "amount": 25.0
    }
  ]
}
```

Accepted bulk array keys: `subscribers`, `users`, `items`, `purchases`.

Recommended migration product keys:

- `vip_chat_lv`: Latvian VIP chat.
- `vip_chat_ru`: Russian VIP chat.
- `scanner_chat`: PRO Market Scanner / AI Signals.
- `monthly`: legacy one-month VIP plan. Prefer explicit chat product keys for imports when possible.

Idempotency:

- Send a stable `event_id` or `order_id`. Repeated webhooks with the same `payment_system + event_id` are ignored as duplicates.
- For bulk imports, send a stable `batch_id`. If an item has no own `event_id`, the bot creates a stable item event id from `batch_id + item index + item data`.

Security:

- Set `WEBHOOK_SECRET` in `.env`.
- Send either `X-Webhook-Secret: <WEBHOOK_SECRET>` or `X-Webhook-Signature`, an HMAC-SHA256 hex digest of the raw JSON body using `WEBHOOK_SECRET`.
