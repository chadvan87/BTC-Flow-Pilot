# BTC FlowPilot V5 — instructions for Claude Code / Codex

This is a DEMO foundation, not an autonomous production bot. Read README.md,
docs/FEATURE_MATRIX.md, TEST_REPORT.md and all execution/risk/security modules first.

## Invariants
- REAL trading is permanently disabled in Binance.request for every non-GET method.
  Do not add a toggle that can enable it. REAL credentials are read-only.
- AUTO execution exists for DEMO only as an experimental, UNVALIDATED forward test (owner decision
  2026-10-11). Never represent it as validated or complete; never add an AUTO path for REAL.
  AUTO must stay behind its own switch, go through engine.preview()/submit(), and turn off on STOP/restart.
- Do not weaken Risk Engine, guards, exchange filters, confirmation, STOP or credentials security.
- STOP survives restart; startup always STOP. Never auto-resume.
- Never retry an ambiguous market entry. Persist intent first and query stable client ID.
- HTTP 200 alone does not mean SL/TP protection. Verify exchange-side algo attributes/status.
- Dedicated account, single process, single worker. Async locks are not distributed locks.
- Secrets must never enter Git, frontend build, localStorage, response bodies or logs.
- Do not fabricate candles, backtests, win rate, ROI, test outcomes or live data.

## Commands
From backend (virtual environment active):
```
python -m compileall -q app research tests
python -m pytest -q
```
From frontend:
```
npm ci
npm run typecheck
npm run build
```
Validate YAML syntax and actual Render Blueprint UI separately. Re-run relevant
fault tests after changing order handling. Use fixtures/mocks unless the owner
explicitly enters DEMO keys and requests an exchange test. Do not request secret
keys in chat. Do not execute REAL orders.

## API verification
Re-check official Binance developer documentation: DEMO domains, fapi v3 account
and positionRisk, symbolConfig, algoOrder, openAlgoOrders, depth sequencing and
WebSocket routing. The retrieved Binance documentation had a migrated catalog;
local-order-book page returned sparse content. Sequence implementation follows
Futures U <= lastUpdateId <= u then pu == previous u; verify on the actual feed
before supervised Demo orders. General information and REST algo paths were
verified against official docs on 2026-10-11; live execution was NOT verified.

## Fix order
1. Syntax/import/dependency failures; use requirements/lock and npm lockfile.
2. Database startup/persistence, encryption and login/CSRF/TLS.
3. CORS and cookie behavior; prefer combined same-origin hosting.
4. Feed reconnect/resync, freshness, recorder integrity and correct trade sign.
5. Account checks, fees, loss accounting, market filters and idempotency.
6. Partial/ambiguous fill recovery, protection verification, flatten cleanup.
7. Full strategy state machines and tests, then replay/backtest validation.

Never patch an error by ignoring validation or returning fake success. Document
remaining defects honestly in TEST_REPORT.md. Do not claim real API integration,
PostgreSQL or Render deployment passed based only on mocked tests.

## Roadmap ownership
Implement PostgreSQL migrations and distributed fencing before multi-worker use.
Add authenticated user-data stream plus robust paginated account ledger, complete
fee/funding accounting, alert delivery retries and operator escalation. Add real
zone/secondary-test/retest lifecycle, replay-aware clock, calibrated absorption,
full strategy ablation and historical depth data. Keep automatic entries DEMO-only
until validated. Cross-platform and Render smoke tests are still required.
