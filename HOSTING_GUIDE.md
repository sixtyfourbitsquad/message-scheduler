# Complete VPS hosting guide (Ubuntu)

This guide walks you from zero to a running **Telegram Channel Automation Bot** on an Ubuntu VPS. The bot uses **HTTPS webhooks**, **PostgreSQL**, and **FastAPI/Uvicorn** behind **Nginx**.

**Assumptions**

- VPS OS: **Ubuntu 22.04 or 24.04** (steps use `apt`; adjust for other distros).
- You have **root** or `sudo` on the VPS.
- You will use a domain name that points to the VPS (e.g. **DuckDNS** + **Let’s Encrypt**).

**Time**: roughly 45–90 minutes the first time, depending on DNS and SSL propagation.

---

## Part A — Accounts and values to collect first

Do these **before** or **while** you set up the server so you are not blocked waiting on IDs.

### Step A1 — Telegram bot token

1. Open Telegram and chat with **[@BotFather](https://t.me/BotFather)**.
2. Send `/newbot` (or use an existing bot with `/token`).
3. Copy the **HTTP API token** (looks like `123456789:AAH...`). Store it securely. You will put it in `.env` as `TELEGRAM_BOT_TOKEN`.

### Step A2 — Your Telegram user ID (admin)

1. The bot only allows users listed in `ADMIN_TELEGRAM_IDS`.
2. Get your numeric ID, for example by messaging **[@userinfobot](https://t.me/userinfobot)** or **[@getidsbot](https://t.me/getidsbot)**.
3. Note the **user id** (digits only). If you have multiple admins, note all IDs separated by commas (no spaces), e.g. `111111111,222222222`.

### Step A3 — Target channel and permissions

1. Create or choose the **public channel** you will automate.
2. Add your bot to the channel: **Channel** → **Administrators** → **Add administrator**.
3. Enable at least: **Post messages** (and any permissions you need for media).
4. Optionally note the channel **@username** or numeric id (e.g. `-100...`) for the bot’s Settings UI later.

### Step A4 — Discussion group (optional, for welcome messages)

1. Link a **discussion group** to the channel (Telegram channel settings).
2. Add the **same bot** to that group as **administrator** so it can post and receive **chat member** updates.
3. In **[@BotFather](https://t.me/BotFather)** → your bot → **Bot Settings** → **Group Privacy**: if you need the bot to see **all** join events in groups, set privacy as documented by Telegram for your use case (group welcomes require the bot to receive updates in that group).

### Step A5 — DuckDNS (or any public HTTPS hostname)

1. Sign up at [https://www.duckdns.org](https://www.duckdns.org).
2. Create a subdomain, e.g. `mychannelbot.duckdns.org`.
3. Copy your **DuckDNS token** from the site.
4. Do **not** set the IP in the DuckDNS web UI until you have the VPS **public IPv4** (Part B). You will point the subdomain to that IP.

### Step A6 — Webhook secret token

1. Generate a long random string (alphanumeric, **8–256** characters). Example (run on your PC or server):

   ```bash
   openssl rand -hex 32
   ```

2. Save this as `WEBHOOK_SECRET_TOKEN` in `.env`. Telegram will send it on each webhook request in the header `X-Telegram-Bot-Api-Secret-Token`.

---

## Part B — VPS access and baseline security

### Step B1 — Create or log into the VPS

1. From your provider’s panel, note the VPS **public IPv4** address.
2. SSH in (replace `root` and the IP if your provider uses a different user):

   ```bash
   ssh root@YOUR_VPS_IP
   ```

3. If the provider gave you an SSH key, use it (`ssh -i path/to/key root@YOUR_VPS_IP`).

### Step B2 — System update

```bash
sudo apt update
sudo apt upgrade -y
```

### Step B3 — Set hostname (optional)

```bash
sudo hostnamectl set-hostname channel-bot-vps
```

### Step B4 — Create a deploy user (recommended)

Running the app as `root` is discouraged. Create a user (example: `deploy`):

```bash
sudo adduser deploy
sudo usermod -aG sudo deploy
```

Log out and log in as `deploy`:

```bash
exit
ssh deploy@YOUR_VPS_IP
```

From here, use `sudo` when commands require root.

### Step B5 — Firewall (UFW)

Allow SSH, HTTP, and HTTPS:

```bash
sudo apt install -y ufw
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
sudo ufw status
```

**Do not** expose PostgreSQL (5432) to the public internet unless you know exactly why.

---

## Part C — Install system packages

### Step C1 — Install Python 3.12, Git, Nginx, Certbot, PostgreSQL client libs

Ubuntu 24.04 often has Python 3.12 by default. On 22.04 you may need the **deadsnakes** PPA for 3.12; simplest path on 22.04 is to use the default Python if it is 3.10+ and matches your plan — **this project targets Python 3.12** per `requirements.txt` / `pyproject.toml`.

**Ubuntu 24.04 example:**

```bash
sudo apt install -y python3.12 python3.12-venv python3-pip git nginx certbot python3-certbot-nginx
```

**PostgreSQL server:**

```bash
sudo apt install -y postgresql postgresql-contrib
```

### Step C2 — Verify Python version

```bash
python3.12 --version
```

You should see `Python 3.12.x`. If `python3.12` is missing, install it using your Ubuntu version’s documented method (e.g. deadsnakes PPA on 22.04), then continue.

---

## Part D — PostgreSQL database

### Step D1 — Switch to the postgres OS user and open psql

```bash
sudo -u postgres psql
```

### Step D2 — Create database role and database

Inside `psql`, run (change passwords and names if you wish):

```sql
CREATE USER botuser WITH PASSWORD 'REPLACE_WITH_STRONG_PASSWORD';
CREATE DATABASE channel_bot OWNER botuser;
GRANT ALL PRIVILEGES ON DATABASE channel_bot TO botuser;
\q
```

### Step D3 — Connection string for the app

The app uses **asyncpg**. Your `DATABASE_URL` must look like:

```text
postgresql+asyncpg://botuser:REPLACE_WITH_STRONG_PASSWORD@127.0.0.1:5432/channel_bot
```

- Host `127.0.0.1` is correct when PostgreSQL and the bot run on the **same** VPS.
- Do not commit this URL with a real password to git.

### Step D4 — Quick connectivity test (optional)

```bash
sudo apt install -y postgresql-client
psql "postgresql://botuser:REPLACE_WITH_STRONG_PASSWORD@127.0.0.1:5432/channel_bot" -c "SELECT 1;"
```

If this fails, check PostgreSQL is running: `sudo systemctl status postgresql`.

---

## Part E — Point DuckDNS to the VPS

### Step E1 — In DuckDNS dashboard

1. Open [https://www.duckdns.org](https://www.duckdns.org) and select your subdomain.
2. Set **current ip** to your VPS **public IPv4** (same as you used for SSH), then save.

### Step E2 — Wait for DNS

Propagation can take from **1 minute to 30+ minutes**. Verify from your PC:

```bash
ping YOURSUBDOMAIN.duckdns.org
```

The resolved IP should match your VPS IP.

### Step E3 — Optional: cron to keep DuckDNS updated

If your home/office IP changes and you use DuckDNS for something else, you can add a cron job on the VPS (only relevant if this hostname tracks **this** server’s IP, which is usually stable on a VPS). For a VPS, updating DuckDNS on boot or daily is optional.

Example cron (replace `YOURSUBDOMAIN` and `YOURTOKEN`):

```bash
crontab -e
```

Add:

```cron
@reboot curl -s "https://www.duckdns.org/update?domains=YOURSUBDOMAIN&token=YOURTOKEN&ip=" >/dev/null
```

---

## Part F — Deploy application files

### Step F1 — Choose install directory

This repo and the sample systemd unit use:

```text
/opt/channel-bot
```

### Step F2 — Copy the project to the VPS

**Option 1 — Git clone** (if the project is in a remote repository):

```bash
sudo mkdir -p /opt/channel-bot
sudo chown deploy:deploy /opt/channel-bot
cd /opt/channel-bot
git clone YOUR_GIT_URL .
```

**Option 2 — SCP/rsync** from your PC (example):

```bash
rsync -avz --exclude '.venv' --exclude '__pycache__' ./Message-shedular/ deploy@YOUR_VPS_IP:/opt/channel-bot/
```

Ensure the `bot/` package and `requirements.txt` end up under `/opt/channel-bot/`.

### Step F3 — Python virtual environment

```bash
cd /opt/channel-bot
python3.12 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

Deactivate when finished (optional):

```bash
deactivate
```

---

## Part G — Environment file `.env`

### Step G1 — Create `.env` from the example

```bash
cd /opt/channel-bot
cp .env.example .env
chmod 600 .env
nano .env
```

### Step G2 — Fill each variable

| Variable | Required | Meaning |
|----------|----------|--------|
| `TELEGRAM_BOT_TOKEN` | Yes | From BotFather. |
| `ADMIN_TELEGRAM_IDS` | Yes | Comma-separated Telegram user IDs. |
| `WEBHOOK_BASE_URL` | Yes | `https://YOURSUBDOMAIN.duckdns.org` — **no trailing slash**. |
| `WEBHOOK_PATH` | Yes | Default `/webhook` (must match Nginx `location` and Telegram URL). |
| `WEBHOOK_SECRET_TOKEN` | Yes | Long random secret; must match what Telegram stores when `setWebhook` runs. |
| `DATABASE_URL` | Yes | `postgresql+asyncpg://...` from Part D. |
| `DUCKDNS_DOMAIN` | No | Subdomain only, e.g. `mysubdomain` (not full URL), if you use startup DuckDNS update. |
| `DUCKDNS_TOKEN` | No | DuckDNS token for optional IP update on bot startup. |
| `DEFAULT_TIMEZONE` | No | IANA zone, e.g. `UTC` or `Europe/Berlin`. |
| `LOG_LEVEL` | No | e.g. `INFO` or `DEBUG`. |

**Full webhook URL** the bot registers with Telegram is:

```text
${WEBHOOK_BASE_URL}${WEBHOOK_PATH}
```

Example: `https://mysubdomain.duckdns.org/webhook`.

### Step G3 — Uvicorn bind host/port (optional)

The app listens on `0.0.0.0:8000` by default. To change:

```bash
export HOST=127.0.0.1
export PORT=8000
```

For production behind Nginx on the same machine, binding **`127.0.0.1:8000`** is slightly tighter than `0.0.0.0`. If you bind only to localhost, set in `.env` or systemd `Environment=`:

```ini
Environment=HOST=127.0.0.1
Environment=PORT=8000
```

---

## Part H — Nginx reverse proxy (HTTP first)

### Step H1 — Copy the sample site config

```bash
sudo cp /opt/channel-bot/deploy/nginx-channel-bot.conf /etc/nginx/sites-available/channel-bot
sudo nano /etc/nginx/sites-available/channel-bot
```

1. Replace **every** `YOURSUBDOMAIN.duckdns.org` with your real hostname.
2. Ensure `proxy_pass` points to the same host/port Uvicorn uses (default `http://127.0.0.1:8000`).

### Step H2 — Enable the site

```bash
sudo ln -sf /etc/nginx/sites-available/channel-bot /etc/nginx/sites-enabled/channel-bot
sudo nginx -t
sudo systemctl reload nginx
```

### Step H3 — HTTP-only smoke test (before TLS)

From your PC:

```bash
curl -i http://YOURSUBDOMAIN.duckdns.org/health
```

You should get `200` and JSON `{"status":"ok"}` **only if** the bot process is already running. If the bot is not running yet, Nginx may return **502** until Part J is done — that is normal.

---

## Part I — TLS certificate (Let’s Encrypt / Certbot)

### Step I1 — Obtain certificate with Nginx plugin

```bash
sudo certbot --nginx -d YOURSUBDOMAIN.duckdns.org
```

Follow prompts (email, agree to terms). Certbot will adjust your Nginx `server` block for HTTPS.

### Step I2 — Verify HTTPS health

```bash
curl -i https://YOURSUBDOMAIN.duckdns.org/health
```

Expect `200` once the bot is running.

### Step I3 — Auto-renewal test

```bash
sudo certbot renew --dry-run
```

---

## Part J — systemd service (run bot on boot)

### Step J1 — Choose the Linux user for the service

The sample unit uses **`www-data`**. That user must be able to **read** `/opt/channel-bot` and **read** `.env`, and **write** is not required for normal operation.

**Simplest permissions** (example: owned by `deploy`, readable by others is not ideal; better is a dedicated user):

**Recommended: dedicated user `channelbot`**

```bash
sudo adduser --system --group --home /opt/channel-bot channelbot
sudo chown -R channelbot:channelbot /opt/channel-bot
```

Then edit the unit file’s `User=` and `Group=` to `channelbot`.

**If you keep `www-data`:**

```bash
sudo chown -R deploy:deploy /opt/channel-bot
sudo chmod -R o+rX /opt/channel-bot
sudo chmod 640 /opt/channel-bot/.env
sudo chgrp www-data /opt/channel-bot/.env
```

Adjust to your security standards.

### Step J2 — Install the unit file

```bash
sudo cp /opt/channel-bot/deploy/channel-bot.service /etc/systemd/system/channel-bot.service
sudo nano /etc/systemd/system/channel-bot.service
```

Check and set:

- `User=` / `Group=`
- `WorkingDirectory=/opt/channel-bot`
- `EnvironmentFile=/opt/channel-bot/.env`
- `ExecStart=/opt/channel-bot/.venv/bin/python -m bot.main`

Optional for localhost-only Uvicorn:

```ini
Environment=HOST=127.0.0.1
Environment=PORT=8000
```

### Step J3 — Enable and start

```bash
sudo systemctl daemon-reload
sudo systemctl enable channel-bot
sudo systemctl start channel-bot
sudo systemctl status channel-bot
```

### Step J4 — Logs

```bash
sudo journalctl -u channel-bot -f
```

On startup the app creates DB tables, starts the scheduler, and calls **Telegram `setWebhook`**. Look for log lines confirming the webhook URL.

### Step J5 — Verify endpoints again

```bash
curl -i https://YOURSUBDOMAIN.duckdns.org/health
```

---

## Part K — Telegram webhook verification

### Step K1 — Confirm secret header behavior

Telegram sends:

```http
X-Telegram-Bot-Api-Secret-Token: <your WEBHOOK_SECRET_TOKEN>
```

Your FastAPI route rejects mismatches with **401**.

### Step K2 — Manual webhook test (optional)

You can use Telegram’s `getWebhookInfo` via browser or curl with your bot token (do not paste tokens in public chats):

```bash
curl "https://api.telegram.org/bot<TOKEN>/getWebhookInfo"
```

Check `url`, `pending_update_count`, and last error fields.

### Step K3 — Use the bot

1. In Telegram, open your bot.
2. Send `/start`.
3. You should see the **CHANNEL CONTROL PANEL** with inline buttons.
4. In **Settings**, set **target channel** and (if used) **discussion group** and **timezone**.

---

## Part L — Post-deploy checklist

1. **Channel**: bot is admin and can post.
2. **Database**: `journalctl` shows no DB connection errors.
3. **HTTPS**: `curl https://.../health` returns 200.
4. **Webhook**: `getWebhookInfo` shows correct URL and no persistent error.
5. **Firewall**: only 22, 80, 443 open to the world; Postgres not exposed.
6. **Backups**: plan `pg_dump` for `channel_bot` on a schedule.
7. **Updates**: `git pull`, `pip install -r requirements.txt`, `sudo systemctl restart channel-bot`.

---

## Part M — Troubleshooting

### Problem: `502 Bad Gateway` from Nginx

- Bot not running: `sudo systemctl status channel-bot`.
- Wrong upstream port: confirm Uvicorn port in Nginx `proxy_pass` and `PORT` env.
- Binding mismatch: if Uvicorn listens on `127.0.0.1` only, Nginx must proxy to `127.0.0.1`, not a Docker bridge IP.

### Problem: `401` on `/webhook`

- `WEBHOOK_SECRET_TOKEN` in `.env` does not match what was used when `setWebhook` was called. Fix `.env`, restart service; bootstrap calls `setWebhook` again on startup.

### Problem: Bot does not respond to `/start`

- Wrong token in `.env`.
- Your user id not in `ADMIN_TELEGRAM_IDS`.
- Webhook not set or Telegram shows errors in `getWebhookInfo`.
- Check `journalctl` for tracebacks.

### Problem: “You must be a channel administrator…”

- Bot channel permissions or wrong channel id in Settings.
- Use Settings escape (`cfg:` / home) if documented in project gates, or fix channel admin from Telegram client.

### Problem: Schedules do not fire

- `sudo systemctl restart channel-bot` after DB changes, or use Settings **Restart scheduler**.
- Target channel must be set.
- Check `failed_deliveries` / logs for posting errors.

### Problem: Welcome message never sends

- Discussion group id must match the **linked** group.
- Bot must be **group admin** and receive `chat_member` updates.
- Welcome must be **enabled** in the bot UI.

---

## Part N — File reference on the server

| Path | Role |
|------|------|
| `/opt/channel-bot/.env` | Secrets and config (chmod 600). |
| `/opt/channel-bot/.venv/` | Python virtual environment. |
| `/etc/systemd/system/channel-bot.service` | systemd unit. |
| `/etc/nginx/sites-enabled/channel-bot` | Nginx site (or symlinked name). |
| `/var/log/nginx/` | Nginx access/error logs. |
| `journalctl -u channel-bot` | Application logs. |

---

## Summary command list (experienced admins)

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3.12 python3.12-venv python3-pip git nginx certbot python3-certbot-nginx postgresql postgresql-contrib ufw
sudo ufw allow OpenSSH && sudo ufw allow 80/tcp && sudo ufw allow 443/tcp && sudo ufw enable
sudo -u postgres psql -c "CREATE USER botuser WITH PASSWORD '***';" -c "CREATE DATABASE channel_bot OWNER botuser;"
# deploy files to /opt/channel-bot, then:
cd /opt/channel-bot && python3.12 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt && deactivate
sudo cp deploy/nginx-channel-bot.conf /etc/nginx/sites-available/channel-bot && sudo nano /etc/nginx/sites-available/channel-bot
sudo ln -sf /etc/nginx/sites-available/channel-bot /etc/nginx/sites-enabled/channel-bot && sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d YOURSUBDOMAIN.duckdns.org
sudo cp deploy/channel-bot.service /etc/systemd/system/channel-bot.service && sudo nano /etc/systemd/system/channel-bot.service
sudo systemctl daemon-reload && sudo systemctl enable --now channel-bot
curl -fsS https://YOURSUBDOMAIN.duckdns.org/health
```

You now have a full end-to-end path from VPS creation to a production-style deployment of this bot.
