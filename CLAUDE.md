# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Backend for a Lotofácil lottery pool platform ("Bolão Lotofácil"). Users can browse pools, purchase quotas/shares, manage wallets, and pay via Pix (Mercado Pago integration). Admins can create/edit pools, add lottery games (15 numbers from 1-25), and run result appraisals (manual or automatic via Lotofácil API).

Built with Python/FastAPI, using Supabase (PostgreSQL) as the database via a custom HTTP client. The codebase and comments are written in Brazilian Portuguese.

## Commands

### Run development server
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Install dependencies
```bash
pip install -r requirements.txt
```

### API docs (when server is running)
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

### No tests
There is no test suite yet. `tests/test_api.py` exists but is empty.

## Architecture

### Layered structure

```
Routes (app/api/) → Services (app/services/) → Supabase HTTP Client (app/core/supabase.py) → Database
Schemas (app/schemas/) provide Pydantic validation at the route layer.
```

- `app/main.py` — FastAPI app, CORS, rate limiter, Sentry, router registration, health check (`GET /`). `redirect_slashes=False`.
- `app/config.py` — Pydantic Settings loaded from `.env`. Properties: `cors_origins_list`, `admin_emails_list`. Has `model_validator` that enforces `MERCADOPAGO_WEBHOOK_SECRET` in production.
- `app/api/deps.py` — Auth dependency injection (JWT verification + admin check)
- `app/api/v1/admin/` — Admin-only routes (pool CRUD, games, apuração, stats)
- `app/core/security.py` — JWT creation (`create_access_token`) and verification (`verify_token`) using HS256 + SECRET_KEY
- `app/core/limiter.py` — slowapi rate limiter (key: remote IP)

### Data access pattern

There is **no ORM**. `app/core/supabase.py` implements a custom HTTP client (`SupabaseHTTPClient`) that talks to the Supabase REST API using `httpx`. It provides a chainable query builder mirroring the Supabase JS client:

```python
supabase.table("boloes").select("*").eq("status", "aberto").execute()
supabase.table("boloes").select("id, nome").in_("id", list_of_ids).execute()
```

Key classes:
- `SupabaseHTTPClient` — holds a persistent `httpx.Client` for connection pooling. Methods: `.table(name)`, `.rpc(fn, params)`
- `TableQuery` — chainable builder with `.select()`, `.eq()`, `.in_()`, `.limit()`, `.order()`, `.insert()`, `.update()`, `.delete()`, `.execute()`
- `RPCQuery` — calls Supabase PostgreSQL functions via REST
- `QueryResponse` — response wrapper with `.data` (list/dict or None) and `.error` (str or None). **Always check `.error` before using `.data`.**

Two global client instances (imported from `app.core.supabase`):
- `supabase` — uses the anon key (public/user-level access)
- `supabase_admin` — uses the service role key (bypasses RLS)

All admin and service-layer code uses `supabase_admin` to bypass Row Level Security. Complex atomic operations use Supabase RPC functions.

### Authentication and authorization

**JWT HS256** — fully implemented. The `Authorization: Bearer {token}` header carries a signed JWT (not a raw UUID).

- `app/core/security.py`:
  - `create_access_token(user_id, email, is_admin)` — generates JWT with 12h expiration
  - `verify_token(token)` — decodes and validates signature + expiration; raises `ValueError` on failure
- `app/api/deps.py`:
  - `get_current_user_id()` — required, raises 401 if token missing/invalid
  - `get_current_user_optional()` — returns None if unauthenticated
  - `get_current_user()` — returns `{"id": user_id}` dict
  - `get_admin_user()` — verifies `is_admin` claim in JWT payload; raises 403 if not admin

Admin routes use `dependencies=[Depends(get_admin_user)]`. The `is_admin` flag is embedded in the JWT at login time based on `ADMIN_EMAILS` env var — no database call needed per request.

### Auth flow (email confirmation + password recovery)

Registration uses `POST /auth/v1/signup` (Supabase anon key) with `redirect_to={FRONTEND_URL}/confirmar-email`. Email duplicate detection: Supabase returns HTTP 400, or HTTP 200 with `identities == []`.

Login returns 403 with `detail="EMAIL_NOT_CONFIRMED"` if the user hasn't confirmed email yet. On success, returns a signed JWT and `is_admin` flag.

