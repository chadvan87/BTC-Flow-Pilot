# BTC FlowPilot V5

**Bản nền tảng DEMO có source code chạy được. REAL read-only; auto trading bị khóa.**

Đọc `docs/FEATURE_MATRIX.md` trước khi sử dụng. Hai chiến thuật đầy đủ chưa được
triển khai/kiểm chứng: dashboard cung cấp nghiên cứu order flow và regime, còn
đặt lệnh DEMO là thao tác thủ công có risk checks. Không có cam kết lợi nhuận,
win rate hoặc báo cáo backtest giả. Vốn thử nghiệm giới hạn 175 USDT, không dùng
số dư Demo lớn hơn để tăng risk budget.

## 1. Kiến trúc

React/TypeScript/Vite/Tailwind/Recharts → FastAPI → Risk / Guards / Execution →
Binance Futures DEMO. SQLAlchemy lưu control, encrypted credentials, journal và
audit; SQLite hỗ trợ chạy local nhanh, PostgreSQL dùng khi hosting. Public
WebSocket → snapshot/sequence book + executed-trade flow → regime/checklist.
Hyperliquid và Telegram là tích hợp tùy chọn.

**Chỉ chạy một process/worker và một instance cho tài khoản.** Không chạy cùng
Demo account từ máy local và Render đồng thời. Lock hiện tại chỉ trong process,
không bảo vệ nhiều instance. Dùng tài khoản DEMO chuyên dụng, không thêm lệnh tay
hoặc bot khác trong khi FlowPilot quản lý vị thế.

## 2. Chuẩn bị

- Python 3.11+ (đã test Python 3.12.14 trên Linux).
- Node 22+ và npm (đã build trên Node 24.19.0).
- Kết nối internet tới Binance Demo; có thể bị giới hạn theo khu vực/mạng.
- Binance Demo key/secret, KHÔNG dùng API key của tài khoản thật cho Demo.
- Docker Desktop nếu chọn PostgreSQL local. Không bắt buộc cho quick start SQLite.

Giải nén ZIP, mở terminal trong thư mục `btc-flowpilot`.

## 3. Chạy backend local — Windows PowerShell

```
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python bootstrap.py
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

Nếu PowerShell chặn Activate, dùng CMD và `.venv\Scripts\activate.bat`, hoặc
chạy trực tiếp `.venv\Scripts\python.exe -m uvicorn ...`. Không cần đổi policy
hệ thống. Nếu không có Python 3.12, chọn bản 3.11+ đã cài. Cross-platform chưa
được thử trên Windows/macOS.

## 4. Chạy backend local — macOS / Linux

```
cd backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python bootstrap.py
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

`bootstrap.py` hỏi password quản trị tối thiểu 12 ký tự và database URL. Enter
để dùng SQLite. Script tạo Fernet encryption key + session signing key và ghi
`.env` mà không in secrets. Không ghi đè `.env` có sẵn. API keys vẫn chưa cài.

Hoặc copy `.env.example` thành `.env` rồi điền thủ công. Để tạo encryption key:
```
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```
Để tạo SESSION_KEY:
```
python -c "import secrets; print(secrets.token_urlsafe(48))"
```
Lưu ENCRYPTION_KEY an toàn: mất key sẽ không đọc được credentials đã mã hóa.
Không gửi `.env`, key hoặc API secret qua chat hay commit vào Git.

## 5. Chạy frontend (terminal thứ hai)

```
cd frontend
npm ci
npm run dev
```
Mở http://localhost:5173. Nhập password đã tạo. Vite proxy `/api` về
http://127.0.0.1:8000; không cần sửa URL mặc định.

Để chạy cùng origin bằng backend:
```
cd frontend
npm run build
```
Sau đó restart backend và mở http://127.0.0.1:8000. FastAPI tự serve
`frontend/dist` nếu có. Không cần Vite trong cách này.

## 6. PostgreSQL local (tùy chọn, cần cho hosting)

1. Cài Docker Desktop và khởi động.
2. Copy `deploy/.env.example` thành `deploy/.env`.
3. Điền POSTGRES_PASSWORD bằng mật khẩu riêng (không để trống).
4. Trong thư mục deploy:
```
docker compose up -d
```
5. Trong `backend/.env`, đặt:
```
DATABASE_URL=postgresql+psycopg://flowpilot:YOUR_URL_ENCODED_PASSWORD@localhost:5432/flowpilot
```
`YOUR_URL_ENCODED_PASSWORD` là chỗ thay thế; cần URL-encode ký tự đặc biệt trong
password. Restart backend. SQLAlchemy tự tạo bảng records. Chưa có Alembic
migrations hoặc kiểm thử PostgreSQL server thực trong bản bàn giao.

