---
name: fix-vulns
description: >
  Fix security vulnerabilities from scanner reports (XLSX). Trigger on: vulnerability 
  report files (.xlsx), CVE IDs, requests to patch/bump dependencies for security reasons.
---

# Vulnerability Fix Workflow

## Phase 1: Parse the Report

Read XLSX with openpyxl (or pandas if available). Find columns by **semantic meaning**:

- CVE ID
- Severity
- Component
- Current & Fix version
- Issue layer (APP → dependency files; OS → Dockerfile base image)
- Microservice name
- Physical path

If file has **multiple sheets**, check all.

**Filter:**
- Keep only `High` and `Critical` severity
- Process all microservices including tests — but handle test services separately (see Phase 2b)
- Deduplicate: same CVE + same component = one item

---

## Phase 2: Locate and Fix

For each affected microservice, trace where vulnerable component introduced and apply fix:

- **APP layer** — dependency files (go.mod, package.json, requirements.txt, etc.)
- **OS layer** — Dockerfile base image and package installs

If fix not in obvious places, dig deeper into codebase to find actual source.

**Fix version selection:** Use `Fix Version` from report. If multiple versions listed, pick highest patch of current minor or latest overall. If no fix version — skip.

Apply changes one microservice at a time.

---

## Phase 2b: Test Services — Internal Base Images

Test services often use internal or organization base images (e.g. `ghcr.io/netcracker/...`, `ghcr.io/<org>/...`) rather than standard Alpine/Debian. When CVEs appear for a test service:

1. **Find the Dockerfile** for the test service in the repo (e.g. `tests/*/Dockerfile`).

2. **Inspect the `FROM` line.** If it references an internal/org image:
   - Fetch `https://github.com/<org>/<repo>/tags` and list available versions newer than the current tag
   - If a newer version exists with security-related release notes → bump the tag in the Dockerfile to the latest stable

3. **APP layer CVEs** — fix in the test service's own `requirements.txt` / `package.json` / etc. as usual.

4. **OS layer CVEs that remain** — if the Dockerfile already runs `apk upgrade --no-cache --available`, remaining OS CVEs are blocked on upstream package availability; document as "fix version not yet in OS repository".

---

## Phase 3: Assess Unfixed CVEs

For each CVE not fixed (no fix version, or fix breaks compatibility), check if project actually uses vulnerable feature (imports, config files, what binary does). Write one-line verdict: **"Not affected — [reason]"** or **"Potentially affected — [reason]"**.

E.g. PostgreSQL CVE in Redis-only service likely not applicable.

---

## Phase 4: Write the Report

Generate `vuln-report-<YYYY-MM-DD>.md` in repo root.

**Report has two sections:**

**1. Fixed CVEs:**

| CVE | Severity | Component | Fix | File changed |
|-----|----------|-----------|-----|--------------|

**2. Unfixed CVEs:**

**Rules:**
- One row per unique CVE (not per component instance)
- `Reason` = why not fixed (no fix version, compatibility block, source repo not in this project)
- `Impact` = concrete explanation — does project actually trigger vulnerability? Reference specific features, protocols, or code paths

| CVE | Severity | Components | Reason | Impact |
|-----|----------|------------|--------|--------|
