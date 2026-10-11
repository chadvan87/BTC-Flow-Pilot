# Test report — BTC FlowPilot V5 DEMO foundation

Executed in the supplied Linux workspace on 2026-10-11.
Python 3.12.14; Node 24.19.0; npm 11.9.0. Tested dependencies are pinned in
backend/requirements.txt and requirements-lock.txt; frontend has package-lock.json.

## Completed checks

| Check | Actual result | Evidence / scope |
|---|---|---|
| Python compilation | PASS | `python -m compileall -q app research tests` |
| Pytest | PASS: 57 tests | `python -m pytest -q`; unit + mocked integration/API tests |
| TypeScript strict compilation | PASS | `tsc --noEmit`, invoked by npm build |
| Vite production build | PASS | 766 modules, built frontend/dist |
| SQLAlchemy initialization | PASS on SQLite | In-memory test and persistent file reopen; startup smoke |
| Auth / CSRF / encrypted credentials | PASS | Unauthorized API rejected; CSRF/origin blocked; ciphertext and no plaintext retrieval |
| STOP / restart / REAL lock | PASS with mocks | Default STOP, no automatic resume; REAL non-GET client calls blocked |
| Entry tolerance / risk / filters | PASS | ATR tolerance, tick, short symmetry, costs, min size, margin, hard caps |
| Idempotency / unknown entry | PASS with mocks | Timeout accepted by fake exchange then queried; no second entry; payload conflict rejected |
| Protection / partial fills | PASS with mocks | SL query failure stops; partial fill stops; attributes verified |
| Flatten / recovery | PASS with mocks | Flat verified then conditional cancel; restart reconciliation without entry retry |
| Account preflight | PASS with mocks | Position, pending orders, hedge/cross/10x, daily loss, streak, stale quote, tiny margin and absent news blocked |
| Signed Binance algo request | PASS via httpx MockTransport | HMAC, endpoint, closePosition, triggerPrice, no invalid quantity/reduceOnly pair |
| Order book / trades | PASS on fixture events | Snapshot boundary, pu gap, absolute quantities, deletion, stale flag, deduped executed delta |
| Research metric primitives | PASS | Empty metrics remain null, known return series metrics verified |
| Render / Compose YAML | PASS syntax + basic structure only | PyYAML parse and services presence; NOT provider schema validation |
| Local server startup / dashboard assets | PASS | Uvicorn starts, /health and authenticated API; built dashboard served same origin |

Initial pytest run: 39 pass / 4 fail. Corrected SQLite in-memory connection pool
and installed HTTPX SOCKS dependency, then extended preflight/client cases.
Final run: 57 passed, 1 warning. Warning is Starlette TestClient deprecation
of HTTPX in favor of httpx2, not a test failure.

Vite warns main JS chunk is about 522 kB (>500 kB). Build succeeds. Code splitting
can be added later; this is a performance warning, not evidence of UI failure.

## Update 2026-10-11 (local macOS session)

macOS, Python 3.12, Node 22.20.0. Added 9-symbol list, status bar states, and
experimental AUTO DEMO entries (strategies A_CHECKLIST and B_RETEST).

| Check | Actual result | Evidence / scope |
|---|---|---|
| Pytest | PASS: 91 tests | Includes rule tests for both strategies, auto loop gating (auto off / STOP / news), preview-reject without STOP, idempotent signal IDs, loss-streak auto-off, API confirm/RUNNING requirements |
| TypeScript + Vite build | PASS | Main chunk still >500 kB warning |
| Live Demo public feeds | PASS (observed) | All 9 symbols: depth synced + fresh, trades fresh, REST fresh, via authenticated local API |
| Live Demo signed account read | PASS (observed) | Test connection returned account balance |
| Live Demo AUTO or manual order lifecycle | NOT VERIFIED | No order had been placed when this was written |

AUTO results must come from the month-long Demo forward test; no performance is claimed.

### Whale Confirmation Engine

