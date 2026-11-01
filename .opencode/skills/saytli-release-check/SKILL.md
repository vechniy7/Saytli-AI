---
name: saytli-release-check
description: Deployment, Docker container orchestration, environment variable audits, and production release verification for Saytli AI on Linux VDS. Use before building images, updating Docker Compose, configuring Caddy, or launching production updates.
---

# Saytli Release Checklist & Runbook

## Pre-Release Verification
1. **Secrets & Credentials**:
   - Verify `TELEGRAM_BOT_TOKEN`, `OPENROUTER_API_KEY`, and internal secrets exist only in `.env` (never committed).
   - Ensure leaked token test scripts are eliminated.
2. **Container Security**:
   - Ensure Dockerfile executes under a dedicated non-root user (`saytli:saytli`).
   - Restrict volume mounts to writable directories (`/app/data`).
3. **Storage & Multi-Process Safety**:
   - `data/sites.json` access must use file locks (`fcntl`/`portalocker`) or SQLite to prevent race conditions between FastAPI and aiogram worker.
4. **Health Check & Reverse Proxy**:
   - FastAPI exposes `GET /health` responding with status 200 and storage/LLM check.
   - Caddyfile terminates SSL, binds to `saytli-ai.ru`, and proxies `127.0.0.1:8080`.
5. **Post-Deployment Smoke Test**:
   - Verify `https://saytli-ai.ru/health`.
   - Verify sample site `/s/demo`.
   - Test Telegram bot `/start` responsiveness.
