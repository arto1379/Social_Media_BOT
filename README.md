# Social Media BOT

A self-hosted bot that publishes short-form video to social media on a
schedule, tracks how each upload performs, and researches what is trending -
all managed from a web interface with per-user access control.

Version 1 ships with **YouTube Shorts**. The platform layer is a plugin
architecture, so Instagram Reels or TikTok is a new folder under
`app/platforms/`, not a rewrite.

---

## Contents

- [What it does](#what-it-does)
- [Quick start](#quick-start)
- [How the code works](#how-the-code-works)
  - [Project layout](#project-layout)
  - [The request path](#the-request-path)
  - [Background automation](#background-automation)
  - [How a video gets published](#how-a-video-gets-published)
  - [How the money rule works](#how-the-money-rule-works)
  - [Shorts formatting](#shorts-formatting)
  - [Trend research](#trend-research)
  - [Statistics](#statistics)
  - [Users, roles and permissions](#users-roles-and-permissions)
  - [Adding another platform](#adding-another-platform)
- [Configuration summary](#configuration-summary)
- [Command reference](#command-reference)
- [Security notes](#security-notes)
- [Content rights - read this](#content-rights---read-this)
- [Testing](#testing)
- [Licence](#licence)

---

## What it does

| Requirement | How it is met |
|---|---|
| Upload to social media through their APIs | YouTube Data API v3, resumable uploads with progress and retry |
| Statistics of views across platforms | Platform-neutral snapshot table, per-video and per-channel, with history |
| Easy deployment on Ubuntu | One script: `sudo bash deploy/install_ubuntu.sh --domain … --email …` |
| Web interface for everything, including API tokens | Flask interface; tokens are encrypted at rest and never displayed |
| HTTPS with Let's Encrypt, HTTP redirected | certbot + nginx, configured by the installer; the app enforces it too |
| Admin created at deployment, who can then add users with partial access | Bitmask permissions, editable roles, per-user extra grants |
| YouTube Shorts format | ffmpeg conversion to vertical 1080×1920, trimmed to 3 minutes |
| Research trends and publish accordingly | Ranks the trending chart by view velocity, feeds topics into production |
| Automatic in the background, manual through the site | One queue, one code path, two triggers |
| Majority of videos should make money | Licence-aware content picker holding a configurable monetisable ratio |
| Python 3 | Python 3.11+, Flask, SQLAlchemy, APScheduler |
| Neat code, one concern per file, commented | ~40 modules, each with a docstring saying what it is for and why |

---

## Quick start

### Ubuntu server (production)

```bash
git clone <your-repo-url> socialbot && cd socialbot
sudo bash deploy/install_ubuntu.sh --domain bot.example.com --email you@example.com
```

The script installs the packages, creates a service account, generates
secrets, sets up the database and the first administrator, registers two
systemd services, configures nginx and obtains a Let's Encrypt certificate. It
prints the admin password at the end - that is the only time it is shown.

Then add your YouTube API credentials to `/opt/socialbot/.env` and restart:

```bash
sudo systemctl restart socialbot socialbot-worker
```

### Your own PC (Windows, running in the background)

If you want the bot running on a desktop or laptop rather than a server -
web interface on `localhost`, automation running quietly in the background -
follow **[CONFIGURE_LOCAL.md](CONFIGURE_LOCAL.md)**. It is a step-by-step
Windows guide covering ffmpeg, the `.env` file, the database, a Task Scheduler
background task, and connecting YouTube over `http://localhost`.

### Local machine (development)

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env               # then fill in SECRET_KEY and ENCRYPTION_KEY
export APP_ENV=development         # Windows: $env:APP_ENV="development"
export FLASK_APP=wsgi.py

flask init-db
flask create-admin
python run.py                      # http://127.0.0.1:8000
```

Full step-by-step instructions for Ubuntu, Windows Server and a test server -
including the Google Cloud setup and a troubleshooting section - are in
**[CONFIGURE.md](CONFIGURE.md)**.

---

## How the code works

### Project layout

```
Social_Media_BOT/
├── app/
│   ├── __init__.py              Application factory: config, extensions,
│   │                            blueprints, error pages, security headers
│   ├── config.py                Every environment variable, in one place
│   ├── extensions.py            db / login / csrf / migrate singletons
│   ├── logging_setup.py         stdout + rotating file logging
│   ├── cli.py                   flask init-db, create-admin, check, …
│   │
│   ├── models/                  One table per file
│   │   ├── user.py              User, Role (permission bitmask)
│   │   ├── account.py           PlatformAccount + encrypted credentials
│   │   ├── video.py             Video, licence/rights fields, publish gate
│   │   ├── upload.py            UploadJob - the publishing queue
│   │   ├── stats.py             StatSnapshot - append-only metrics history
│   │   ├── trend.py             Trend - researched topics
│   │   ├── setting.py           Runtime settings (key/JSON value)
│   │   └── audit.py             AuditLog - who did what
│   │
│   ├── security/
│   │   ├── permissions.py       The permission catalogue and default roles
│   │   ├── access.py            @permission_required and friends
│   │   └── crypto.py            Fernet encryption for stored tokens
│   │
│   ├── platforms/               The extension point
│   │   ├── base.py              PlatformAdapter interface + result types
│   │   ├── registry.py          @register_adapter / get_adapter
│   │   └── youtube/
│   │       ├── adapter.py       Implements the interface
│   │       ├── auth.py          OAuth 2.0 flow and token refresh
│   │       ├── client.py        Service factory + error classification
│   │       ├── uploader.py      Resumable upload, thumbnails
│   │       ├── analytics.py     Views, watch time, revenue
│   │       └── trends.py        Trending research
│   │
│   ├── services/                All the behaviour
│   │   ├── settings_service.py  Settings schema, defaults, coercion
│   │   ├── audit_service.py     Audit recording
│   │   ├── account_service.py   Credentials with transparent refresh
│   │   ├── video_processing.py  ffprobe inspection, ffmpeg Shorts conversion
│   │   ├── content_service.py   Which video to publish next (the money rule)
│   │   ├── upload_service.py    The queue: planning and execution
│   │   ├── stats_service.py     Collection and aggregation
│   │   ├── trend_service.py     Research and storage
│   │   └── scheduler_service.py APScheduler wiring
│   │
│   ├── web/                     One blueprint per area of the site
│   │   ├── auth.py  dashboard.py  videos.py  accounts.py
│   │   ├── stats.py  trends.py  users.py  settings.py  api.py
│   │   └── forms.py             WTForms definitions and validation
│   │
│   ├── templates/               Jinja2, one folder per blueprint
│   └── static/                  Self-contained CSS and JS - no CDN
│
├── deploy/
│   ├── install_ubuntu.sh        The one-command Ubuntu installer
│   ├── install_windows.ps1      The Windows equivalent
│   ├── socialbot.service        systemd unit - web (gunicorn)
│   ├── socialbot-worker.service systemd unit - background worker
│   ├── nginx-socialbot.conf     Reverse proxy, TLS, upload limits
│   └── backup.sh                Backs up .env, the database and media
│
├── tests/                       pytest suite
├── run.py                       Development server
├── wsgi.py                      Production WSGI entry point
├── worker.py                    Background worker entry point
├── requirements.txt
├── README.md                    You are here
└── CONFIGURE.md                 Detailed setup and troubleshooting
```

### The request path

```
browser
   │
   ▼
nginx ──── TLS termination, HTTP→HTTPS redirect, static files, upload limits
   │
   ▼
gunicorn (3 workers) ── wsgi.py ── create_app()
   │
   ├── before_request       force HTTPS, force password change if due
   ├── Flask-Login          session → current_user
   ├── @permission_required bitmask check, 403 otherwise
   ├── blueprint view       parse the request, call one service, render
   └── after_request        CSP, HSTS, X-Frame-Options, nosniff
```

Views are deliberately thin. Anything that decides something lives in
`app/services/`, which is what lets the scheduler reuse the exact same code
paths as the website.

### Background automation

`worker.py` runs a single APScheduler instance with four recurring jobs:

| Job | Default interval | What it does |
|---|---|---|
| `upload_queue` | 5 minutes | Plan the next automatic upload, then run whatever is due |
| `collect_statistics` | 3 hours | Refresh views/likes/revenue from every connected account |
| `research_trends` | 6 hours | Ask each platform what is trending |
| `maintenance` | daily at 03:30 UTC | Prune old snapshots and stale trends |

The web service runs with `SCHEDULER_ENABLED=0` and the worker with `1`. That
split matters: with three gunicorn workers each running its own scheduler, the
same video would be published three times.

Every job is also runnable on demand - from the dashboard ("Run now") or the
command line (`flask run-job upload_queue`).

### How a video gets published

```
   Add a video (website)            Automatic planning (worker)
            │                                  │
            ▼                                  ▼
   file saved to media/            plan_automatic_uploads()
            │                        · automation on?
            ▼                        · under the daily limit?
   ffprobe inspection                · minimum spacing respected?
            │                        · which video next? ── content_service
            ▼                                  │
   Shorts conversion if needed                 ▼
            │                        queue_video(...) at the next slot
            ▼                                  │
   status: draft                               │
            │                                  │
            ▼                                  │
   rights confirmed by a reviewer              │
            │                                  │
            ▼                                  │
   status: ready ────────────────────────────►─┘
                                               │
                                               ▼
                              UploadJob (pending) in the queue
                                               │
                                               ▼
                                   process_due_jobs()
                                     · re-check the publish gate
                                     · refresh the OAuth token
                                     · resumable upload with progress
                                     · thumbnail (best effort)
                                               │
                        ┌──────────────────────┼──────────────────────┐
                        ▼                      ▼                      ▼
                  succeeded              retryable error        permanent error
              video → published      backoff 5/15/45/135 min    job → failed,
              url recorded           then try again             account flagged
```

The publish gate (`Video.blocking_reasons()`) is checked twice - when queueing
and again immediately before the transfer - so approval withdrawn while a job
sat in the queue still stops the upload.

### How the money rule works

The PRD asks that the majority of published videos be able to make money, with
a few royalty-free clips allowed to gather views. `content_service` implements
that as a **running mix** rather than a fixed rotation:

1. Measure the share of the last 20 automatic uploads that were monetisable.
2. Below the target (default 80%) → the next pick must be monetisable.
   At or above → a royalty-free clip is allowed.
3. Within the chosen class, rank by promise: videos tied to a fresh
   high-scoring trend first, then the longest-waiting.
4. If the preferred class is empty, fall back to the other rather than waste
   the slot - the ratio self-corrects on the next pick.

A video counts as monetisable when its licence is *owned* or *commercially
licensed*. *Royalty-free* is publishable but counts as view-bait. *Unverified*
is never published at all.

### Shorts formatting

YouTube decides whether an upload is a Short by looking at the file, not at an
API flag: vertical, and at most three minutes. `video_processing.py` therefore
does the real work before the upload:

- `probe()` reads duration and frame size with ffprobe, honouring rotation
  metadata so a phone video is measured as it will actually play;
- `shorts_problems()` reports everything disqualifying, in plain language;
- `convert_to_shorts()` re-encodes to 1080×1920, H.264 + AAC, `+faststart`,
  trimmed to the limit, in one of three styles:
  - **blur** (default) - blurred zoomed background, original frame centred
  - **crop** - fills the screen, loses the sides
  - **pad** - black bars

### Trend research

`youtube/trends.py` reads the `mostPopular` chart for the configured region and
ranks by **view velocity** (views ÷ hours since publication) rather than raw
views - a three-day-old video with 400k views says more about what is rising
now than a two-month-old one with 2M. Scores are normalised to 0–100 so runs
are comparable.

What is kept is the **topic and its keywords**, never the file. The trends page
then offers "Make a video about this", which pre-fills the upload form's title,
tags and description. See [Content rights](#content-rights---read-this).

### Statistics

Metrics come from two APIs and are merged:

- **Data API** (`videos.list`) - views, likes, comments. Cheap and always available.
- **Analytics API** (`reports.query`) - watch time, average view percentage,
  subscribers gained, estimated revenue. Owner-only; revenue additionally needs
  the monetary scope and a monetised channel.

Analytics is best-effort: a brand new channel has no analytics rows, and that
must not stop view counts being recorded.

Each collection **appends a snapshot** instead of overwriting a counter. That
costs a little disk and buys the growth curve, "views in the last 7 days", and
an audit of when a number changed. The maintenance job prunes anything over
400 days old.

### Users, roles and permissions

Twelve permission bits (view dashboard, manage videos, approve publishing,
manage accounts, manage users, …) stored as one integer.

- A **Role** carries a bitmask; three are seeded (Administrator, Editor, Analyst)
  and administrators can create more.
- A **User** points at one role and may hold **extra permissions** on top, for
  one-off grants that do not deserve a whole new role.
- `is_admin` short-circuits every check - "admin should have every access",
  including permissions added in a future version.

Guard rails: you cannot remove your own admin flag or disable your own account,
and the last remaining administrator cannot be demoted or deleted.

### Adding another platform

1. Create `app/platforms/instagram/`.
2. Implement `PlatformAdapter` (`app/platforms/base.py`) - authorise, upload,
   measure, research. Return the shared dataclasses, not raw API responses.
3. Decorate the class with `@register_adapter`.
4. Import the package in `app/platforms/__init__.py`.

Nothing else changes. The queue, statistics, dashboard, accounts page and
permission model are already platform-neutral, and `tests/test_platforms.py`
checks that every registered adapter implements the full contract.

---

## Configuration summary

Two kinds of configuration, kept deliberately apart:

**`.env` - belongs to the machine.** Secrets, paths, ports. Needs a restart.

| Variable | Meaning |
|---|---|
| `APP_ENV` | `production`, `development` or `testing` |
| `SECRET_KEY` | Signs session cookies and CSRF tokens |
| `ENCRYPTION_KEY` | Fernet key encrypting OAuth tokens at rest — **back this up** |
| `PUBLIC_BASE_URL` | Public https address; must match the OAuth redirect URI |
| `DATABASE_URL` | SQLite by default; PostgreSQL supported |
| `MEDIA_ROOT` / `DATA_ROOT` / `LOG_ROOT` | Where files live |
| `HOST` / `PORT` | What the app binds to (localhost; nginx proxies) |
| `BEHIND_PROXY` | Trust `X-Forwarded-*` from nginx |
| `FORCE_HTTPS` | Redirect http→https and mark cookies secure |
| `MAX_UPLOAD_MB` | Largest accepted upload; mirror it in nginx |
| `FFMPEG_BINARY` / `FFPROBE_BINARY` | Paths, if not on `PATH` |
| `SCHEDULER_ENABLED` | `1` on the worker, `0` on the web service |
| `UPLOAD_POLL_MINUTES` / `STATS_INTERVAL_MINUTES` / `TREND_INTERVAL_HOURS` | Job intervals |
| `YOUTUBE_CLIENT_ID` / `YOUTUBE_CLIENT_SECRET` | From the Google Cloud console |
| `YOUTUBE_TREND_REGION` | Two-letter region for trend research |

**Settings page - belongs to the operation.** Editable in the browser, applied
on the next background cycle, no restart: automatic publishing on/off, uploads
per day, publishing time slots, minimum spacing, the monetisable ratio, whether
rights confirmation is required, `#Shorts` and attribution handling, default
privacy and category, trend region, and the conversion style.

---

## Command reference

Run from the install directory with `FLASK_APP=wsgi.py` set.

| Command | What it does |
|---|---|
| `flask init-db` | Create the schema, built-in roles and default settings |
| `flask create-admin` | Create the first administrator (`--generate-password` prints one) |
| `flask reset-password <user>` | New password, clears any lockout |
| `flask list-users` | Accounts, roles and state |
| `flask run-job <job>` | Run one background job in the foreground |
| `flask check` | Diagnose the configuration - run this first when stuck |
| `flask db upgrade` | Apply schema migrations after an upgrade |

Job ids: `upload_queue`, `collect_statistics`, `research_trends`, `maintenance`.

---

## Security notes

- **Passwords** are hashed with Werkzeug's default KDF. Eight consecutive
  failures lock the account for 15 minutes; the login form gives the same
  message for a wrong password and an unknown user.
- **OAuth tokens** are encrypted with Fernet before they touch the database and
  are never rendered in a page. `ENCRYPTION_KEY` is the only way to read them -
  back it up with the database, and expect to reconnect every channel if it is
  lost.
- **CSRF** protection on every form; state-changing actions are POST-only,
  including sign-out.
- **Sessions** are HTTP-only, `SameSite=Lax`, and Secure when TLS is on.
- **Headers**: CSP, HSTS, `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy`.
  The CSP is strict because the interface ships its own CSS and JS - no CDN,
  which also means it works on a server with no outbound internet access.
- **Redirects**: `?next=` is validated as a same-site path, so the login form
  cannot be used to bounce somebody off-site.
- **The service account** on Ubuntu is a system user with no login shell, and
  the systemd units restrict it to writing only `data/`, `media/` and `logs/`.
- **Production refuses to start** with a missing or placeholder `SECRET_KEY` or
  `ENCRYPTION_KEY`.
- **Audit log** records access changes, credential changes and publishing, with
  the username and IP.

---

## Content rights - read this

The bot is built to publish material you are allowed to publish, and it will
refuse to publish anything else. This is not caution for its own sake - it is
what makes the "make money" goal achievable:

- YouTube's Partner Programme rejects channels built on **reused content**.
  Re-uploading someone else's video is the fastest way to be denied
  monetisation, and it exposes you to copyright strikes and channel termination.
- So trend research collects **topics to film**, not files to repost. The
  reference link on a trend page is there for you to watch and learn from.
- Every video records where it came from and under what licence. **Unverified
  material is never published.** A named reviewer must confirm the rights, and
  that confirmation is written to the audit log with their username against it.
- Royalty-free material is fully supported - record the attribution line and
  the bot appends it to the description automatically, which is what CC-BY and
  most stock licences require.

If you need volume, the sustainable answers are producing original clips,
licensing stock footage, or cutting your own back catalogue into Shorts. All
three are first-class in the licence model.

---

## Testing

```bash
pip install -r requirements-dev.txt
pytest                       # 110 tests
pytest --cov=app             # with coverage
```

The suite covers the permission model, the content picker's money rule and its
rights gate, queue retry classification, scheduling arithmetic, settings
coercion, token encryption, Shorts validation, statistics aggregation, the
adapter contract, and that every page renders with the right access control.
No test touches the network.

---

## Licence

See [LICENSE](LICENSE).
