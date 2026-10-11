# API sources reviewed on 2026-10-11

Official Binance General Info:
https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/general-info

Official migrated USD-M REST trade catalog (New/Query/Cancel Algo Order):
https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/trade

Original depth synchronization reference (page currently sparse in retrieved view):
https://developers.binance.com/docs/derivatives/usds-margined-futures/websocket-market-streams/How-to-manage-a-local-order-book-correctly

Hyperliquid official perpetual account info:
https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint/perpetuals
Hyperliquid info endpoint (userFills, userFillsByTime), rate limits, WebSocket
subscriptions and heartbeats (reviewed 2026-10-11):
https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint
https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits
https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions
https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/timeouts-and-heartbeats
Docs do not define fill `side`; live fills on 2026-10-11 showed B=buy, A=sell, a
signed startPosition, flips as "Long > Short"/"Short > Long", and a twapId field.

Render free limitations:
https://render.com/docs/free

The docs identify https://demo-fapi.binance.com and wss://demo-fstream.binance.com.
Conditional protection uses POST /fapi/v1/algoOrder with algoType=CONDITIONAL,
triggerPrice, closePosition=true, workingType=MARK_PRICE and clientAlgoId;
query protection with GET /fapi/v1/algoOrder. This implementation rejects hedge
mode and uses BOTH positionSide. It never combines closePosition with quantity
or reduceOnly. Emergency market closure uses quantity and reduceOnly=true.

Documentation review is not a live compatibility test. Endpoint availability,
WebSocket URL routing, status enum behavior and close-position protection must
be rechecked with current official docs and a dedicated Demo account.
