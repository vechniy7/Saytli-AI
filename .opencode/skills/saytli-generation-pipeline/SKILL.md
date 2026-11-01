---
name: saytli-generation-pipeline
description: Pipeline orchestration and verification for Saytli AI website generation and modification. Use when modifying prompt builders, LLM generation routines, site editing/versioning, quality scoring, or automated smoke testing.
---

# Saytli Generation Pipeline

## Architecture Overview
Saytli AI generates production-ready single-page landing pages and sites from natural language prompts using LLMs, post-processing filters, static quality audits, and automated browser verification.

## Unified Generation Stages
Both **initial generation** and **subsequent edits** must pass through the identical validation gate:

```
User Prompt (Telegram/API)
   │
   ▼
[1] Skill & Design System Routing (skills.py, design_systems.py)
   │
   ▼
[2] LLM Synthesis (ask_ai / OpenRouter)
   │
   ▼
[3] HTML Extraction & Sanitization
   - Extract Clean <html>...</html> block
   - Sanitize forbidden protocols (javascript:, data:)
   - Strip prompt injection or conversational remnants
   │
   ▼
[4] Quality & Repair Gate (quality.py)
   - Ensure viewport meta tag exists
   - Verify non-empty DOM (>500 bytes visible text, interactive elements)
   - Patch missing essential libraries (Tailwind, Lucide)
   │
   ▼
[5] Static Pipeline Review (pipeline.py)
   - Score structure, visual contrast, responsive breakpoints
   - Reject or auto-fix broken markup
   │
   ▼
[6] Browser QA Verification (Playwright CLI / browser_qa.py)
   - Check console errors: 0 unhandled exceptions allowed
   - Check broken resource 404s
   - Verify interactive elements (buttons, mobile menus)
   │
   ▼
[7] Atomic Write & Version Commit
   - Save versioned HTML (`v{n}/index.html`)
   - Update `data/sites.json` metadata atomically
   - Update active pointer `site["path"]`
```

## Rollback Policy
- When editing a site fails quality or smoke verification, the active pointer remains on the previous verified version (`v{n-1}`).
- The Telegram UI must provide immediate one-click rollback if a user dislikes an edit.
