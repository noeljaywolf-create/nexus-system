# Render free-plan testing

This configuration deploys **nexus-system**, not Altitude. Use synthetic test
records only. It is not a production deployment.

## Existing Render service

In Settings, use repository `noeljaywolf-create/nexus-system`, branch `main`,
and leave Root Directory empty:

- Runtime: Python
- Build command: `pip install -r requirements.txt`
- Start command: `python -u render_start.py`
- Instance type: Free
- Health check: `/api/health`
- Environment: `PYTHON_VERSION=3.11.9`, `NEXUS_SECURE_COOKIE=1`,
  `NEXUS_DISABLE_DEMO=1`

Render supplies `PORT` and `RENDER_EXTERNAL_HOSTNAME`. The startup adapter binds
to `0.0.0.0:$PORT` and adds only that hostname to Nexus's allowed hosts. Do not
use `launcher.py` on Render: it is a local/browser launcher.

Deploy the latest commit, visit the HTTPS service URL, and create a disposable
workspace. Test login, refresh, and an invoice workflow. The local-only seeded
demo button is deliberately disabled for hosted access.

## New service

Create a Render Blueprint from this repository to use `render.yaml`. Adding a
Blueprint file does not automatically update an independently configured service;
existing services must have their dashboard commands updated as above.

## Free-tier limits

- SQLite and uploaded files live on an **ephemeral filesystem**. Redeploys,
  restarts, or instance replacement can lose data. Do not store real company data.
- Free instances can sleep; cold starts and downtime are expected. Scheduled
  automations run only while the application is awake.
- This service uses Python's standard-library HTTP server, not a production
  application-server deployment. A successful deploy is not a security approval.
- For retained data, provision a separate PostgreSQL database and configure
  `NEXUS_DATABASE_URL` privately in Render. Install its driver in the build command
  (`pip install -r requirements.txt "psycopg[binary]"`). Check the database
  provider's current free-plan expiry, backup, and connection limits first.
- Never commit database URLs, passwords, `.env` files, or database files.

## Troubleshooting

- Missing `requirements.txt`: deploy a commit containing this file, with Root
  Directory empty.
- No open port: use `render_start.py`, not the loopback-only launcher.
- Host rejected: confirm Render supplied `RENDER_EXTERNAL_HOSTNAME`; add custom
  domains explicitly through `NEXUS_ALLOWED_HOSTS` if needed.
- Cross-origin rejection: use the same HTTPS service origin for UI and API.
