---
name: ecosystem_state
description: Auto-generated snapshot of all 8 Chimera repos — LOC, tests, commits, key files. Regen: python ~/.claude/scripts/ecosystem_snapshot.py
type: reference
---

# Chimera Ecosystem State (2026-05-27 14:44)

**Totals: 2,018,715 LOC, 3352 tests, 8 repos**

## Banterpacks
**Core intelligence — JARVIS, TDD002, Chimera, TDD005, RLAIF, Authoring**
- LOC: **171,033** (.py: 149,066, .rs: 19,187, .js: 1,826, .sql: 954)
- Tests: **1789**

Recent:
- `9159238 (P105.3) fix degraded debates: local model + adapt-to-available + generation timeout`
- `50b01a8 (P105.2) streaming -> Muse: self-initializing OTel export`
- `30b1428 (P105.1) chimera debate cost/consensus -> Muse; TDD005 pointed at collector`
- `8263146 (P105.0) OTel Collector hub: single OTLP pipeline -> ClickHouse (Muse owns all telemetry)`
- `f31df34 (P104.10) note: Watchdog heartbeat pipeline proven end-to-end (local sink); only external URL remains`

<details><summary>Key files (40)</summary>

- jarvis\src\jarvis\auth.py (112)
- jarvis\src\jarvis\banterhearts_canary.py (313)
- jarvis\src\jarvis\banterhearts_registry.py (226)
- jarvis\src\jarvis\budget.py (245)
- jarvis\src\jarvis\calendar\ics.py (170)
- jarvis\src\jarvis\circuit_breaker.py (166)
- jarvis\src\jarvis\concurrency.py (85)
- jarvis\src\jarvis\config.py (206)
- jarvis\src\jarvis\deps.py (84)
- jarvis\src\jarvis\embeddings.py (225)
- jarvis\src\jarvis\gateway\app.py (508)
- jarvis\src\jarvis\gateway\audit.py (98)
- jarvis\src\jarvis\gateway\http.py (349)
- jarvis\src\jarvis\gateway\pipeline\chimera.py (224)
- jarvis\src\jarvis\gateway\pipeline\deterministic.py (184)
- jarvis\src\jarvis\gateway\pipeline\policy.py (140)
- jarvis\src\jarvis\gateway\pipeline\turn.py (756)
- jarvis\src\jarvis\gateway\routes\__init__.py (81)
- jarvis\src\jarvis\gateway\routes\approvals_control.py (227)
- jarvis\src\jarvis\gateway\routes\audits_trace_dashboard.py (461)
- jarvis\src\jarvis\gateway\routes\awareness.py (146)
- jarvis\src\jarvis\gateway\routes\calendar_inbox.py (362)
- jarvis\src\jarvis\gateway\routes\chat.py (390)
- jarvis\src\jarvis\gateway\routes\cognitive.py (83)
- jarvis\src\jarvis\gateway\routes\core.py (82)
- jarvis\src\jarvis\gateway\routes\devices_mesh.py (355)
- jarvis\src\jarvis\gateway\routes\dsr.py (84)
- jarvis\src\jarvis\gateway\routes\inbox_drafts.py (269)
- jarvis\src\jarvis\gateway\routes\inbox_priority.py (256)
- jarvis\src\jarvis\gateway\routes\memory_user.py (118)
- jarvis\src\jarvis\gateway\routes\notifications.py (100)
- jarvis\src\jarvis\gateway\routes\outbox.py (435)
- jarvis\src\jarvis\gateway\routes\p2p_mesh.py (274)
- jarvis\src\jarvis\gateway\routes\peer_profiles.py (369)
- jarvis\src\jarvis\gateway\routes\peer_requests.py (323)
- jarvis\src\jarvis\gateway\routes\peers.py (321)
- jarvis\src\jarvis\gateway\routes\planner.py (183)
- jarvis\src\jarvis\gateway\routes\proactive.py (141)
- jarvis\src\jarvis\gateway\routes\provenance.py (101)
- jarvis\src\jarvis\gateway\routes\state_learning_constitution.py (230)
</details>

## Chimera_Multi_agent
**Muse Protocol — observability, autonomous remediation agents**
- LOC: **17,797** (.py: 17,797)
- Tests: **103**

Recent:
- `be16322 fix: add from __future__ import annotations to 37 files â€” deprecated typing imports (P97.3 deprecated_imports)`
- `0b77cf8 feat: real OTLP gRPC receiver with health scrape fallback (94.3 otlp_receiver)`
- `5955ac5 fix: TDD-008 audit â€” health subscription, fixer mappings, watcher fixes`
- `a5a976c fix: CI green â€” add missing playbook JSONs, fix lint (E704, F811, E401)`
- `48b77d7 feat: TDD-008 Muse â€” constitutional observability with autonomous remediation`

<details><summary>Key files (38)</summary>

