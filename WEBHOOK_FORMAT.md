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

Required fields:

- `email`: must match the e-mail registered in the bot.
- `payment_system`: payment provider used on the website, for example `stripe`, `paypal`, `bank`, `crypto`.
- `product_key`: use `monthly` for the 1-month VIP subscription, or a custom key if `subscription_days` is provided.
- `subscription_days`: how many access days should be added. If `product_key` is a known bot plan and this field is missing, the bot uses the configured plan duration.

Idempotency:

- Send a stable `event_id` or `order_id`. Repeated webhooks with the same `payment_system + event_id` are ignored as duplicates.

Security:

- Set `WEBHOOK_SECRET` in `.env`.
- Send either `X-Webhook-Secret: <WEBHOOK_SECRET>` or `X-Webhook-Signature`, an HMAC-SHA256 hex digest of the raw JSON body using `WEBHOOK_SECRET`.
