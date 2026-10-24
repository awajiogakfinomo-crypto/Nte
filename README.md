# Nte - Nigerian Location Intelligence Platform

A location intelligence platform powered by NIPOST Digital Postcode API, providing address validation, logistics management, KYC verification, and API key management for Nigerian addresses.

## Architecture

```
┌─────────────────────┐     ┌─────────────────────┐
│    Netlify (Free)   │     │    Render (Paid)    │
├─────────────────────┤     ├─────────────────────┤
│  Frontend (React)   │────▶│  FastAPI Backend    │
│  Static Export      │     │  PostgreSQL         │
│                     │     │  Redis              │
│                     │     │  Celery Workers     │
└─────────────────────┘     └─────────────────────┘
```

- **Frontend**: Reflex (Python → React) deployed to Netlify as static files
- **Backend**: FastAPI with Celery workers deployed to Render
- **Database**: Managed PostgreSQL on Render
- **Cache/Queue**: Managed Redis on Render
- **Background Jobs**: Celery workers + Celery Beat (via Render Cron)

## Tech Stack

- **Backend**: FastAPI, SQLAlchemy, Alembic, Celery, Redis
- **Frontend**: Reflex (compiles to React)
- **Database**: PostgreSQL 16
- **Cache/Queue**: Redis 7
- **API**: NIPOST Digital Postcode API
- **Auth**: JWT (HS256), Google OAuth (optional)
- **Monitoring**: Prometheus metrics, structured logging

## Features

- **Address Validation** - Validate Nigerian addresses against NIPOST postcodes
- **Logistics Management** - Delivery tracking, route optimization
- **KYC Verification** - Identity verification workflows
- **API Keys** - Rate-limited API access for integrations
- **Usage Analytics** - Request tracking, billing metrics
- **Notifications** - Email/SMS notifications via Celery

## Deployment

### Prerequisites
- GitHub account
- Render account
- Netlify account
- NIPOST API key

### Backend (Render)
1. Connect repository to Render
2. Use **Blueprint** deployment (reads `render.yaml`)
3. Provisioned services:
   - `nte-postgres` - PostgreSQL (free 90 days, then $7/mo)
   - `nte-redis` - Redis (free 25MB, then $7/mo)
   - `nte-api` - Web Service (free tier spins down, $7/mo always-on)
   - `nte-celery-worker` - Background Worker ($7/mo required)
   - `nte-celery-beat` - Cron Job (free 100 runs/day)
4. Set secret environment variables in Render dashboard:
   - `POSTCODE_API_KEY` - Your NIPOST API key
   - `SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD`, `EMAIL_FROM` - Email credentials

### Frontend (Netlify)
1. Connect repository to Netlify
2. Build settings (auto-detected from `netlify.toml`):
   ```
   Build command: cd frontend/nte_frontend && reflex export --frontend-only
   Publish directory: frontend/nte_frontend/.web/_static
   ```
3. Add environment variables:
   ```
   API_URL=https://nte-api.onrender.com
   FRONTEND_URL=https://nte.netlify.app
   ```

### CI/CD (GitHub Actions)
Auto-deploys on push to `main`:
1. Runs tests
2. Deploys backend to Render
3. Builds & deploys frontend to Netlify

Required GitHub secrets:
- `RENDER_API_KEY` - From Render Account Settings
- `NETLIFY_AUTH_TOKEN` - From Netlify User Settings
- `NETLIFY_SITE_ID` - From Netlify Site Settings

## Local Development

```bash
# Backend
cd backend
pip install -e ".[dev]"
cp .env.example .env  # Fill in values
alembic upgrade head
uvicorn app.main:app --reload

# Frontend (separate terminal)
cd frontend/nte_frontend
reflex init
reflex run
```

## Project Structure

```
nte/
├── .github/workflows/deploy.yml    # CI/CD pipeline
├── render.yaml                     # Render Blueprint
├── netlify.toml                    # Netlify config
├── pyproject.toml                  # Python dependencies
├── Dockerfile.backend              # Backend Docker image
├── backend/
│   ├── alembic/                    # Database migrations
│   └── app/                        # FastAPI application
│       ├── api/                    # API routes
│       ├── core/                   # Config, DB, security, Celery
│       ├── models/                 # SQLAlchemy models
│       ├── schemas/                # Pydantic schemas
│       ├── services/               # Business logic
│       └── tasks/                  # Celery tasks
└── frontend/
    └── nte_frontend/               # Reflex frontend (run `reflex init`)
```

## API Documentation

Once deployed:
- **API Docs**: `https://nte-api.onrender.com/docs` (Swagger UI)
- **ReDoc**: `https://nte-api.onrender.com/redoc`
- **Health**: `https://nte-api.onrender.com/health`
- **Metrics**: `https://nte-api.onrender.com/metrics` (Prometheus)

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `SECRET_KEY` | JWT signing key (auto-generated on Render) | Yes |
| `POSTCODE_API_KEY` | NIPOST API key | Yes |
| `DATABASE_URL` | PostgreSQL connection (auto-linked on Render) | Yes |
| `REDIS_URL` | Redis connection (auto-linked on Render) | Yes |
| `CORS_ORIGINS` | Allowed frontend origins | Yes |
| `SMTP_*` | Email configuration | For notifications |
| `GOOGLE_CLIENT_ID/SECRET` | Google OAuth | Optional |

## License

MIT