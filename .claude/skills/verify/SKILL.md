---
name: verify
description: Run Echo's canonical verification gate end-to-end and report the real output before claiming work done or committing. Failing output gets pasted, fixed, and re-run — never summarized away.
---

# Verify — Echo

Honesty rules: paste actual command output (not a summary), fix failures, re-run until green,
and state explicitly anything you could NOT verify (live-stack-only paths, GPU-gated paths).
A skipped step is reported as skipped, never implied as passing.

## Gate

1. `python -m pytest` (channel adapter tests).
2. Adapter changes: smoke against the live bridge if the stack is up (Telegram `@Chimerabetabot` is production — flag risky changes instead of live-testing them).
