# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Backend for a Lotofacil lottery pool platform ("Bolao Lotofacil"). Users can browse pools, purchase quotas/shares, manage wallets, and pay via Pix (Mercado Pago integration). Built with Python/FastAPI, using Supabase (PostgreSQL) as the database via a custom HTTP client.

The codebase and comments are written in Brazilian Portuguese.

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

## Architecture

### Layered structure

```
app/
├── main.py              # FastAPI app, CORS, router registration
├── config.py            # Pydantic Settings loaded from .env
├── api/                 # Route handlers (controllers)
│   ├── deps.py          # Auth dependency injection
│   ├── boloes.py        # Public pool routes
│   ├── cotas.py         # Quota purchase routes
│   ├── carteira.py      # Wallet routes
│   ├── pagamentos.py    # Pix payment routes
│   ├── transacoes.py    # Transaction routes
│   └── v1/admin/        # Admin-only routes
├── services/            # Business logic layer
├── schemas/             # Pydantic request/response models
├── core/
│   ├── supabase.py      # Custom Supabase HTTP client
│   └── security.py      # (placeholder for JWT validation)
└── utils/               # Utility helpers
```

### Data access pattern

There is **no ORM**. `app/core/supabase.py` implements a custom HTTP client (`SupabaseHTTPClient`) that talks to the Supabase REST API using `httpx`. It provides a chainable query builder mirroring the Supabase JS client:

```python
supabase.table("boloes").select("*").eq("status", "aberto").execute()
```

Two global client instances are defined at module level in `core/supabase.py`:
- `supabase` — uses the anon key (public/user-level access)
- `supabase_admin` — uses the service role key (admin/privileged access)

Complex atomic operations use Supabase RPC functions (e.g., `comprar_cota` for quota purchases).

### Authentication

Currently in **test/development mode**: the `Authorization: Bearer {user_id}` header passes the Supabase user UUID directly. Auth dependencies are in `app/api/deps.py`:
- `get_current_user_id()` — required, raises 401 if missing
- `get_current_user_optional()` — returns None if unauthenticated
- `get_current_user()` — returns `{"id": user_id}` dict

JWT validation is not yet implemented (security.py is empty).

### API route prefixes

All routes are under `/api/v1/`:
- `/api/v1/boloes` — public pool browsing
- `/api/v1/cotas` — quota management and purchase
- `/api/v1/carteira` — wallet balance
- `/api/v1/pagamentos` — Pix payment creation and webhooks
- `/api/v1/transacoes` — transaction history
- `/api/v1/admin/boloes` — admin pool CRUD

### Payment flow

Pix payments go through Mercado Pago. `PagamentoService` creates charges and handles webhook callbacks. In development/sandbox mode, payments are simulated. The webhook endpoint is `/api/v1/pagamentos/webhook/mercadopago`.

### Supabase tables

`boloes`, `cotas`, `carteira`, `transacoes`, `pagamentos_pix`, `jogos_bolao`

## Environment Setup

Copy `.env.example` to `.env` and fill in values. Required variables:
- `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `DATABASE_URL`
- `SECRET_KEY`

Optional (payments): `MERCADOPAGO_ACCESS_TOKEN`, `MERCADOPAGO_ENV`, `WEBHOOK_URL`