Password recovery:
- `POST /api/v1/auth/forgot-password` — calls `/auth/v1/recover` with `redirect_to={FRONTEND_URL}/redefinir-senha`. Always returns 200 (doesn't reveal if email exists). Rate limited: 3/min.
- `POST /api/v1/auth/reset-password` — calls `PUT /auth/v1/user` with `Authorization: Bearer {access_token}` from the recovery email link.

Supabase Dashboard must have "Enable email confirmations" ON and Redirect URLs:
- `https://www.boloeslotofacil.com/**`
- `https://boloeslotofacil.com/**`
- `http://localhost:3000/**`
- `http://localhost:5173/**`

### Rate limiting

`slowapi` with `get_remote_address` as key function. Registered in `app/main.py`.

| Endpoint | Limit |
|----------|-------|
| `POST /auth/login` | 10/min |
| `POST /auth/forgot-password` | 3/min |
| `POST /pagamentos/webhook/mercadopago` | 60/min |

### API route prefixes

All routes are under `/api/v1/`:
- `/api/v1/auth` — registration, login, forgot-password, reset-password
- `/api/v1/boloes` — public pool browsing and game listing
- `/api/v1/cotas` — quota management and purchase
- `/api/v1/carteira` — wallet balance
- `/api/v1/pagamentos` — Pix payment creation and webhooks
- `/api/v1/transacoes` — transaction history (requires auth; user sees only own records)
- `/api/v1/perfil` — user profile (nome, telefone, chave_pix). Auto-creates profile+carteira if missing.
- `/api/v1/admin/boloes` — admin pool CRUD, game management, apuração
- `/api/v1/admin/stats` — dashboard statistics and activity feed
- `/api/v1/cron` — cron endpoints (fechar-boloes, apurar-resultados). Protected by `X-Cron-Secret` header only.

### Key features

**Game management (jogos):** Admins add lottery games (exactly 15 numbers from 1-25) via `POST /admin/boloes/{id}/jogos`. Numbers are validated and stored sorted.

**Result appraisal (apuração):** Two modes:
- **Automatic:** `POST /admin/boloes/{id}/apurar/automatico` — fetches drawn numbers from the Lotofácil API and calculates hits per game
- **Manual:** `POST /admin/boloes/{id}/apurar` — admin provides the 15 drawn numbers

Both update each game's `acertos` (hit count) and set the pool status to `apurado`.

**Lotofácil API — dual source with fallback** (`app/services/resultado_service.py`):
- Primary: `https://servicebus2.caixa.gov.br/portaldeloterias/api/lotofacil/{concurso}` (field `listaDezenas` / `listaRateioPremio`)
- Fallback: `https://loteriascaixa-api.herokuapp.com/api/lotofacil/{concurso}` (field `dezenas` / `premiacoes`)
- Timeout: 30s. Prize mapping: `acertos = 16 - faixa` (faixa 1 = 15 hits, faixa 5 = 11 hits).

**Cron jobs** (`app/api/cron.py`): Protected by `SECRET_KEY` via **header only** (`X-Cron-Secret`). Query param support was removed (would expose secret in logs). Scheduled on cron-job.org:
- `POST /cron/fechar-boloes` — closes all `aberto` pools (run at 20:55)
- `POST /cron/apurar-resultados` — appraises all pending pools (run `*/15 21,22 * * *`)

**Payment flow:** Pix payments go through Mercado Pago (`app/services/pagamento_service.py`).
- If `MERCADOPAGO_ACCESS_TOKEN` is not set **or** `MERCADOPAGO_ENV=sandbox` **or** `ENVIRONMENT=development` → uses simulated fake QR codes (development mode)
- Otherwise → calls real Mercado Pago API
- Webhook at `/api/v1/pagamentos/webhook/mercadopago` verifies HMAC-SHA256 signature (`x-signature` header), checks idempotency, verifies paid amount via MP API, and credits wallet via atomic RPC.

**Note:** Pix real money is currently NOT active. `MERCADOPAGO_ACCESS_TOKEN` is not configured on Render — all payments generate fake QR codes. To activate: set `MERCADOPAGO_ACCESS_TOKEN` (production token) and `MERCADOPAGO_ENV=production` on Render and configure webhook in MP dashboard.

**Also note:** The payer email in `_criar_pix_mercadopago` is currently hardcoded as `test_user@test.com` — must be fixed before activating real Pix.

### Supabase tables

| Table | Key columns |
|-------|-------------|
| `boloes` | id, nome, concurso_numero, concurso_fim, total_cotas, cotas_disponiveis, valor_cota, status |
| `jogos_bolao` | id, bolao_id, dezenas (int[]), acertos |
| `resultados_concurso` | id, bolao_id, concurso_numero, dezenas_sorteadas (int[]) |
| `acertos_concurso` | id, jogo_id, concurso_numero, acertos |
| `premiacoes_bolao` | id, bolao_id, concurso_numero, acertos, valor_premio |
| `cotas` | id, bolao_id, usuario_id, valor_pago |
| `carteira` | id, usuario_id, saldo_disponivel, saldo_bloqueado |
| `transacoes` | id, usuario_id, tipo, valor, origem, saldo_anterior, saldo_posterior |
| `pagamentos_pix` | id, usuario_id, valor, status, qr_code, external_id |
| `usuarios` | id, nome, telefone, chave_pix |

Pool statuses: `aberto`, `fechado`, `apurado`, `cancelado`

**Important:** The column `resultado_dezenas` does NOT exist in `boloes`. All drawn numbers are stored in `resultados_concurso`.

### Database constraints (Supabase)

Applied via SQL migrations (already in production):

**Indexes:**
- `idx_cotas_usuario_id`, `idx_cotas_bolao_id`
- `idx_jogos_bolao_bolao_id`
- `idx_resultados_concurso_bolao` (bolao_id, concurso_numero)
- `idx_acertos_concurso_bolao` (bolao_id, concurso_numero)
- `idx_pagamentos_external_id`
- `idx_transacoes_usuario_id`

**Unique constraint:** `uq_resultado_bolao_concurso` on `resultados_concurso(bolao_id, concurso_numero)` — prevents duplicate appraisals.

**Check constraints:**
- `chk_saldo_nao_negativo`: `carteira.saldo_disponivel >= 0`
- `chk_cotas_nao_negativas`: `boloes.cotas_disponiveis >= 0`
- `chk_valor_cota_positivo`: `boloes.valor_cota > 0`
- `chk_dezenas_length`: `array_length(jogos_bolao.dezenas, 1) = 15`

**Foreign keys:** `cotas→boloes`, `cotas→usuarios`, `jogos_bolao→boloes`, `acertos_concurso→jogos_bolao`, `resultados_concurso→boloes`, `pagamentos_pix→usuarios`

**Trigger:** `trg_transacoes_immutable` — `BEFORE UPDATE OR DELETE` on `transacoes` raises exception. Transactions are append-only (audit log).

### RPC functions

- `comprar_cota(p_usuario_id, p_bolao_id, p_quantidade)` — atomic quota purchase (debit wallet, create cota, update pool availability)
- `creditar_carteira(p_usuario_id, p_valor, p_origem, p_referencia_id, p_descricao)` — atomic credit (UPDATE carteira + INSERT transacao in one SQL transaction). Used for Pix deposits and prize distribution.
- `buscar_minhas_cotas(p_usuario_id)` — get user's quotas (SECURITY DEFINER to bypass RLS)

**All financial operations use RPCs — never raw SELECT+calculate+UPDATE.**

### Monitoring

Sentry is integrated in `app/main.py` (FastAPI + httpx integrations). Activated when `SENTRY_DSN` env var is set. `traces_sample_rate=0.1`, `send_default_pii=False`.

## Environment Setup (Local)

Copy `.env.example` to `.env` and fill in values. Required variables:
- `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`
- `SECRET_KEY` (long random string — used for JWT signing AND cron authentication)
- `FRONTEND_URL` (default: `http://localhost:3000`) — used in email confirmation and password recovery links

Optional: `MERCADOPAGO_ACCESS_TOKEN`, `MERCADOPAGO_ENV`, `WEBHOOK_URL`, `CORS_ORIGINS`, `LOG_LEVEL`, `ADMIN_EMAILS`, `SENTRY_DSN`

**Note:** `MERCADOPAGO_WEBHOOK_SECRET` is **required** when `ENVIRONMENT=production`. The `model_validator` in `app/config.py` raises a startup error if it's missing in production.

Frontend dev server runs on port 3000 and proxies `/api` to this backend on port 8000.

## Deployment

**Production**: Render — `https://bolao-lotofacil-api.onrender.com`. Free tier sleeps after 15 min inactivity (~30s cold start).

`GET /` health check returns `{"status": "ok"}`. Config: `Procfile`.

### Render environment variables (production)

| Variable | Status | Notes |
|----------|--------|-------|
| `SUPABASE_URL` | ✅ set | |
| `SUPABASE_ANON_KEY` | ✅ set | |
| `SUPABASE_SERVICE_ROLE_KEY` | ✅ set | |
| `SECRET_KEY` | ✅ set | Used for JWT + cron auth |
| `ENVIRONMENT` | ✅ `production` | |
| `CORS_ORIGINS` | ✅ set | `https://boloeslotofacil.com,https://www.boloeslotofacil.com` |
| `ADMIN_EMAILS` | ✅ set | Comma-separated, no hardcoded default in code |
| `FRONTEND_URL` | ✅ set | `https://www.boloeslotofacil.com` |
| `MERCADOPAGO_WEBHOOK_SECRET` | ✅ set | Placeholder — swap for real MP secret when Pix is activated |
| `SENTRY_DSN` | ✅ set | Backend DSN from Sentry FastAPI project |
| `MERCADOPAGO_ACCESS_TOKEN` | ❌ not set | Required to activate real Pix payments |
| `MERCADOPAGO_ENV` | ❌ not set | Set to `production` when activating real Pix |

### Frontend (Vercel)

| Variable | Status | Notes |
|----------|--------|-------|
| `VITE_API_URL` | ✅ set | Points to Render backend |
| `VITE_SENTRY_DSN` | ✅ set | Frontend DSN from Sentry React project |