| Check | Actual result | Evidence / scope |
|---|---|---|
| Pytest | PASS: 138 total (47 whale tests) | Classification incl. flips, partial fills/TWAP merge, price-only notional change, baseline, tid dedupe, WS snapshot replay, REST backfill, size-only reconcile, 429 retry, weight limiter, stale/missing/no-equity data, single-whale dominance, related-wallet clusters, conflicting, cohort N/A, symbol mapping (incl. kPEPE), discovery verification, require-confirmation block, AUTO ranking without setup changes, API |
| Live Hyperliquid smoke (in-memory DB) | PASS (observed) | 3 active public wallets: baselines created 0 actions; WebSocket streamed 98 fills in 75s; 59 actions classified; up to 18 fills merged; second clearinghouseState reconciled with 0 unexplained size changes; metaAndAssetCtxs 234 markets |
| Whale influence on real entries | NOT VERIFIED | No Demo order placed with whale context; usefulness of whale bias is unmeasured |
| Coin discovery on live data | NOT VERIFIED | Logic tested with fake Binance responses only; no live suggestion observed |

### PostgreSQL (local Docker, 2026-10-11)

| Check | Actual result | Evidence / scope |
|---|---|---|
| Full pytest on PostgreSQL 16 | PASS: 138 | `TEST_DATABASE_URL=postgresql+psycopg://… pytest` against a disposable postgres:16 container |
| Large record / upsert / reopen | PASS | 4000-fill whale record (~1 MB) round-trip 27 ms write / 15 ms read; upsert; persistence across Store re-open |
| Server boot on PostgreSQL | PASS | Startup STOP, login, Binance Demo feed synced, whale collector running; no errors in log |
| Managed/hosted PostgreSQL (SSL, Render) | NOT EXECUTED | Local container only |
| Render deployment | NOT EXECUTED | Blueprint region set to frankfurt (Binance blocks US IPs); not yet deployed |

## Not verified / blocked

- **Live Binance DEMO integration and order lifecycle: NOT VERIFIED.** No API keys
  supplied. One public `/fapi/v1/time` call was attempted; upstream rejected it
  (ExchangeError). No signed live order/SL/TP request was made.
- **Actual Demo WebSocket handshake, DOM sequencing and reconnect: NOT VERIFIED.**
  Algorithm tests use fixture events; current endpoint routing requires a live
  supervised smoke test in the user's network.
- **Hosted PostgreSQL and Render deployment: NOT EXECUTED** (local PostgreSQL 16 tested 2026-10-11, see above).
  SQLite tests do not establish PostgreSQL availability, SSL or Render compatibility.
- **Visual browser QA: NOT COMPLETED.** Playwright package was available but the
  Chromium executable was absent. Browser download failed with invalid/truncated
  archive in this network. Eight-tab desktop/mobile smoke script could not run.
  No browser screenshots or visual QA success are claimed.
- Hyperliquid live wallet requests and Telegram delivery: NOT EXECUTED.
- Windows/macOS setup, Python 3.11 and Node 22: NOT EXECUTED. uvloop pin includes a
  Windows exclusion; remaining dependencies need platform smoke tests.
- Full research recorder/replay on a live/historical dataset and full baseline
  CSV report: NOT EXECUTED. No dataset was supplied and none was invented.
- No full strategy, DOM backtest, walk-forward optimization, strategy ablation
  or profitability validation has been completed.

## Material limitations

See docs/FEATURE_MATRIX.md for detailed scope. AUTO is DEMO-only, experimental and
unvalidated; full secondary-test absorption and zone state machines are not implemented. REAL is locked.
Reconciliation uses periodic REST, not user-data streams. If SL cannot be
verified, entries stop and the operator must inspect/flatten promptly; there
is no autonomous repair/close policy. Planned risk is not an absolute loss cap.
Account ledger pagination, complete round-trip loss attribution, virtual equity
compounding, migrations, multi-instance fencing, MFA and notification queues
are not implemented. Dedicated Demo account + one process are mandatory.

This ZIP is a supervised DEMO development foundation, not a production-ready
unattended trading system. No win rate/ROI/30–35% monthly return is reported.
