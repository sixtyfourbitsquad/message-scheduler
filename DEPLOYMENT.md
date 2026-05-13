## Ubuntu VPS deployment (webhook + PostgreSQL + Nginx + Certbot + DuckDNS)

This bot runs in **webhook mode only** behind HTTPS. The FastAPI app exposes:

- `POST /webhook` — Telegram updates (path configurable via `WEBHOOK_PATH`)
- `GET /health` — simple health check for monitoring

### 1) DuckDNS

1. Create a subdomain at [duckdns.org](https://www.duckdns.org).
2. Put `DUCKDNS_DOMAIN` and `DUCKDNS_TOKEN` in `.env` if you want the optional startup IP refresh (`bot/services/duckdns.py`).
3. On the VPS, install a cron job to refresh your public IP periodically (recommended), for example every 5 minutes:

```bash
*/5 * * * * curl -s "https://www.duckdns.org/update?domains=YOURSUBDOMAIN&token=YOURTOKEN&ip=" >/dev/null
```

### 2) PostgreSQL

```bash
sudo apt update
sudo apt install -y postgresql postgresql-contrib
sudo -u postgres psql -c "CREATE USER botuser WITH PASSWORD 'strongpassword';"
sudo -u postgres psql -c "CREATE DATABASE channel_bot OWNER botuser;"
```

Use a URL like:

`postgresql+asyncpg://botuser:strongpassword@127.0.0.1:5432/channel_bot`

### 3) Python app

```bash
sudo apt install -y python3.12 python3.12-venv git
cd /opt
sudo git clone <your-repo-url> channel-bot
sudo chown -R $USER:$USER channel-bot
cd channel-bot
python3.12 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
cp .env.example .env
nano .env
```

Fill in at minimum:

- `TELEGRAM_BOT_TOKEN`
- `ADMIN_TELEGRAM_IDS`
- `WEBHOOK_BASE_URL` (example: `https://mysubdomain.duckdns.org`)
- `WEBHOOK_PATH` (default `/webhook`)
- `WEBHOOK_SECRET_TOKEN` (must match Telegram `secret_token`)
- `DATABASE_URL`

### 4) TLS (Certbot + Nginx)

Point DuckDNS to your VPS public IP, then:

```bash
sudo apt install -y nginx certbot python3-certbot-nginx
sudo cp deploy/nginx-channel-bot.conf /etc/nginx/sites-available/channel-bot
sudo ln -s /etc/nginx/sites-available/channel-bot /etc/nginx/sites-enabled/channel-bot
sudo nginx -t
sudo systemctl reload nginx
sudo certbot --nginx -d YOURSUBDOMAIN.duckdns.org
```

Update the `server_name` and upstream port in `deploy/nginx-channel-bot.conf` if needed.

### 5) systemd service

```bash
sudo cp deploy/channel-bot.service /etc/systemd/system/channel-bot.service
sudo nano /etc/systemd/system/channel-bot.service
```

Set `User`, `Group`, `WorkingDirectory`, and `EnvironmentFile` to your VPS paths.

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now channel-bot
sudo journalctl -u channel-bot -f
```

### 6) Telegram channel checklist

- Bot is **admin** in the target channel with permission to **post messages**.
- For **subscriber tracking** (optional “broadcast to subscribers” DMs): keep the bot a **channel admin** so Telegram sends `chat_member` updates for joins/leaves.

### 7) Operational notes

- New deploys create tables `bot_users`, `channel_delivery_logs`, and `channel_subscribers` automatically (`create_all`). Existing DBs get them on next bot restart the same way.
- If the `schedules` table existed before multi-slot / pool columns, run once on Postgres:

```sql
ALTER TABLE schedules ADD COLUMN IF NOT EXISTS daily_slot_times JSONB;
ALTER TABLE schedules ADD COLUMN IF NOT EXISTS content_pool_json JSONB;
ALTER TABLE schedules ADD COLUMN IF NOT EXISTS jitter_seconds INTEGER;
```

- The app calls `setWebhook` on startup using `WEBHOOK_BASE_URL` + `WEBHOOK_PATH`.
- Schedules are stored in PostgreSQL and reloaded into APScheduler on startup and after Settings “Restart scheduler”.
- If you change DNS or TLS, reload Nginx and restart the service.
