---
name: saytli-publisher-security
description: Security verification and hardening for Saytli AI site publishing, HTML sanitization, CSP rules, path traversal defenses, and static file serving. Use when auditing or modifying HTML rendering, Caddy/FastAPI serving endpoints (/s/{site_id}), or sandbox controls.
---

# Saytli Publisher Security

## Scope & Objective
Ensures generated websites published on `saytli-ai.ru/s/{site_id}` cannot execute malicious scripts against host domains, steal visitor credentials, exfiltrate private data, or escape their assigned directory.

## Core Security Rules
1. **Directory Isolation & Path Traversal Prevention**:
   - `site_id` must strictly match `^[a-zA-Z0-9_-]{6,32}$`.
   - Never resolve paths directly from untrusted input using string concatenation.
   - Always resolve via `site["path"]` in metadata or verify `.resolve().is_relative_to(SITES_DIR)`.
2. **HTML Sanitization & CSP**:
   - Disallow `javascript:` and arbitrary `data:` URIs in `<a>`, `<iframe>`, `<form>` tags.
   - Restrict external scripts to approved CDNs (e.g. Tailwind CDN, FontAwesome, Lucide, Google Fonts).
   - Require Caddy / FastAPI to inject strict `Content-Security-Policy` and `X-Content-Type-Options: nosniff`.
   - Ensure user-generated sites are served on an isolated subdomain or sandbox origin if cookies/tokens are shared.
3. **Form & Data Protection**:
   - Forbid arbitrary backend POST targets that mimic Saytli internal services.
   - Sanitize user prompts and AI-injected payloads.
4. **Secret Protection**:
   - Never expose Telegram Bot Tokens, OpenRouter API keys, or server paths in client-facing HTML or repository files.
   - Revoke and replace any hardcoded tokens (e.g. `bot_relay_test.py`).
