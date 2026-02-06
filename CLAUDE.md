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

- `app/main.py` — FastAPI app, CORS, router registration, health check (`GET /`). `redirect_slashes=False`.
- `app/config.py` — Pydantic Settings loaded from `.env`. Properties: `cors_origins_list`, `admin_emails_list` parse comma-separated env vars.
- `app/api/deps.py` — Auth dependency injection (user auth + admin check)
- `app/api/v1/admin/` — Admin-only routes (pool CRUD, games, apuração, stats)
- `app/core/security.py` — Placeholder (JWT validation not yet implemented)

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

All admin and service-layer code uses `supabase_admin` to bypass Row Level Security. Complex atomic operations use Supabase RPC functions (e.g., `comprar_cota` for quota purchases).

### Authentication and authorization

Currently in **test/development mode**: the `Authorization: Bearer {user_id}` header passes the Supabase user UUID directly (no JWT validation). Auth dependencies in `app/api/deps.py`:
- `get_current_user_id()` — required, raises 401 if missing
- `get_current_user_optional()` — returns None if unauthenticated
- `get_current_user()` — returns `{"id": user_id}` dict
- `get_admin_user()` — verifies user email is in `ADMIN_EMAILS` whitelist by calling the Supabase Auth Admin API, raises 403 if not authorized

Admin routes use `dependencies=[Depends(get_admin_user)]` to protect them. The `ADMIN_EMAILS` env var is a comma-separated list of authorized emails (configured in `app/config.py` with defaults).

Registration and login endpoints in `app/api/auth.py` use the Supabase Auth API directly via httpx. The login response includes an `is_admin` flag.

### API route prefixes

All routes are under `/api/v1/`:
- `/api/v1/auth` — registration and login
- `/api/v1/boloes` — public pool browsing and game listing
- `/api/v1/cotas` — quota management and purchase
- `/api/v1/carteira` — wallet balance
- `/api/v1/pagamentos` — Pix payment creation and webhooks
- `/api/v1/transacoes` — transaction history
- `/api/v1/admin/boloes` — admin pool CRUD, game management, apuração
- `/api/v1/admin/stats` — dashboard statistics and activity feed

### Key features

**Game management (jogos):** Admins add lottery games (exactly 15 numbers from 1-25) to pools via `POST /admin/boloes/{id}/jogos`. Numbers are validated and stored sorted.

**Result appraisal (apuração):** Two modes:
- **Automatic:** `POST /admin/boloes/{id}/apurar/automatico` — fetches drawn numbers from `loteriascaixa-api.herokuapp.com/api/lotofacil/{concurso}` and calculates hits per game
- **Manual:** `POST /admin/boloes/{id}/apurar` — admin provides the 15 drawn numbers

Both update each game's `acertos` (hit count) and set the pool status to `apurado`.

**Payment flow:** Pix payments go through Mercado Pago (`app/services/pagamento_service.py`). In development mode (`ENVIRONMENT=development`), payments are simulated with fake QR codes. In production, real Mercado Pago API calls are made. The webhook endpoint is `/api/v1/pagamentos/webhook/mercadopago`.

### Supabase tables

| Table | Key columns |
|-------|-------------|
| `boloes` | id, nome, concurso_numero, total_cotas, cotas_disponiveis, valor_cota, status, resultado_dezenas |
| `jogos_bolao` | id, bolao_id, dezenas (int[]), acertos |
| `cotas` | id, bolao_id, usuario_id, valor_pago |
| `carteira` | id, usuario_id, saldo_disponivel, saldo_bloqueado |
| `transacoes` | id, usuario_id, tipo, valor, origem, saldo_anterior, saldo_posterior |
| `pagamentos_pix` | id, usuario_id, valor, status, qr_code, external_id |
| `usuarios` | id, nome, telefone |

Pool statuses: `aberto`, `fechado`, `apurado`, `cancelado`

### RPC functions

- `comprar_cota(p_usuario_id, p_bolao_id, p_quantidade)` — atomic quota purchase (debit wallet, create cota, update pool)
- `buscar_minhas_cotas(p_usuario_id)` — get user's quotas (SECURITY DEFINER to bypass RLS)

## Environment Setup (Local)

Copy `.env.example` to `.env` and fill in values. Required variables:
- `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`
- `SECRET_KEY`

Optional: `MERCADOPAGO_ACCESS_TOKEN`, `MERCADOPAGO_ENV`, `WEBHOOK_URL`, `CORS_ORIGINS`, `LOG_LEVEL`, `ADMIN_EMAILS`

Frontend dev server runs on port 3000 and proxies `/api` to this backend on port 8000.

## Deployment

**Production**: Render (free tier) — `https://bolao-lotofacil-api.onrender.com`. Free tier sleeps after 15 min inactivity (~30s cold start).

`GET /` health check returns `{"status": "ok"}`. Config: `Procfile` (Render/Heroku), `railway.toml` (unused — Railway trial was unreliable).

Production env vars: `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `SECRET_KEY`, `ENVIRONMENT=production`, `CORS_ORIGINS`, `LOG_LEVEL=INFO`.