- muse\contracts\types.py (258)
- muse\fixers\base.py (116)
- muse\fixers\circuit_resetter.py (96)
- muse\fixers\dlq.py (205)
- muse\fixers\dlq_replayer.py (94)
- muse\fixers\playbook_runner.py (258)
- muse\fixers\provider_rerouter.py (117)
- muse\fixers\workflow_resumer.py (129)
- muse\ingestion\event_bus.py (123)
- muse\ingestion\health_poller.py (179)
- muse\ingestion\otlp_receiver.py (269)
- muse\runtime.py (443)
- muse\triagers\base.py (114)
- muse\triagers\dependency_graph.py (98)
- muse\triagers\workflow.py (108)
- muse\watchers\budget_overrun.py (98)
- muse\watchers\calibration_drift.py (115)
- muse\watchers\provider_fail.py (106)
- muse\watchers\workflow_stuck.py (117)
- agents\banterhearts_ingestor.py (441)
- agents\banterpacks.py (125)
- agents\banterpacks_collector.py (462)
- agents\chimera.py (173)
- agents\council.py (503)
- agents\i18n_translator.py (454)
- agents\publisher.py (502)
- agents\watcher.py (305)
- integrations\clickhouse.py (230)
- integrations\clickhouse_client.py (284)
- integrations\datadog.py (223)
- integrations\datadog_monitoring.py (476)
- integrations\deepl.py (271)
- integrations\ecosystem_paths.py (99)
- integrations\mcp_client.py (229)
- integrations\repo.py (209)
- integrations\retry_utils.py (165)
- integrations\secrets.py (232)
- integrations\tracing.py (158)
</details>

## Echo
**Channel adapters — Slack, Discord, Telegram, WhatsApp, Email → JARVIS**
- LOC: **3,080** (.py: 3,080)
- Tests: **68**

Recent:
- `4439643 (P104.10) echo follow-on: observability logs + tag-safe message splitting`
- `c9dee0a (P104.10) telegram hardening: double-text, non-text, slow-turn, WS-drop, auth, log-leak`
- `a7325bf (P104.9) telegram: swallow benign 'message is not modified' edit`
- `93b1ea2 fix: bridge to current JARVIS API (bare /jarvis paths + required idempotency_key)`
- `fcc2e29 feat: production Echo â€” 5 adapters, streaming, formatting, persistent sessions`

<details><summary>Key files (9)</summary>

- echo\discord\app.py (241)
- echo\email\app.py (255)
- echo\shared\client.py (220)
- echo\shared\format.py (200)
- echo\shared\sessions.py (99)
- echo\shared\stream.py (244)
- echo\slack\app.py (247)
- echo\telegram\app.py (416)
- echo\whatsapp\app.py (273)
</details>

## jarvis-console
**Web UI — Next.js dashboard (chat, control room, memory, tools, workflows)**
- LOC: **2,405** (.ts: 893, .tsx: 1,512)
- Tests: **0**

Recent:
- `6181802 feat: JARVIS console â€” Next.js web UI with chat, control room, admin panels`

<details><summary>Key files (11)</summary>

- src\hooks\useChat.ts (211)
- src\lib\jarvis-client.ts (123)
- src\lib\jarvis-ws.ts (173)
- src\lib\types.ts (241)
- src\app\calendar\page.tsx (119)
- src\app\control-room\page.tsx (182)
- src\app\memory\page.tsx (125)
- src\app\settings\page.tsx (152)
- src\app\workflows\[id]\page.tsx (97)
- src\app\workflows\page.tsx (82)
- src\hooks\useJarvis.tsx (114)
</details>

## Banterhearts
**Training, benchmarking, MLOps, eval framework (36 TRs, 555K measurements)**
- LOC: **274,857** (.py: 274,857)
- Tests: **1100**

Recent:
- `ea0b7fec artifacts: refresh unit-test training telemetry`
- `e62221e6 batch_inference_safety: arXiv cs.LG submission package`
- `3000ef96 batch_inference_safety: finalize accepted camera-ready`
- `89065a57 PublishReady index: bring README current to TR152 (was pinned to TR149)`
- `b1e23d97 TR155: runner + judge/launch harness updates (24/24 tests)`

## Chimeradroid
**Unity Android companion, offline-first, execution packet 100%**
- LOC: **1,415,888** (.cs: 1,415,888)
- Tests: **0**

Recent:
- `29fc040 fix: update API paths from /jarvis/v2/ to /jarvis/ â€” matches Banterpacks P92.6 prefix merge`
- `42dfa7d fix: add offline detection, targeted stream updates, drain backoff (86.10 chimeradroid_companion_gaps)`
- `93db8bb feat: verify Chimeradroid companion packet on latest Embardiment baseline (86.9 chimeradroid_packet_verification)`
- `bf047e2 Align Chimeradroid with Embardiment fork and Unity 6000.1 baseline`
- `a6e7269 Harden workflow companion loop and document packet endpoints`

## Chimeraforge
**PyPI CLI, 70K measurements, 292 tests, 4-gate capacity planner**
- LOC: **114,669** (.py: 114,669)
- Tests: **292**

Recent:
- `5b1ba74 chore: bump version to 0.2.2`
- `48a36b5 ci: add PyPI trusted publishing workflow`
- `4e01d01 fix: add from __future__ import annotations â€” deprecated typing imports (P97.3 deprecated_imports)`
- `0cd7a91 Remove duplicate legacy experiment folders`
- `1cae5ef Remove tracked PNG artifacts`

## Banterblogs
**Blog product (Next.js), episode generation from git history**
- LOC: **18,986** (.ts: 3,146, .tsx: 15,010, .js: 830)
- Tests: **0**

Recent:
- `8317dd7 feat(home): surface ICML 2026 workshop acceptance in the hero`
- `ce8a6e4 feat(papers): BIS paper accepted at ICML 2026 Workshop on Hypothesis Testing`
- `9984bc8 feat(reports): sync TR149 + TR152 (Phase 4), bump counts to 48 reports / 841K measurements`
- `f24e6fc Merge fix/scene-02-hydration-bridge into main: kill long-standing scene 02 React #418`
- `dd429a7 fix(scene-02): kill the long-standing React #418 with the same useState bridge scenes 03/04/05 use`
