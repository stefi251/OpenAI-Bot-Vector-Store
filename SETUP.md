# RegAdam – Server Setup Guide

This guide is for the system administrator deploying the RegAdam FastAPI backend on the Regada VPS.

---

## Prerequisites

- Python 3.11 or higher
- Git
- Nginx (already running on the VPS)
- A terminal with SSH access to the VPS

---

## Step 1 — Clone the Repository

```bash
git clone https://github.com/stefi251/OpenAI-Bot-Vector-Store.git regadam
cd regadam
```

---

## Step 2 — Create the Virtual Environment and Install Dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

> **Important:** The `openai` library must be version 1.30.0 or higher.
> Verify with: `pip show openai`

---

## Step 3 — Add the Private Data Files

The actuator and error reference files are **not included in the repository** for security reasons.
They will be provided separately by Peter Stefanyi as a `.zip` archive.

Unpack them into the project so the folder structure looks like this:

```
regadam/
  data/
    private/
      MASTER_ACTUATOR_REFERENCE.json
      errors_raw.csv
      actuator_tree_raw.csv
```

---

## Step 4 — Create the `.env` Configuration File

Create a file named `.env` in the project root (same folder as `main.py`):

```bash
nano .env
```

Paste the following and fill in the values provided by Peter Stefanyi:

```
OPENAI_API_KEY=<provided by Peter Stefanyi>

ASSISTANT_ID_EN=<provided by Peter Stefanyi>
ASSISTANT_ID_SK=<provided by Peter Stefanyi>
ASSISTANT_ID_RU=<provided by Peter Stefanyi>

VECTOR_STORE_ID=<provided by Peter Stefanyi>
VECTOR_STORE_ID_EN=<provided by Peter Stefanyi>
VECTOR_STORE_ID_SK=<provided by Peter Stefanyi>
VECTOR_STORE_ID_RU=<provided by Peter Stefanyi>

MASTER_ACTUATOR_TREE_PATH=/home/<your-user>/regadam/data/private/MASTER_ACTUATOR_REFERENCE.json
ERROR_DB_PATH=/home/<your-user>/regadam/data/private/errors_raw.csv

ALLOWED_ORIGINS=https://vps.regada.sk

# --- Security keys (generate with: python3 -c "import secrets; print(secrets.token_hex(32))") ---

# Protects the /stats and /debug/* admin endpoints — pass as X-Admin-Stats-Key header
ADMIN_STATS_KEY=<generate a random 32-byte hex string>

# Signs the conversation history blob so clients cannot tamper with it
BLOB_HMAC_SECRET=<generate a random 32-byte hex string>
```

> Replace `/home/<your-user>/regadam/` with the actual path where you cloned the repository.
> The `.env` file must **never** be committed to Git or shared — it contains secret API keys.

### Generating secure random keys

Run this once per key on any machine with Python 3:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

Run it twice to get two different values — one for `ADMIN_STATS_KEY`, one for `BLOB_HMAC_SECRET`.

---

## Step 5 — Test the Application Locally on the VPS

```bash
source .venv/bin/activate
uvicorn main:app --host 127.0.0.1 --port 8000
```

Verify it responds:

```bash
curl http://127.0.0.1:8000/
```

You should get an HTML response. Press `Ctrl+C` to stop.

---

## Step 6 — Run as a Background Service (systemd)

Create a service file so the app starts automatically and restarts on failure:

```bash
sudo nano /etc/systemd/system/regadam.service
```

Paste (adjust paths to match your setup):

```ini
[Unit]
Description=RegAdam FastAPI Service
After=network.target

[Service]
User=<your-user>
WorkingDirectory=/home/<your-user>/regadam
EnvironmentFile=/home/<your-user>/regadam/.env
ExecStart=/home/<your-user>/regadam/.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable regadam
sudo systemctl start regadam
sudo systemctl status regadam
```

---

## Step 7 — Configure Nginx Reverse Proxy

Edit your Nginx site configuration (typically in `/etc/nginx/sites-available/` or `/etc/nginx/conf.d/`):

```nginx
location /regadam/ {
    proxy_pass http://127.0.0.1:8000/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

> **Note the trailing slash** on both `/regadam/` and `http://127.0.0.1:8000/` — this is required so Nginx strips the `/regadam` prefix before forwarding to FastAPI.
>
> **Important:** The `X-Real-IP` header is used by the application to identify client IPs for rate limiting. Nginx must set this header as shown above.

Test and reload Nginx:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

---

## Step 8 — Verify the Full Stack

```bash
curl https://vps.regada.sk/regadam/
```

You should receive the RegAdam HTML interface. If you get `Cannot POST /ask`, the Nginx proxy is not configured correctly — revisit Step 7.

---

## Updating the Application

When a new version is released:

```bash
cd /home/<your-user>/regadam
git pull origin main
source .venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart regadam
```

---

## Admin Endpoints

These endpoints require the `X-Admin-Stats-Key` HTTP header set to the value of `ADMIN_STATS_KEY` in `.env`:

| Endpoint | Purpose |
|---|---|
| `GET /stats` | Usage dashboard — chat counts, feedback scores |
| `GET /health` | Service health check |
| `GET /debug/error/{code}` | Look up error code from the CSV database |
| `GET /debug/actuator/{prefix}` | Look up actuator data by prefix |

Example:
```bash
curl -H "X-Admin-Stats-Key: <your-key>" https://vps.regada.sk/regadam/stats
```

---

## Key Rotation

When rotating secrets:

1. Generate new values with `python3 -c "import secrets; print(secrets.token_hex(32))"`
2. Update `.env` on the server
3. Restart the service: `sudo systemctl restart regadam`
4. Existing browser sessions will get new CSRF tokens on next page load — no user impact
5. `BLOB_HMAC_SECRET` rotation invalidates any open multi-turn conversations (users will need to start a new conversation); this is expected and acceptable

---

## Log Files

The application writes a rotating log to `regadam.log` in the working directory:

- Maximum size: 10 MB per file
- Kept files: 5 (oldest automatically deleted)
- Location: `/home/<your-user>/regadam/regadam.log`

To view recent entries:
```bash
tail -f /home/<your-user>/regadam/regadam.log
```

---

## Troubleshooting

| Problem | Check |
|---|---|
| `Cannot POST /ask` on the public URL | Nginx proxy config — Step 7 |
| `openai` errors on startup | Run `pip show openai` — must be >= 1.30.0 |
| `ERROR_DB_PATH is not set` | Check `.env` paths in Step 4 |
| App not starting after reboot | Run `sudo systemctl status regadam` |
| Port 8000 already in use | Run `lsof -ti :8000 \| xargs kill -9` |
| `/stats` returns 403 | `ADMIN_STATS_KEY` not set in `.env` or wrong header value |
| Feedback buttons not working | Check browser console — CSP header issues would appear here |
| Rate limit errors (429) | Default: 10 requests/60 s per IP for `/ask`; 5/60 s for `/feedback` and `/escalate` |
