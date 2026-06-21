# Internal Pipeline API Contract

`POST /internal/pipeline/run`

## Request

```json
{
  "seller_message": "required string",
  "conversation_context": [],
  "room_type": "support",
  "metadata": {
    "message_id": "202375",
    "room_id": "48423",
    "shop_id": "7304",
    "case_id": "optional"
  }
}
```

- `seller_message` — required; current inbound seller text.
- `conversation_context` — optional prior thread messages.
- `room_type` — optional Inchand room type (`support`, `complaint`, `cancelation`, `fund`, etc.).
- `metadata` — optional correlation IDs. `shop_id` is passed into tool execution context.

## Conversation context rules

- Map Inchand `sender=shop` → `role=user`
- Map Inchand admin/system messages → `role=assistant`
- Order messages oldest → newest
- Exclude the current seller message from `conversation_context` (it belongs in `seller_message`)
- Recommended max history: 10 messages

## Response

Safe fields only. No `shop_id`, seller message, tokens, URLs, or raw tool payloads.

Key fields:

- `message_id`, `room_id` — echoed from request metadata
- `needs_human_review` — true for human follow-up / escalation
- `should_send` — false when `needs_human_review=true`
- `send_gated` — true when reply was replaced by acknowledgement
- `final_reply_source` — `template`, `template+enrichment`, or `send_gate`
- `final_reply` — text safe to deliver when `should_send=true`

## Poller mapping (Inchand message)

| Inchand field | API field |
|---------------|-----------|
| `content` | `seller_message` |
| `room_type` | `room_type` |
| `id` | `metadata.message_id` |
| `room_id` | `metadata.room_id` |
| `shop_id` | `metadata.shop_id` |
| prior messages | `conversation_context` |
