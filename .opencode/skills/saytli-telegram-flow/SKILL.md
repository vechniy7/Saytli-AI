---
name: saytli-telegram-flow
description: Architecture and UX patterns for aiogram 3.x Telegram bot handlers in Saytli AI. Use when adding callback queries, conversational state machines (FSM), rate limiting, edit/rollback commands, or error handling.
---

# Saytli Telegram Bot Flow

## Principles & Requirements
1. **Ownership & Access Control**:
   - Ensure users can only edit, rollback, or delete websites they own (`user_id == site["user_id"]`).
2. **Callback Handling**:
   - Implement explicit handlers for all inline keyboard buttons (`edit:{site_id}`, `rollback:{site_id}`, `delete:{site_id}`, `preview:{site_id}`).
   - Always call `await callback.answer()` to dismiss loading states.
3. **FSM State Management**:
   - Isolate generation states per user with timeouts.
   - Handle `/cancel` cleanly at any stage of website creation or modification.
4. **Rate Limiting & Queueing**:
   - Throttle concurrent LLM generation per user to prevent credit exhaustion and server overload.
   - Provide clear progress notifications (e.g. "Generating structure...", "Refining styles...").
5. **Resilience & Proxy Compatibility**:
   - Support Cloudflare Worker reverse proxy fallback for Telegram API webhooks/polling.
   - Gracefully handle Telegram API timeouts and message editing limitations.
