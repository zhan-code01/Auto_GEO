# AGENTS.md Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the repository guidance accurate, safe to execute, and resilient to changes in the current optimization roadmap.

**Architecture:** Keep stable repository rules and canonical verification commands in `AGENTS.md`; leave time-bound optimization detail in `docs/AutoGEO优化方案_2026-09.md`. This change is documentation-only and does not alter application behavior, CI, or package scripts.

**Tech Stack:** Markdown, PowerShell read-only checks, Git repository metadata.

---

### Task 1: Correct repository map and scope rules

**Files:**
- Modify: `AGENTS.md`

- [ ] Replace the inaccurate `tests/e2e` description with the current `frontend/e2e` location and state that the roadmap applies conditionally to optimization work.
- [ ] Mark the external `../research` directory as optional background material that must not block work.
- [ ] Add source-of-truth and generated-output guidance.

### Task 2: Make verification commands safe and reproducible

**Files:**
- Modify: `AGENTS.md`

- [ ] Separate read-only lint/type checks from auto-fix commands.
- [ ] Align backend commands with the current CI commands for Ruff, format, MyPy, and unit tests.
- [ ] Document PostgreSQL test database and required environment prerequisites before running tests.
- [ ] Document the migration command from the authoritative `backend/` working directory and require upgrade/downgrade validation.

### Task 3: Add scoped testing and deployment guardrails

**Files:**
- Modify: `AGENTS.md`

- [ ] Add a change-to-verification matrix for backend, frontend, migrations, and external automation.
- [ ] Mark production Compose/deploy commands as explicit-user-request operations and point to the production runbook for `.env` initialization.
- [ ] Require mock/sandbox behavior for tests that could call external AI, browser, or publishing systems.

### Task 4: Verify the documentation change

**Files:**
- Verify: `AGENTS.md`
- Verify: `frontend/package.json`
- Verify: `.github/workflows/ci.yml`
- Verify: `tests/conftest.py`

- [ ] Check that every command named in `AGENTS.md` exists in the referenced package/configuration files.
- [ ] Check that all referenced repository paths exist or are explicitly marked optional.
- [ ] Inspect the final diff and confirm no application or CI files were changed.