Dừng container bằng `docker compose stop`. Không dùng `down -v` nếu muốn giữ dữ
liệu. Backup database và encryption key riêng trước thay đổi schema/deploy.

## 7. Environment variables

| Biến | Ý nghĩa |
|---|---|
| DATABASE_URL | SQLite local hoặc PostgreSQL `postgresql+psycopg://...` |
| ADMIN_PASSWORD | Password quản trị, ít nhất 12 ký tự |
| ENCRYPTION_KEY | Fernet key, cố định giữa các lần restart |
| SESSION_KEY | Chuỗi ngẫu nhiên ít nhất 32 ký tự |
| CORS_ORIGINS | Origin chính xác, phân cách dấu phẩy, không wildcard |
| COOKIE_SECURE | false local HTTP; true khi HTTPS |
| ALLOW_LOCAL_HTTP | true chỉ cho loopback local; false hosting |
| ENABLE_MARKET_FEED | true để thu DEMO feed; false cho test offline |
| TELEGRAM_TOKEN / TELEGRAM_CHAT_ID | Tùy chọn; để trống thì không gửi alert |
| frontend VITE_API_URL | Để trống cho local proxy / same-origin; HTTPS backend nếu split |

Tất cả key/secret trong template để trống. API key nhập qua dashboard Settings,
backend mã hóa và không cung cấp endpoint lấy lại plaintext. HTTP chỉ được phép
cho loopback development; hosting bắt buộc HTTPS. Browser không dùng localStorage
cho credentials/session. Cookie hết hạn sau 1 giờ.

## 8. Tạo / nhập DEMO key

1. Đăng nhập Binance Demo và xác minh đang ở môi trường DEMO.
2. Tạo API key trong Demo API Management theo giao diện Binance hiện tại:
   https://demo.binance.com/en/my/settings/api-management
3. Trong Binance Demo, đặt one-way mode, single-asset mode, isolated margin và
   2x leverage cho BTCUSDT/ETHUSDT. Bot **không tự sửa account mode**.
4. Không có vị thế/lệnh đang mở trên tài khoản trước test entry.
5. Trên FlowPilot chọn DEMO → Settings → API key / API secret → Save credentials.
6. Nhấn Test connection. Balance này là số dư sàn, khác risk budget 175 USDT.
7. Kiểm tra tab Order Flow đã synced/fresh. Lỗi mạng sẽ chặn entry.

Chọn REAL chỉ để đọc số dư/vị thế qua API GET. Mọi mutation REAL bị chặn trong
Binance client, không có setting hay environment variable mở khóa REAL.

## 9. News calendar bắt buộc

Settings nhận JSON calendar có UTC offset. Bạn phải rà lịch CPI/FOMC/NFP và sự
kiện liên quan trước khi xác nhận calendar hợp lệ. Ví dụ cấu trúc:
```
{
  "valid_until": "2026-10-12T00:00:00+00:00",
  "events": [
    {"name": "REPLACE_WITH_VERIFIED_EVENT", "time": "2026-10-11T14:00:00+00:00"}
  ]
}
```
Đây là ví dụ cấu trúc, KHÔNG phải lịch sự kiện thật. Thay toàn bộ ngày/sự kiện
bằng lịch đã kiểm tra. `events: []` chỉ dùng khi bạn đã rà soát và xác nhận không
có sự kiện trong khoảng hiệu lực. Thiếu/expired calendar chặn mọi entry. Blackout
60 phút trước và sau sự kiện. Lưu calendar sẽ STOP bot; RESUME là thủ công.

## 10. Test một lệnh DEMO có giám sát

1. Test connection và kiểm tra tài khoản trên Binance Demo.
2. Nhập/kiểm tra news calendar. Chờ public feed đồng bộ và đủ 300 candles.
3. RESUME trong Overview. Đây là mở test thủ công, không bật auto strategy.
4. Nhập symbol, LONG/SHORT, ideal entry, SL, TP và tolerance.
5. SL/TP phải đúng tick size. Chọn stop theo cấu trúc bạn phân tích, không ép
   stop sát để vượt minimum notional. Tài khoản 175 USDT có thể không đủ BTC min
   notional khi stop xa; bị từ chối là hành vi bảo vệ mong muốn.
