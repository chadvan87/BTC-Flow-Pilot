# Delivered scope / honest feature matrix

| Area | Implemented | Limitation / remaining work |
|---|---|---|
| Symbols | BTC, ETH, LINK, SOL, XRP, TRX, DOGE, NEAR, AAVE (USDT-M), single list in `app/config.py` | Per-symbol volume-profile bin is fixed, not adaptive to price changes |
| React terminal | 8 tabs, responsive, dark theme, live API polling, Recharts profile | No continuous exchange equity chart, analytics data import UI or browser E2E test suite |
| Authentication | Admin login, signed 1h HttpOnly cookie, origin + CSRF header, login throttle | No MFA, multi-user RBAC, durable rate limit or session revocation list |
| Credentials | Environment-separated encrypted key/secret in SQLAlchemy store, no retrieval endpoint | Encryption-key rotation and external vault not implemented |
| Environments | DEMO execution, REAL read-only client barrier | No REAL execution path, no automatic switching with managed positions |
| Manual DEMO | Preview, confirmation, risk/account/news/crash checks, market entry, algo SL/TP verification | Live exchange not verified; partial fill is stopped and handed to operator |
| Protection | Durable states, stable client IDs, query after timeout, exact attributes, periodic REST reconciliation | No user-data stream, no automatic repair/close if SL fails; operator must flatten promptly |
| STOP / RESUME | Persisted STOP, manual resume, startup STOP, protects existing position | Requires healthy feed/news and no unresolved managed records to resume |
| FLATTEN DEMO | Managed symbols only, reduce-only market close, cancel pending entries, verify flat then cleanup | Dedicated Demo account mandatory; ambiguous ownership or API failure needs manual exchange inspection |
| Risk | Planned 0.5%, daily income loss 1.5%, 3 attempted entries, two losing closes (operator can clear after review, audit-logged), one account position, 2x isolated, net RR >=2, filters | Fixed 175 USDT cap; not a complete compounding virtual-equity ledger. Closing-order loss streak conservatively excludes entry fees; not full round-trip attribution |
| Order flow | Buffered snapshot + sequence checks, reconnect, imbalance, 5-second liquidity age, trade delta/CVD, footprint, 5m POC/VA, OI/funding | Public Demo feed unverified; CVD resets on reconnect; absorption is experimental price-response heuristic |
| Trend context | EMA50/200, confirmed pivots, Wilder ADX/ATR, BOS candidates | CHOCH and full zone lifecycle incomplete |
| Strategy A/B | Confirmation checklist; rule-based A_CHECKLIST (all checklist rows) and B_RETEST (15m breakout + retest + 5m delta), both 2.5R, in `app/strategies/auto.py` | Rules are UNVALIDATED (no backtest/replay results); secondary-test absorption lifecycle NOT implemented; B_RETEST is stateless candle logic, not a full zone state machine |
| AUTO DEMO entries (added 2026-10-11) | Separate operator switch, DEMO only; dry preview then normal submit; one trade at a time; STOP/restart turn AUTO off; loss streak turns AUTO off; orders tagged by strategy | Experimental forward test only. Not verified against live Demo execution; skip/decision log is in memory (lost on restart); no per-strategy performance report yet |
| News / crash | Manually reviewed expiring UTC calendar, blackout +/-60min, stale/spread/15m move/range guards | No automatic CPI/FOMC/NFP provider; ATR spike is a range heuristic, not calibrated |
| Whale Confirmation Engine (2026-10-11) | Hyperliquid userFills WebSocket (first 10 wallets) + REST userFillsByTime/clearinghouseState reconcile, baseline snapshot, tid dedupe, 429 retry + self weight limit; signed-size OPEN/ADD/REDUCE/CLOSE, flip split, partial/TWAP merge; per-coin decayed bias with cluster + dominance caps; monitored-wallet Long/Short cohort; setup ranking + optional require-confirmation block; coin discovery with Binance verification into research watchlist | Weights/thresholds unvalidated; history factor is a crude realised-PnL heuristic; HIP-3 and spot fills ignored; userFillsByTime page size documented inconsistently (500 vs 2000) so paging is conservative; per-item request weight undocumented (assumed 1/20 items); research coins have no Binance order-flow feed; no copy trading |
| Research | JSONL recorder, sequence replay, candle EMA baseline, costs, OOS, fixed folds, basic metrics/bootstrap | NOT full FlowPilot backtest; no historical funding, full ablation, execution simulation or validated DOM results |
| Deployment | Combined same-origin Render Blueprint + optional Static Site template + PostgreSQL Compose | YAML checked locally only; no Render deployment or PostgreSQL server test executed |
| Alerts | Telegram on STOP and protected Demo entry | Env-configured only; no retry queue, delivery verification or frontend token editor |

## Go-live restriction
This release is intended for development, recording and supervised DEMO tests.
100+ valid Demo trades plus fault-injection exercises are a suggested validation
milestone, not sufficient evidence of profitability or readiness on their own.
The 30–35% monthly goal was not used as an assumption or reported outcome.
