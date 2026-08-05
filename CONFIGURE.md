# Configuration guide

Complete setup instructions for the Social Media BOT on **Ubuntu Server**,
**Windows Server** and a **local test server**, followed by a troubleshooting
section covering the problems people actually hit.

If something is broken, jump straight to
[Part 8 - Troubleshooting](#part-8---troubleshooting). The first thing to run
is always:

```bash
flask check
```

---

## Contents

1. [Before you start](#part-1---before-you-start)
2. [YouTube API credentials](#part-2---youtube-api-credentials)
3. [Ubuntu Server - automatic install](#part-3---ubuntu-server-automatic-install)
4. [Ubuntu Server - manual install](#part-4---ubuntu-server-manual-install)
5. [Windows Server](#part-5---windows-server)
6. [Test server](#part-6---test-server)
7. [First run: connect, add, publish](#part-7---first-run-connect-add-publish)
8. [Troubleshooting](#part-8---troubleshooting)
9. [Day-to-day operation](#part-9---day-to-day-operation)
10. [Upgrading](#part-10---upgrading)

---

# Part 1 - Before you start

## What you need

| | Minimum | Comfortable |
|---|---|---|
| OS | Ubuntu 22.04 / Windows Server 2019 | Ubuntu 24.04 LTS |
| CPU | 1 core | 2 cores (ffmpeg is CPU-bound) |
| RAM | 1 GB | 2 GB |
| Disk | 10 GB | 40 GB+ (video files add up fast) |
| Python | 3.11 | 3.12 |
| Other | ffmpeg, a domain name pointing at the server | |

## The domain name

For HTTPS you need a domain (or subdomain) whose DNS **A record already points
at the server's public IP**. Let's Encrypt verifies ownership by connecting to
it over port 80, so this must be true *before* you run the installer.

Check it:

```bash
dig +short bot.example.com      # should print your server's IP
curl -I http://bot.example.com  # should reach your server, not a parking page
```

If you are just testing and have no domain, use
[Part 6 - Test server](#part-6---test-server) instead.

## Accounts you need

- A **Google account that owns a YouTube channel**. A Google account with no
  channel cannot upload - create one at youtube.com first.
- A **Google Cloud project** for the API credentials (free).

---

# Part 2 - YouTube API credentials

Do this once. It is the same on every operating system, and it is the step
people most often get subtly wrong - read the redirect URI part carefully.

## 2.1 Create a project

1. Open <https://console.cloud.google.com/>.
2. Click the project selector at the top, then **New project**.
3. Name it (for example `social-media-bot`) and click **Create**.
4. Make sure the new project is selected before continuing.

## 2.2 Enable the two APIs

Go to **APIs & Services → Library** and enable both:

- **YouTube Data API v3** — uploading, video metadata, public statistics, trends
- **YouTube Analytics API** — watch time, subscribers gained, estimated revenue

Without the second one, uploads still work but the statistics page will only
show public counters.

## 2.3 Configure the consent screen

**APIs & Services → OAuth consent screen**:

1. User type: **External** (unless you have Google Workspace, where
   **Internal** is simpler and skips verification entirely).
2. App name, support email, developer contact email — any real values.
3. **Scopes**: you can leave this empty. The application requests its scopes at
   runtime; the consent screen lists them either way.
4. **Test users**: add the Google account that owns the channel.
   This matters. While the app is in "Testing" mode only listed test users can
   authorise it, and their refresh tokens expire after **7 days**.
5. Save.

> **Publish the app when you are done testing.**
> On the OAuth consent screen page, click **Publish app**. Until you do, you
> will have to reconnect the channel every week when the refresh token expires.
> For a personal bot using only these scopes, Google's verification is usually
> not required — you will see an "unverified app" warning on the consent
> screen, which you can click through with **Advanced → Go to … (unsafe)**.

## 2.4 Create the OAuth client

**APIs & Services → Credentials → Create credentials → OAuth client ID**:

1. Application type: **Web application** (not "Desktop app" — the bot receives
   the callback in a browser).
2. Name: anything.
3. Under **Authorised redirect URIs**, click **Add URI** and enter:

   ```
   https://bot.example.com/accounts/oauth/callback/youtube
   ```

   Replace `bot.example.com` with your domain. This must match
   `PUBLIC_BASE_URL` in `.env` **exactly**:

   - `https`, not `http` (unless you are on a test server without TLS)
   - no trailing slash
   - the same host — `www.bot.example.com` and `bot.example.com` are different
   - the path is exactly `/accounts/oauth/callback/youtube`

   A mismatch produces `Error 400: redirect_uri_mismatch`, and it is the single
   most common setup failure. The exact URI to use is also displayed on the
   application's own **Accounts** page.

4. Click **Create** and copy the **Client ID** and **Client secret**.

## 2.5 Note the quota

The default quota is **10,000 units per day**, and one video upload costs about
**1,600 units**. That works out to roughly **6 uploads per day per project**,
regardless of how many channels you connect.

Reading statistics is cheap (1 unit per call covering up to 50 videos), as is
trend research. If you need more uploads, request a quota increase in
**APIs & Services → Quotas**, or use a separate Google Cloud project per
channel.

The quota resets at **midnight Pacific time**. When it runs out the bot marks
the job as retryable and picks it up again automatically — no action needed.

---

# Part 3 - Ubuntu Server (automatic install)

The fastest path. Tested on Ubuntu 22.04 and 24.04.

## 3.1 Get the code onto the server

```bash
ssh you@your-server
sudo apt update && sudo apt install -y git
git clone <your-repo-url> ~/socialbot
cd ~/socialbot
```

## 3.2 Run the installer

```bash
sudo bash deploy/install_ubuntu.sh \
     --domain bot.example.com \
     --email you@example.com
```

Useful options:

| Option | Effect |
|---|---|
| `--domain` | **Required.** The public host name |
| `--email` | Required unless `--no-tls`. Used for Let's Encrypt expiry notices |
| `--admin-user NAME` | First administrator's username (default `admin`) |
| `--install-dir PATH` | Where to install (default `/opt/socialbot`) |
| `--port N` | Internal port gunicorn binds to (default `8000`) |
| `--no-tls` | Skip certbot — for a server with no public DNS name |

What it does, in order:

1. Installs `python3`, `python3-venv`, `ffmpeg`, `nginx`, `certbot`.
2. Creates the `socialbot` system user (no login shell).
3. Copies the application to `/opt/socialbot` and creates `data/`, `media/`,
   `logs/`.
4. Builds the virtual environment and installs the dependencies.
5. Generates `.env` with a fresh `SECRET_KEY` and `ENCRYPTION_KEY`, and locks
   it to mode 600.
6. Runs `flask init-db` and creates the administrator with a random password.
7. Installs and starts `socialbot.service` and `socialbot-worker.service`.
8. Configures nginx and removes the default site.
9. Requests a Let's Encrypt certificate and turns on the HTTP→HTTPS redirect.
10. Opens ports 80/443 in `ufw` if it is active.
11. Runs `flask check` and prints a summary.

**Write down the administrator password it prints.** It is not stored anywhere.

## 3.3 Add the YouTube credentials

```bash
sudo nano /opt/socialbot/.env
```

Fill in the two values from [Part 2](#part-2---youtube-api-credentials):

```ini
YOUTUBE_CLIENT_ID=1234567890-abcdefg.apps.googleusercontent.com
YOUTUBE_CLIENT_SECRET=GOCSPX-xxxxxxxxxxxxxxxxxxxx
```

Then restart both services:

```bash
sudo systemctl restart socialbot socialbot-worker
```

## 3.4 Verify

```bash
# Both services should be "active (running)"
sudo systemctl status socialbot socialbot-worker

# Should print {"status":"ok","database":true}
curl -s https://bot.example.com/health

# Should be all OK
sudo -u socialbot env -C /opt/socialbot FLASK_APP=wsgi.py \
     /opt/socialbot/.venv/bin/flask check
```

Open `https://bot.example.com`, sign in, and change the password when prompted.

Continue at [Part 7](#part-7---first-run-connect-add-publish).

---

# Part 4 - Ubuntu Server (manual install)

Use this if you want to understand each step, or if the installer does not fit
your environment (different init system, shared host, existing nginx setup).

## 4.1 System packages

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip ffmpeg nginx \
                    certbot python3-certbot-nginx git sqlite3
```

Verify ffmpeg — the bot cannot inspect or convert video without it:

```bash
ffmpeg -version
ffprobe -version
```

## 4.2 Service account and directories

```bash
sudo adduser --system --group --home /opt/socialbot \
             --shell /usr/sbin/nologin socialbot

sudo mkdir -p /opt/socialbot
sudo git clone <your-repo-url> /opt/socialbot
sudo mkdir -p /opt/socialbot/{data,logs}
sudo mkdir -p /opt/socialbot/media/{uploads,processed,thumbnails}
sudo chown -R socialbot:socialbot /opt/socialbot
```

A dedicated system user with no shell means that if the web application is ever
compromised, the attacker lands on an account that cannot log in and can only
write to three directories.

## 4.3 Virtual environment

```bash
sudo -u socialbot python3 -m venv /opt/socialbot/.venv
sudo -u socialbot /opt/socialbot/.venv/bin/pip install --upgrade pip wheel
sudo -u socialbot /opt/socialbot/.venv/bin/pip install -r /opt/socialbot/requirements.txt
```

## 4.4 Configuration

Generate the two secrets:

```bash
/opt/socialbot/.venv/bin/python -c "import secrets; print(secrets.token_urlsafe(48))"
/opt/socialbot/.venv/bin/python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

```bash
sudo -u socialbot cp /opt/socialbot/.env.example /opt/socialbot/.env
sudo -u socialbot nano /opt/socialbot/.env
```

Minimum values to set:

```ini
APP_ENV=production
SECRET_KEY=<the first generated value>
ENCRYPTION_KEY=<the second generated value>
PUBLIC_BASE_URL=https://bot.example.com

DATABASE_URL=sqlite:////opt/socialbot/data/socialbot.db
MEDIA_ROOT=/opt/socialbot/media
DATA_ROOT=/opt/socialbot/data
LOG_ROOT=/opt/socialbot/logs

HOST=127.0.0.1
PORT=8000
BEHIND_PROXY=1
FORCE_HTTPS=1

# 0 here; the worker service owns the schedule.
SCHEDULER_ENABLED=0

YOUTUBE_CLIENT_ID=<from Part 2>
YOUTUBE_CLIENT_SECRET=<from Part 2>
```

> Note the **four** slashes in the SQLite URL. `sqlite:///relative/path` is
> relative; `sqlite:////absolute/path` is absolute.

Lock the file down — it holds the keys to every connected channel:

```bash
sudo chmod 600 /opt/socialbot/.env
sudo chown socialbot:socialbot /opt/socialbot/.env
```

## 4.5 Database and administrator

```bash
cd /opt/socialbot
sudo -u socialbot env FLASK_APP=wsgi.py .venv/bin/flask init-db
sudo -u socialbot env FLASK_APP=wsgi.py .venv/bin/flask create-admin --generate-password
```

The second command prints a generated password once and requires it to be
changed at first sign-in. To choose your own instead, drop
`--generate-password` and you will be prompted.

## 4.6 systemd services

```bash
sudo cp /opt/socialbot/deploy/socialbot.service /etc/systemd/system/
sudo cp /opt/socialbot/deploy/socialbot-worker.service /etc/systemd/system/

# The shipped units contain @PLACEHOLDERS@ - substitute them.
sudo sed -i -e 's|@INSTALL_DIR@|/opt/socialbot|g' \
            -e 's|@APP_USER@|socialbot|g' \
            -e 's|@APP_GROUP@|socialbot|g' \
            -e 's|@BIND_HOST@|127.0.0.1|g' \
            -e 's|@BIND_PORT@|8000|g' \
            -e 's|@TIMEOUT@|600|g' \
            /etc/systemd/system/socialbot.service /etc/systemd/system/socialbot-worker.service

sudo systemctl daemon-reload
sudo systemctl enable --now socialbot socialbot-worker
sudo systemctl status socialbot socialbot-worker
```

**Why two services?** gunicorn runs three worker processes. If each of them
started the scheduler, three copies would plan the same upload and the video
would be published three times. The web service therefore runs with
`SCHEDULER_ENABLED=0`, and `worker.py` — a single process — owns the schedule.

## 4.7 nginx

```bash
sudo cp /opt/socialbot/deploy/nginx-socialbot.conf /etc/nginx/sites-available/socialbot
sudo sed -i -e 's|@DOMAIN@|bot.example.com|g' \
            -e 's|@INSTALL_DIR@|/opt/socialbot|g' \
            -e 's|@BIND_HOST@|127.0.0.1|g' \
            -e 's|@BIND_PORT@|8000|g' \
            -e 's|@MAX_UPLOAD_MB@|2048|g' \
            -e 's|@TIMEOUT@|600|g' \
            /etc/nginx/sites-available/socialbot

sudo ln -s /etc/nginx/sites-available/socialbot /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default

# nginx (www-data) must be able to traverse into the static directory.
sudo chmod o+x /opt/socialbot /opt/socialbot/app /opt/socialbot/app/static

sudo nginx -t && sudo systemctl reload nginx
```

## 4.8 HTTPS with Let's Encrypt

```bash
sudo certbot --nginx -d bot.example.com --agree-tos -m you@example.com --redirect
```

`--redirect` is what adds the HTTP→HTTPS redirect the PRD asks for; certbot
rewrites the nginx site file in place to add it along with the TLS listener.

Verify renewal is armed:

```bash
sudo systemctl list-timers certbot.timer
sudo certbot renew --dry-run
```

Certificates last 90 days and the timer renews them at 30 days remaining. There
is nothing further to do.

## 4.9 Firewall

```bash
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw enable
sudo ufw status
```

Port 8000 must **not** be open to the world — only nginx talks to it.

---

# Part 5 - Windows Server

Works on Windows Server 2019/2022 and on Windows 10/11 for testing.

## 5.1 Prerequisites

**Python 3.11+** — from <https://www.python.org/downloads/windows/>. During
install, tick **"Add python.exe to PATH"**.

**ffmpeg** — the easy way:

```powershell
winget install Gyan.FFmpeg
```

Then close and reopen PowerShell so the new `PATH` takes effect, and check:

```powershell
ffmpeg -version
ffprobe -version
```

If you install it manually instead, unzip to `C:\ffmpeg` and either add
`C:\ffmpeg\bin` to the system `PATH` or set these in `.env`:

```ini
FFMPEG_BINARY=C:\ffmpeg\bin\ffmpeg.exe
FFPROBE_BINARY=C:\ffmpeg\bin\ffprobe.exe
```

**NSSM** (optional, for running as a Windows service):

```powershell
winget install NSSM.NSSM
```

## 5.2 Automatic install

Open PowerShell **as Administrator** in the project directory:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\deploy\install_windows.ps1 -Domain bot.example.com
```

The script checks the prerequisites, builds the virtual environment, generates
`.env` with fresh secrets, restricts that file to Administrators and SYSTEM,
initialises the database, creates the administrator, and registers the two
services with NSSM. It prints the admin password at the end.

## 5.3 Manual install

```powershell
cd C:\socialbot
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip wheel
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# Generate the secrets
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
.\.venv\Scripts\python.exe -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

Copy-Item .env.example .env
notepad .env          # fill in the values, as in section 4.4

$env:FLASK_APP = "wsgi.py"
.\.venv\Scripts\flask.exe init-db
.\.venv\Scripts\flask.exe create-admin
```

Start it with waitress (Windows has no gunicorn):

```powershell
.\.venv\Scripts\waitress-serve.exe --listen=127.0.0.1:8000 --threads=8 wsgi:application
```

And the worker, in a second window:

```powershell
.\.venv\Scripts\python.exe worker.py
```

## 5.4 Running as a Windows service

```powershell
# Web
nssm install SocialBotWeb C:\socialbot\.venv\Scripts\waitress-serve.exe `
     "--listen=127.0.0.1:8000" "--threads=8" "wsgi:application"
nssm set SocialBotWeb AppDirectory C:\socialbot
nssm set SocialBotWeb Start SERVICE_AUTO_START

# Worker (exactly one instance - see section 4.6 for why)
nssm install SocialBotWorker C:\socialbot\.venv\Scripts\python.exe C:\socialbot\worker.py
nssm set SocialBotWorker AppDirectory C:\socialbot
nssm set SocialBotWorker Start SERVICE_AUTO_START

Start-Service SocialBotWeb, SocialBotWorker
Get-Service SocialBot*
```

Edit either service later with `nssm edit SocialBotWeb`.

## 5.5 HTTPS on Windows

The application does not terminate TLS itself. Two options:

### Option A - IIS as a reverse proxy (native)

1. **Server Manager → Add Roles and Features → Web Server (IIS)**.
2. Install [URL Rewrite](https://www.iis.net/downloads/microsoft/url-rewrite)
   and [Application Request Routing](https://www.iis.net/downloads/microsoft/application-request-routing).
3. In IIS Manager → server node → **Application Request Routing Cache →
   Server Proxy Settings** → tick **Enable proxy**.
4. Create a site bound to your domain, then add a rewrite rule forwarding
   everything to `http://127.0.0.1:8000/`.
5. Get a certificate with [win-acme](https://www.win-acme.com/):

   ```powershell
   .\wacs.exe --target iis --host bot.example.com --installation iis
   ```

   win-acme creates a scheduled task for renewal automatically.
6. Add an IIS rewrite rule redirecting HTTP to HTTPS.

In `web.config`, make sure the proxy forwards the protocol, or the app will
redirect in a loop:

```xml
<serverVariables>
  <set name="HTTP_X_FORWARDED_PROTO" value="https" />
</serverVariables>
```

and keep `BEHIND_PROXY=1` in `.env`.

### Option B - nginx for Windows

Download nginx from <https://nginx.org/en/download.html>, adapt
`deploy/nginx-socialbot.conf`, and obtain a certificate with win-acme in
`--installation script` mode. Simpler if you already know nginx.

## 5.6 Windows-specific notes

- **Firewall**: allow 80/443 inbound, keep 8000 internal.

  ```powershell
  New-NetFirewallRule -DisplayName "HTTP"  -Direction Inbound -LocalPort 80  -Protocol TCP -Action Allow
  New-NetFirewallRule -DisplayName "HTTPS" -Direction Inbound -LocalPort 443 -Protocol TCP -Action Allow
  ```

- **Antivirus**: real-time scanning of `media\` slows ffmpeg noticeably. Adding
  an exclusion for the media directory is worth it on a busy install.
- **Long paths**: if a deeply nested media path fails, enable long path support
  (`Computer Configuration → Administrative Templates → System → Filesystem →
  Enable Win32 long paths`).
- **Logs** are in `logs\socialbot.log`, plus `logs\service-*.log` when running
  under NSSM.

---

# Part 6 - Test server

For evaluating the bot on a laptop or an internal VM with no domain and no
certificate.

```bash
git clone <your-repo-url> socialbot && cd socialbot
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
```

Edit `.env` for local use:

```ini
APP_ENV=development
SECRET_KEY=any-long-random-string-for-local-use-only
ENCRYPTION_KEY=<generate a real Fernet key - this one cannot be faked>
PUBLIC_BASE_URL=http://localhost:8000

# No TLS locally, so cookies must not be Secure-only and there is no proxy.
FORCE_HTTPS=0
BEHIND_PROXY=0

DATABASE_URL=sqlite:///data/socialbot.db
SCHEDULER_ENABLED=1        # one process, so it can run the schedule itself
```

`ENCRYPTION_KEY` must be a real Fernet key even locally:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Then:

```bash
export APP_ENV=development FLASK_APP=wsgi.py    # PowerShell: $env:APP_ENV="development"
flask init-db
flask create-admin
python run.py
```

Open <http://localhost:8000>.

## Testing the YouTube connection locally

Google will not accept `http://` redirect URIs for public hosts, but it **does**
allow `http://localhost`. Add this to your OAuth client's authorised redirect
URIs:

```
http://localhost:8000/accounts/oauth/callback/youtube
```

and set `PUBLIC_BASE_URL=http://localhost:8000`. The full connect flow then
works on your machine.

## Testing uploads without going public

Set **Default privacy** to `private` or `unlisted` on the Settings page. The
whole pipeline runs — upload, statistics, the queue — but nothing is visible on
the channel. Delete the test videos from YouTube Studio afterwards.

## Running the jobs by hand

```bash
flask run-job upload_queue          # plan and run uploads
flask run-job collect_statistics    # refresh statistics
flask run-job research_trends       # research trends
flask run-job maintenance           # prune old data
```

## Running the tests

```bash
pip install -r requirements-dev.txt
pytest -v
```

---

# Part 7 - First run: connect, add, publish

## 7.1 Sign in and change the password

Open the site, sign in with the administrator account, and set a new password
when prompted. A passphrase of four or five unrelated words beats a short
scrambled string — minimum length is 12 characters.

## 7.2 Connect the YouTube channel

1. **Accounts → Connect an account**.
2. Platform: YouTube. Name: anything meaningful ("Main channel").
3. **Save and connect** sends you to Google's consent screen.
4. Sign in with the account that owns the channel and approve the permissions:
   upload videos, read channel data, read analytics.
5. If you see "Google hasn't verified this app", click **Advanced → Go to …
   (unsafe)**. That is expected for an unverified personal project.
6. You land back on the Accounts page with the channel connected.

Press **Test** to confirm. It should say "Connected to <your channel name>".

## 7.3 Review the settings

**Settings**, with the defaults worth thinking about:

| Setting | Default | Notes |
|---|---|---|
| Automatic publishing | on | Master switch |
| Uploads per account per day | 3 | Also protects the API quota (~6/day) |
| Publishing times (UTC) | 09:00, 15:00, 20:00 | Times are UTC, not local |
| Minimum hours between uploads | 3 | On top of the slots |
| Share of monetisable uploads | 0.8 | Four in five must be able to earn |
| Require rights confirmation | on | **Leave it on** |
| Convert uploads to Shorts format | on | Needs ffmpeg |
| Conversion style | blur | blur / crop / pad |
| Trend region | US | Two-letter country code |

## 7.4 Add a video

1. **Videos → Add video**.
2. Choose the file. Vertical and under three minutes goes through untouched;
   anything else is converted (keep the tab open while it runs).
3. Fill in the title, description and tags.
4. **Set the rights fields.** This is the part that decides whether the video
   can be published at all:
   - *Owned / original* — you made it. Monetisable.
   - *Commercially licensed* — you hold a licence. Monetisable.
   - *Royalty-free* — CC0/CC-BY/stock. Publishable, but counts as view-bait.
   - *Rights unverified* — **blocked from publishing** until you say more.

   Record where it came from, and put the credit line in **Attribution** for
   anything royalty-free — the bot appends it to the description automatically.
5. **Add video**. It lands as a draft.

## 7.5 Confirm the rights

On the video page, tick the confirmation box and press **Confirm rights**. The
status becomes *ready* and the video enters the pool the automation draws from.

Your username and the time are written to the audit log against that
confirmation. This is deliberate: approving publication is the moment somebody
takes responsibility for the copyright position.

## 7.6 Publish

**Automatically** — nothing to do. Within five minutes the worker plans an
upload for the next publishing slot; the dashboard's queue shows it.

**Manually** — on the video page choose an account and press **Queue upload**.
The worker picks it up on its next pass. To skip the wait, press **Plan and run
uploads** on the dashboard, or:

```bash
flask run-job upload_queue
```

## 7.7 Watch it work

The dashboard shows the live queue with progress bars, recent results, system
health and the library mix. The **Statistics** page fills in a few hours later
after the first collection, or immediately via **Collect now**.

---

# Part 8 - Troubleshooting

## 8.1 First moves

```bash
# The configuration check - covers most install problems
sudo -u socialbot env -C /opt/socialbot FLASK_APP=wsgi.py \
     /opt/socialbot/.venv/bin/flask check

# Are both services alive?
sudo systemctl status socialbot socialbot-worker

# What did they say?
sudo journalctl -u socialbot -n 100 --no-pager
sudo journalctl -u socialbot-worker -n 100 --no-pager
sudo tail -n 100 /opt/socialbot/logs/socialbot.log

# Is the app answering behind nginx?
curl -s http://127.0.0.1:8000/health
```

---

## 8.2 Installation and start-up

### `Refusing to start in production with an insecure configuration`

`SECRET_KEY` or `ENCRYPTION_KEY` is missing, still the placeholder, or too
short. Generate real ones:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Put them in `.env` and restart. (Setting `APP_ENV=development` skips the check —
never do that on a public server.)

### `ENCRYPTION_KEY is not a valid Fernet key`

A Fernet key is exactly 44 url-safe base64 characters. Generate it with the
command above — you cannot invent one by hand.

### Service fails immediately, `status=203/EXEC`

systemd cannot execute the command. Usually the virtual environment path is
wrong or was never created:

```bash
ls -l /opt/socialbot/.venv/bin/gunicorn
sudo -u socialbot /opt/socialbot/.venv/bin/python -c "import flask; print(flask.__version__)"
```

Also check the unit file has no leftover `@PLACEHOLDER@` values:

```bash
grep '@' /etc/systemd/system/socialbot.service
```

### `Permission denied` writing to data/ or media/

```bash
sudo chown -R socialbot:socialbot /opt/socialbot/data /opt/socialbot/media /opt/socialbot/logs
```

If the message mentions a path *outside* the install directory, the systemd
`ReadWritePaths=` line does not cover it. Either move the path back under
`/opt/socialbot` or add it to the unit and `daemon-reload`.

### `sqlite3.OperationalError: unable to open database file`

Either the `data/` directory does not exist, or the SQLite URL has the wrong
number of slashes. An absolute path takes **four**:

```ini
DATABASE_URL=sqlite:////opt/socialbot/data/socialbot.db
```

### `Address already in use`

Something is already on port 8000:

```bash
sudo ss -tlnp | grep 8000
```

Stop it, or change `PORT` in `.env` and the `proxy_pass` line in the nginx site.

---

## 8.3 Web interface

### 502 Bad Gateway

nginx is up but the application is not.

```bash
sudo systemctl status socialbot
sudo journalctl -u socialbot -n 50 --no-pager
curl -s http://127.0.0.1:8000/health
```

If the last command works, nginx is pointed at the wrong host or port — check
`proxy_pass` matches `HOST`/`PORT` in `.env`.

### Redirect loop, or "too many redirects"

The application thinks the request is plain HTTP and redirects to HTTPS
forever. Either nginx is not sending `X-Forwarded-Proto`, or `BEHIND_PROXY=0`.

Confirm this line is present in the nginx `location /` block:

```nginx
proxy_set_header X-Forwarded-Proto $scheme;
```

and `BEHIND_PROXY=1` in `.env`. Restart both after changing either.

### The page loads but has no styling

nginx serves `/static/` directly and cannot read the directory:

```bash
sudo chmod o+x /opt/socialbot /opt/socialbot/app /opt/socialbot/app/static
sudo systemctl reload nginx
```

Check the `alias` in the site file points at the real path, and that it ends
with a `/`.

### 413 Request Entity Too Large

The upload exceeds a limit. Raise **both**:

```ini
# .env
MAX_UPLOAD_MB=4096
```

```nginx
# nginx site
client_max_body_size 4096M;
```

Then `systemctl restart socialbot && systemctl reload nginx`.

### 504 Gateway Timeout on upload

The ffmpeg conversion ran longer than a timeout. Raise both the nginx
`proxy_read_timeout` and gunicorn's `--timeout` (they are `@TIMEOUT@` in the
shipped templates, 600 s by default).

Alternatively upload files that are already vertical and under three minutes —
no conversion happens, and the upload returns immediately.

### `CSRF token missing or incorrect`

Usually a stale tab left open past the session lifetime — reload and try again.
If it happens on every request, the cookie is not being stored: with
`FORCE_HTTPS=1` the session cookie is Secure-only and a browser will not keep it
over plain HTTP. On a test server without TLS, set `FORCE_HTTPS=0`.

### Locked out of the administrator account

```bash
cd /opt/socialbot
sudo -u socialbot env FLASK_APP=wsgi.py .venv/bin/flask reset-password admin
```

That also clears the failed-login lockout and re-enables a disabled account.

---

## 8.4 Connecting a YouTube channel

### `Error 400: redirect_uri_mismatch`

The most common failure. The URI registered in Google Cloud must match what the
app sends, **character for character**. Compare:

```bash
grep PUBLIC_BASE_URL /opt/socialbot/.env
```

against **APIs & Services → Credentials → your client → Authorised redirect
URIs**. It must be:

```
<PUBLIC_BASE_URL>/accounts/oauth/callback/youtube
```

Watch for: `http` vs `https`, a trailing slash, `www.` present on one side only,
a port number on one side only. The Accounts page displays the exact string to
paste.

After editing in Google Cloud, allow a minute for the change to propagate.

### `Access blocked: This app's request is invalid`

Almost always the same cause as above, or the OAuth client is the wrong type.
It must be **Web application**, not "Desktop app".

### `Google hasn't verified this app`

Expected while the consent screen is unpublished or unverified. Click
**Advanced → Go to … (unsafe)**. To remove the warning, publish the app on the
OAuth consent screen page.

### `Google did not return a refresh token`

Google only issues a refresh token on the first authorisation of a given
account. Remove the app at
<https://myaccount.google.com/permissions>, then connect again — the full
consent screen will be shown and a refresh token issued.

### The connection works, then breaks after 7 days

The OAuth consent screen is still in **Testing** mode, where refresh tokens
expire after a week. Go to **OAuth consent screen** and click **Publish app**.

### `The connected Google account has no YouTube channel`

You authorised a Google account that has never created a channel. Sign in at
youtube.com with that account, create a channel, then reconnect.

### `Reconnect the account from the Accounts page`

The refresh token was revoked — a password change, a permissions cleanup, or
the 7-day testing expiry. Press **Connect** on the account and authorise again.

---

## 8.5 Uploads

### Nothing is being published

Work down this list; the dashboard's health panel answers most of it.

1. **Is the worker running?**
   `systemctl status socialbot-worker` — it must be *active (running)*.
2. **Is automatic publishing on?** Settings → Automatic publishing.
3. **Is anything ready?** Videos → the library summary. A video needs status
   *ready*, confirmed rights and Shorts format.
4. **Is the daily limit reached?** Settings → Uploads per account per day.
5. **Is it waiting for a slot?** Publishing times are **UTC**. `date -u` on the
   server tells you the current UTC time.
6. **Is the account connected and enabled?** Accounts → status column.

Then force a run and read the explanation:

```bash
cd /opt/socialbot
sudo -u socialbot env FLASK_APP=wsgi.py .venv/bin/flask run-job upload_queue
```

The planner always prints a reason — "the daily limit of 3 uploads is reached",
"no video is ready to publish", and so on.

### `The daily YouTube API quota is limited`

You used the 10,000 units. One upload costs ~1,600, so that is about six per
day. The job is marked retryable and resumes after the quota resets at midnight
Pacific time. To publish more, request a quota increase in Google Cloud or use a
separate project per channel.

### Upload fails with `HTTP 400 ... invalidVideoMetadata`

Something in the metadata was rejected. Titles are capped at 100 characters,
descriptions at 5000, and tags share a 500-character budget — the bot enforces
all three, so the usual remaining cause is an invalid `categoryId` for the
channel's region. Try category 22 (People & Blogs).

### The upload succeeded but is not treated as a Short

The file must be vertical and at most three minutes. Check the video page:
"Format" should read *Shorts ready*, with a frame like 1080×1920. If not, press
**Re-run Shorts conversion**.

Note that YouTube sometimes takes a few minutes after processing to reclassify
a video as a Short.

### A video is stuck in "publishing"

The worker was killed mid-transfer. The job stays as it was; requeue it:

Videos → Upload queue → **Retry** on that row.

---

## 8.6 Video processing

### `ffmpeg was not found`

```bash
sudo apt install -y ffmpeg          # Ubuntu
winget install Gyan.FFmpeg          # Windows (reopen the shell afterwards)
```

If it is installed somewhere unusual, set the full paths in `.env`:

```ini
FFMPEG_BINARY=/usr/local/bin/ffmpeg
FFPROBE_BINARY=/usr/local/bin/ffprobe
```

### `The file contains no video stream`

The upload is audio-only, or the container is corrupt. Check it by hand:

```bash
ffprobe -v error -show_streams /opt/socialbot/media/uploads/<file>
```

### Conversion is very slow

ffmpeg is CPU-bound and the default preset is `medium`. On a single-core VPS a
three-minute clip can take several minutes. Options: give the server another
core, or upload files that are already vertical and short so no conversion is
needed.

### `ffmpeg failed (exit 1)`

The last lines of ffmpeg's own output are included in the error message and
usually say exactly what is wrong. Reproduce it by hand to see everything:

```bash
ffmpeg -i input.mp4 -vf "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920" -t 180 out.mp4
```

---

## 8.7 Statistics

### Everything is zero

Statistics are collected every three hours. Force a run:

```bash
flask run-job collect_statistics
```

Nothing is recorded until at least one video has been published *through the
bot* — it tracks what it uploaded, not the channel's back catalogue.

### Revenue is always empty

Estimated revenue needs all three of: the channel in the YouTube Partner
Programme, the monetary scope granted during authorisation, and actual revenue
in the period. If the channel is monetised but the figure stays empty,
disconnect and reconnect the account so the scope is granted again.

### Watch time is empty but views work

Views come from the Data API, watch time from the Analytics API. Check the
**YouTube Analytics API** is enabled in Google Cloud, then reconnect. A brand
new channel also simply has no analytics rows yet.

---

## 8.8 Trends

### `Connect a YouTube account first`

Trend research calls the API with a connected account's credentials. Connect
one, then run:

```bash
flask run-job research_trends
```

### The trends list is empty for my region

Not every region code has a populated `mostPopular` chart. Try a large market
(`US`, `GB`, `DE`, `IN`) in Settings → Trend region to confirm the pipeline
works, then narrow down.

---

## 8.9 TLS and certificates

### certbot: "Timeout during connect"

Let's Encrypt could not reach port 80 on your server.

```bash
dig +short bot.example.com            # must be this server's public IP
sudo ufw allow 'Nginx Full'
curl -I http://bot.example.com        # must reach nginx
```

Cloud providers also have their own firewall (AWS security groups, Azure NSGs) —
check port 80 is open there too.

### Renewal fails

```bash
sudo certbot renew --dry-run
sudo systemctl list-timers certbot.timer
```

The usual cause is that the ACME challenge location was removed from the nginx
site. Keep this block reachable over plain HTTP:

```nginx
location /.well-known/acme-challenge/ { root /var/www/html; allow all; }
```

### Browser says the certificate is invalid

Usually the certificate was issued for a different name than the one you are
visiting (`bot.example.com` vs `www.bot.example.com`). Reissue for both:

```bash
sudo certbot --nginx -d bot.example.com -d www.bot.example.com --redirect
```

---

## 8.10 Performance

### The site is slow with many videos

The library and queue pages are paginated at 25 rows. If the database itself is
slow, switch from SQLite to PostgreSQL (section 9.4).

### The database is getting big

The maintenance job prunes statistics older than 400 days nightly. Force it:

```bash
flask run-job maintenance
```

SQLite does not return freed space to the disk by itself:

```bash
sudo systemctl stop socialbot socialbot-worker
sudo -u socialbot sqlite3 /opt/socialbot/data/socialbot.db "VACUUM;"
sudo systemctl start socialbot socialbot-worker
```

### The disk is filling up

Video files are the cause, not the database.

```bash
du -sh /opt/socialbot/media/*
```

`media/uploads/` holds the originals and `media/processed/` the converted
copies. Once a video is published you can delete it from the library (which
removes its files) without affecting what is live on YouTube.

---

# Part 9 - Day-to-day operation

## 9.1 Service management

```bash
sudo systemctl restart socialbot socialbot-worker
sudo systemctl stop socialbot-worker        # pause all automation
sudo journalctl -u socialbot-worker -f      # follow the worker live
```

## 9.2 Backups

Three things cannot be regenerated: `.env` (especially `ENCRYPTION_KEY`), the
database, and the media files.

```bash
sudo bash /opt/socialbot/deploy/backup.sh                # config + database
sudo bash /opt/socialbot/deploy/backup.sh --with-media   # everything
```

Nightly, via cron:

```bash
sudo crontab -e
# 0 4 * * * /opt/socialbot/deploy/backup.sh >> /var/log/socialbot-backup.log 2>&1
```

> **Losing `ENCRYPTION_KEY` means every stored OAuth token is unreadable** and
> each channel must be reconnected by hand. Back it up somewhere other than the
> server itself.

## 9.3 Adding users

**Users & roles → Add user**. Pick a role (Editor, Analyst, or one you create)
and optionally add individual permissions on top for one-off access. Leave
"Require a password change at next sign-in" ticked.

To create a role: **Add role**, tick the permissions, save.

## 9.4 Moving to PostgreSQL

Worth it above a few thousand videos, or if you want concurrent writers.

```bash
sudo apt install -y postgresql
sudo -u postgres createuser socialbot --pwprompt
sudo -u postgres createdb socialbot -O socialbot
/opt/socialbot/.venv/bin/pip install "psycopg[binary]"
```

```ini
DATABASE_URL=postgresql+psycopg://socialbot:PASSWORD@localhost/socialbot
```

```bash
cd /opt/socialbot
sudo -u socialbot env FLASK_APP=wsgi.py .venv/bin/flask init-db
sudo systemctl restart socialbot socialbot-worker
```

Note that `init-db` creates an empty schema — it does not migrate existing
SQLite data. Move that with a tool such as `pgloader` if you need it.

## 9.5 Log rotation

The application rotates its own logs at 5 MB, keeping five files. systemd's
journal is capped separately:

```bash
sudo journalctl --vacuum-time=30d
```

---

# Part 10 - Upgrading

```bash
cd /opt/socialbot

# 1. Back up first - always
sudo bash deploy/backup.sh

# 2. Stop the services
sudo systemctl stop socialbot socialbot-worker

# 3. Pull the new code (keeps your .env, data/ and media/)
sudo -u socialbot git pull

# 4. Update dependencies
sudo -u socialbot .venv/bin/pip install -r requirements.txt

# 5. Apply any schema changes
sudo -u socialbot env FLASK_APP=wsgi.py .venv/bin/flask db upgrade
sudo -u socialbot env FLASK_APP=wsgi.py .venv/bin/flask seed-roles

# 6. Start again and check
sudo systemctl start socialbot socialbot-worker
sudo -u socialbot env FLASK_APP=wsgi.py .venv/bin/flask check
```

`seed-roles` refreshes the built-in roles so permissions added in the new
version reach the Administrator and Editor roles. Custom roles are left alone —
grant new permissions to those yourself in **Users & roles**.

If an upgrade goes wrong, restore `.env` and the database from the backup taken
in step 1, then `git checkout` the previous tag.