6. Preview risk & checks: account mode, isolated/2x, margin, news/crash guards,
   freshness, entry cap, loss limits, exchange filters, adaptive tolerance,
   fees/slippage/funding reserve và net R:R >=2.
7. Submit one DEMO test order → xác nhận rõ ràng. Backend kiểm tra lại khi submit.
8. Theo dõi state journal. Chỉ `PROTECTED` sau xác minh SL và TP mới được hiểu là
   đã có lệnh bảo vệ đang active tại thời điểm query.
9. Mở Binance Demo kiểm tra **cả position và conditional SL/TP**: đúng symbol,
   side, trigger price, closePosition, mark-price trigger.
10. Nếu `ENTRY_UNKNOWN`, `PARTIAL_OR_PENDING`, `UNPROTECTED_OR_UNKNOWN` hoặc lỗi:
    bot STOP. Kiểm tra trực tiếp tại sàn ngay. Dùng FLATTEN DEMO nếu thích hợp.
    Bản này không tự động sửa/đóng vị thế khi SL lỗi.

Không click đổi form rồi submit lại để “retry” lệnh timeout. Request ID được giữ
cho cùng form để idempotency. Không xóa journal/database để bỏ qua unresolved
orders. Entry market có thể trượt quá giới hạn; hậu kiểm dừng entry mới nhưng
không đảm bảo giới hạn lỗ tuyệt đối.

## 11. STOP / RESUME / FLATTEN

- **STOP BOT**: ngừng entry mới, giữ protective orders, ghi DB/audit, alert nếu
  cấu hình. Không đồng nghĩa đã đóng vị thế.
- **RESUME**: thủ công, DEMO only, kiểm tra reconciliation, feed/news và unresolved
  orders. Không tự resume sau restart. Không bật auto trading.
- **FLATTEN DEMO**: xác nhận riêng, đóng symbol thuộc journal bằng reduce-only,
  hủy managed pending entry, xác minh vị thế flat rồi xử lý SL/TP. Nếu không xác
  minh được, giữ STOP và báo lỗi. Không hủy protection trước khi verify flat.
- **Reconcile managed orders**: query entry, positions và conditional protection.
  Supervisor cũng chạy mỗi 15 giây, kể cả khi STOP, miễn service đang hoạt động.

Không dùng tài khoản chung với bot khác/manual trading. `closePosition` đóng
cả vị thế của symbol trong one-way mode. Nếu có hoạt động bên ngoài trên symbol
được quản lý, quyền sở hữu không thể suy ra chắc chắn từ Binance position net.

## 11A. AUTO DEMO (forward test, chưa kiểm chứng)

Chỉ DEMO. Nút **▶ Start AUTO** (sau RESUME) cho bot tự đặt lệnh DEMO theo hai chiến
thuật trong `backend/app/strategies/auto.py`: A_CHECKLIST (đủ 7 dòng checklist) và
B_RETEST (breakout 15m theo trend BTC + retest + delta 5m), TP 2.5R. Mỗi setup chạy
preview khô trước, rồi qua `engine.submit()` như lệnh tay: mọi risk check, guard,
xác minh SL/TP và STOP khi không chắc chắn đều giữ nguyên. STOP hoặc restart tắt
AUTO; không tự bật lại. Hai lệnh thua liên tiếp chặn entry và tắt AUTO; sau khi xem
lại, dùng Risk Controls → "I reviewed the losses — clear streak". Chưa có kết quả
hiệu suất nào; kết quả phải đến từ forward test thực tế trên Demo.

## 11B. Whale Confirmation Engine (Hyperliquid)

Tab **Whale Monitor**. Nhập tối đa 30 ví (mỗi dòng: `address,label,cluster,quality`).
Ví cùng `cluster` được tính là MỘT ví độc lập. 10 ví đầu stream qua WebSocket
`userFills` (giới hạn Hyperliquid 10 user/IP), số còn lại poll REST
`userFillsByTime`; mọi ví poll `clearinghouseState` mỗi `poll_seconds` để reconcile.

- Snapshot đầu tiên của mỗi ví là **baseline**, không phải giao dịch mới.
- Hành động OPEN/ADD/REDUCE/CLOSE LONG/SHORT suy ra từ `startPosition` + khối lượng
  fill có dấu (B = mua, A = bán), không từ thay đổi USD notional. FLIP tách thành
  CLOSE hướng cũ + OPEN hướng mới. Partial fill / TWAP / chuỗi fill cùng hướng trong
  `merge_window_s` gộp thành một hành động. Fill dedupe theo trade id.
