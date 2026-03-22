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
```

> Replace `/home/<your-user>/regadam/` with the actual path where you cloned the repository.
> The `.env` file must never be committed to Git or shared — it contains secret API keys.

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

## Troubleshooting

| Problem | Check |
|---|---|
| `Cannot POST /ask` on the public URL | Nginx proxy config — Step 7 |
| `openai` errors on startup | Run `pip show openai` — must be >= 1.30.0 |
| `ERROR_DB_PATH is not set` | Check `.env` paths in Step 4 |
| App not starting after reboot | Run `sudo systemctl status regadam` |
| Port 8000 already in use | Run `lsof -ti :8000 \| xargs kill -9` |