- Nếu kích thước vị thế thay đổi mà không thấy fill, bot backfill REST; vẫn lệch thì
  ghi hành động `reconciled` theo chênh lệch KHỐI LƯỢNG.
- Bias mỗi coin: long/short support tách riêng; REDUCE LONG chỉ giảm hỗ trợ Long,
  đóng Short không phải mở Long; hành động mới nặng hơn vị thế cũ và giảm dần theo
  `half_life_min`; một cluster bị giới hạn `max_wallet_share`; cần `min_independent`
  ví độc lập. Trạng thái: bullish / bearish / neutral / conflicting / unavailable.
- Cohort Long/Short chỉ là **monitored wallets**, không phải toàn thị trường. Mẫu số
  0 → N/A. Funding/OI Hyperliquid chỉ là context.
- Tích hợp chiến lược: whale chỉ xếp hạng setup ĐÃ đạt trend/cấu trúc/order flow/Risk
  Engine. Không tự entry, đảo chiều, đóng lệnh, tăng risk hay nới SL. Bật
  "Require whale confirmation" thì mọi entry (tay và AUTO) bị chặn trừ khi whale
  SUPPORTS — kể cả khi dữ liệu unavailable. Đổi chế độ này sẽ STOP bot.
- Coin discovery: tối đa 5 coin ngoài watchlist khi ≥ `discovery_min_wallets` ví độc
  lập mới mở/tăng cùng hướng trong 1h; kiểm tra mapping Binance USDT-M (kể cả
  `kPEPE → 1000PEPEUSDT`), khớp giá, thanh khoản 24h, spread, funding và lịch sử nến.
  Chỉ thêm vào **research watchlist**; giao dịch coin mới cần bạn duyệt và sửa
  `SYMBOLS` trong `backend/app/config.py`.

Mọi ngưỡng/weights là **giả thuyết cần validation**; điểm số không phải xác suất thắng.
Ví có thể hedge ở sàn khác.

## 12. Render Free DEMO

Khuyến nghị cho người mới: **một Web Service serve cả React build và API cùng
origin**, đã có `render.yaml`. Cách này tránh third-party cookie bị browser chặn.

1. Tạo Git repo riêng, upload source đã giải nén, KHÔNG upload `.env`, recordings,
   database, `.venv` hoặc node_modules.
2. Tạo persistent PostgreSQL bên ngoài. Lấy connection URL với SSL phù hợp nhà
   cung cấp (`?sslmode=require` nếu cần). Đổi prefix thành `postgresql+psycopg://`.
   Bot truy cập database liên tục 24/7, nên database không bao giờ "ngủ": gói free
   tính theo compute-hours (ví dụ Neon ~100 CU-giờ/tháng) sẽ hết giữa tháng. Supabase
   free (500 MB, chỉ pause khi 7 ngày không hoạt động) phù hợp hơn; chọn region
   Frankfurt và dùng chuỗi **Session pooler** (IPv4). Kiểm tra lại giới hạn gói free
   trên trang chính thức trước khi dùng.
3. Trong Render tạo Blueprint từ repo. Chọn service `btc-flowpilot-demo`.
4. Điền DATABASE_URL, ADMIN_PASSWORD, ENCRYPTION_KEY, SESSION_KEY. Giữ encryption
   key cố định. Telegram tùy chọn để trống.
5. CORS_ORIGINS đặt đúng URL HTTPS service, ví dụ `https://YOUR_SERVICE.onrender.com`.
6. Build cài Python dependencies + `npm ci` + frontend build, start Uvicorn một worker.
7. Khi service có URL, mở `/health`, sau đó `/` dashboard. Login và nhập DEMO keys.
8. Sau mỗi redeploy/restart: STOP mặc định → reconcile → feed resync → kiểm tra sàn
   trước RESUME. Không auto resume.

Blueprint được parse/check cục bộ; **chưa deploy Render thực**. Region/plan/build
availability cần kiểm tra ở Render UI. Proxy headers chỉ được trust `*` trong
môi trường Render sau trusted ingress; khi VPS phải giới hạn trusted proxy IP.
Không expose Uvicorn trực tiếp qua HTTP với ALLOW_LOCAL_HTTP=true.

React cũng có thể deploy Static Site theo `deploy/render-static-example.yaml`.
Set VITE_API_URL trước build; thêm chính xác frontend HTTPS origin vào backend
CORS_ORIGINS. Cross-site cookies có thể bị browser chặn: dùng custom domains
cùng site hoặc combined same-origin deployment. Không bỏ auth/CSRF để “sửa CORS”.

Render Free có thể sleep, mất local disk và không bảo đảm WebSocket/24x7; traffic
đi ra quá nhiều có thể bị suspend. UptimeRobot không bảo đảm uptime. Database phải
persistent bên ngoài, recordings không lưu vào ephemeral Render disk nếu cần giữ.
SL/TP đã xác minh ở Binance có thể còn hoạt động khi bot ngủ nhưng bot không còn
supervise, không repair và có thể bỏ lỡ signal. Không dùng Render Free cho REAL.
Khi cần luôn hoạt động: chuyển sang always-on single worker/VPS với PostgreSQL,
TLS reverse proxy, backup/monitoring và fault tests trước.

## 13. Research / backtest

Từ backend với venv active:
```
python -m research.record BTCUSDT recordings/btc.jsonl
python -m research.replay recordings/btc.jsonl
python -m research.backtest YOUR_CLOSED_CANDLES.csv --output report.json
```
Recorder dừng bằng Ctrl+C. JSONL có snapshot, depth và executed aggTrades. Replay
kiểm tra sequence và CVD, không phải trade strategy simulator. Freshness dùng
wall clock live; chưa có replay-aware signal clock. CSV baseline cần tối thiểu
900 rows, columns `time,open,high,low,close,volume`, dữ liệu theo thứ tự tăng dần,
closed candles thật. Baseline EMA khác chiến thuật đầy đủ, không dùng DOM; báo
cáo nhãn rõ `CANDLE_BASELINE_ONLY_NOT_FLOWPILOT`. Có costs, gap-aware stop,
chronological OOS, fixed walk-forward folds, bootstrap interval; chưa có full
strategy ablation/historical funding. Dashboard không trình bày baseline như
performance của bot. Không có historical dataset được đóng gói.

## 14. Kiểm thử

```
cd backend
python -m compileall -q app research tests
python -m pytest -q
```
```
cd frontend
npm run typecheck
npm run build
```
Đọc `TEST_REPORT.md` để biết kết quả đã chạy và phần chưa kiểm chứng. Tests dùng
fixture/mocks; không cần hoặc chứa key thật. Không đặt lệnh thật trong test suite.

## 15. Troubleshooting

| Triệu chứng | Cách kiểm tra |
|---|---|
| Login 503 | ADMIN_PASSWORD >=12; SESSION_KEY >=32; chạy đúng cwd backend |
| Login 401 | Password đúng; cookie hết hạn thì login lại |
| 403 HTTP / CSRF | HTTPS hosting; X-Flowpilot-Request; exact CORS origin |
| Cookie không giữ | Dùng combined same-origin; HTTPS COOKIE_SECURE=true |
| Database URL error | URL hợp lệ, psycopg installed, SSL/network DB đúng |
| Fernet error | Encryption key đúng và giữ nguyên; không đổi key tùy tiện |
| Feed stale | Demo domain, firewall/region, WebSocket routing, mất sequence |
| NO TRADE / RESUME block | News calendar, feed, unmanaged position, unresolved journal |
| Lot/min notional block | Vốn/risk quá nhỏ cho stop; không tăng leverage/risk để ép lệnh |
| Account mode block | Đặt one-way + single-asset + isolated 2x thủ công trên Binance Demo |
| Algo order fail | Recheck official API; kiểm tra vị thế tại sàn ngay, STOP/FLATTEN |
| Cleanup required | Query conditional orders tại sàn; không reset DB để bỏ qua |
| Render restart | STOP mặc định; persistent DB; reconcile rồi kiểm tra trước resume |

API adapter không log upstream URLs/signatures/secrets; response lỗi đã bỏ chi
tiết nhạy cảm. Journal/audit chứa trade data. Cân nhắc bảo mật bản backup.

## 16. Chưa sẵn sàng production

Xem feature matrix và roadmap trong CLAUDE.md. Cần full strategy lifecycle,
user-data stream, robust paginated ledger, explicit virtual equity accounting,
partial-fill automation, emergency repair/escalation, PostgreSQL migrations,
external vault/rotation, distributed fencing, replay-aware clocks và full
quant validation. Chạy ít nhất 100 DEMO trades hợp lệ có giám sát và fault tests
là mốc thử nghiệm đề xuất; không đảm bảo lợi nhuận hoặc đủ điều kiện giao dịch
thật. REAL vẫn khóa trong code của bản bàn giao này.
