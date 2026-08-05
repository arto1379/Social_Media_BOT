# Running the bot on this PC

A step-by-step guide for setting the Social Media BOT up on **this Windows 11
machine** and having it run quietly in the background.

Every path and command below is written for this specific install:

```
Project folder : C:\Users\tolia\OneDrive\Desktop\Pro Projects\Social_Media_BOT
Python          : 3.13.2 (already installed)
Virtual env     : .venv  (already created, dependencies already installed)
```

If you are deploying to a real server instead, use
[CONFIGURE.md](CONFIGURE.md) — this file is the laptop/desktop version.

---

## Contents

- [What you end up with](#what-you-end-up-with)
- [Three things about this PC](#three-things-about-this-pc)
- [Step 1 — Install ffmpeg](#step-1--install-ffmpeg)
- [Step 2 — Check the virtual environment](#step-2--check-the-virtual-environment)
- [Step 3 — Make a data folder outside OneDrive](#step-3--make-a-data-folder-outside-onedrive)
- [Step 4 — Create the .env file](#step-4--create-the-env-file)
- [Step 5 — Create the database and your login](#step-5--create-the-database-and-your-login)
- [Step 6 — Run the configuration check](#step-6--run-the-configuration-check)
- [Step 7 — Start it once, by hand](#step-7--start-it-once-by-hand)
- [Step 8 — Run it in the background](#step-8--run-it-in-the-background)
- [Step 9 — Connect your YouTube channel](#step-9--connect-your-youtube-channel)
- [Step 10 — Publish your first video](#step-10--publish-your-first-video)
- [Set the publishing times for your timezone](#set-the-publishing-times-for-your-timezone)
- [Everyday commands](#everyday-commands)
- [Troubleshooting](#troubleshooting)
- [Removing it](#removing-it)

---

## What you end up with

- The web interface at **<http://localhost:8000>**, reachable only from this PC.
- One background task that starts automatically when you log in and keeps
  running: it serves the website **and** runs the automation (planning uploads,
  publishing, collecting statistics, researching trends).
- Video files and the database stored **outside** OneDrive, so nothing large
  gets synced to the cloud.

It is one process, not two. On a server the web tier and the scheduler are
split so that several web workers cannot each run the schedule; on one PC a
single process does both, which is simpler and is what this guide sets up.

**The PC has to be awake.** Nothing publishes while it is asleep or shut down.
Uploads resume within about five minutes of waking. Pick publishing times when
the machine is normally on — see
[Set the publishing times](#set-the-publishing-times-for-your-timezone).

---

## Three things about this PC

Read these before you start; each one causes a confusing failure otherwise.

### 1. `python` on your PATH is broken

Typing `python` gets you the Microsoft Store stub, which prints
*"Python was not found; run without arguments to install from the Microsoft
Store"* instead of running Python. Your real Python is fine — it is just not
first on the PATH.

**Never type bare `python` for this project.** Always use the virtual
environment's copy:

```powershell
.\.venv\Scripts\python.exe
.\.venv\Scripts\flask.exe
```

Every command in this guide already does that.

### 2. The project lives inside OneDrive

`...\OneDrive\Desktop\Pro Projects\...` is a synced folder. If the bot stored
videos there, OneDrive would try to upload every clip to the cloud, and it can
lock the database file mid-write.

Step 3 puts the data somewhere OneDrive does not touch. Do not skip it.

### 3. PowerShell here is 5.1

`&&`, `||` and `?:` do not work. Use `;` to chain commands, and `if ($?) { }`
when the second command should only run if the first succeeded.

---

## Step 1 — Install ffmpeg

ffmpeg is what inspects videos and converts them into vertical Shorts format.
It is **not currently installed** on this PC.

Open PowerShell and run:

```powershell
winget install Gyan.FFmpeg
```

**Then close PowerShell and open a new window** — the installer changes your
PATH, and an already-open window will not see it.

Check it worked:

```powershell
ffmpeg -version
ffprobe -version
```

Both should print version banners. If they do not, see
[ffmpeg still not found](#ffmpeg-still-not-found-after-installing-it).

---

## Step 2 — Check the virtual environment

The `.venv` folder and all dependencies are already set up. Confirm:

```powershell
cd "C:\Users\tolia\OneDrive\Desktop\Pro Projects\Social_Media_BOT"
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\python.exe -c "import flask, waitress, googleapiclient; print('dependencies OK')"
```

Expected: `Python 3.13.2` and `dependencies OK`.

<details>
<summary>If <code>.venv</code> is missing or broken, rebuild it</summary>

```powershell
cd "C:\Users\tolia\OneDrive\Desktop\Pro Projects\Social_Media_BOT"
Remove-Item -Recurse -Force .venv -ErrorAction SilentlyContinue
& "C:\Users\tolia\AppData\Local\Programs\Python\Python313\python.exe" -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip wheel
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```
</details>

---

## Step 3 — Make a data folder outside OneDrive

```powershell
New-Item -ItemType Directory -Force "C:\Users\tolia\SocialBotData\data"   | Out-Null
New-Item -ItemType Directory -Force "C:\Users\tolia\SocialBotData\media"  | Out-Null
New-Item -ItemType Directory -Force "C:\Users\tolia\SocialBotData\logs"   | Out-Null
Write-Output "data folder ready"
```

`C:\Users\tolia\SocialBotData` is in your user profile but outside the OneDrive
folder, so it is never synced. This is where the database, the video files and
the logs will live.

---

## Step 4 — Create the .env file

`.env` holds the settings and secrets. The block below generates two real
cryptographic keys and writes the whole file for you.

**Paste it as one block** (all of it at once) into PowerShell:

```powershell
cd "C:\Users\tolia\OneDrive\Desktop\Pro Projects\Social_Media_BOT"

$py   = ".\.venv\Scripts\python.exe"
$data = "C:\Users\tolia\SocialBotData"

# SQLAlchemy database URLs use forward slashes even on Windows.
$dbUrl = "sqlite:///C:/Users/tolia/SocialBotData/data/socialbot.db"

$secretKey     = & $py -c "import secrets; print(secrets.token_urlsafe(48))"
$encryptionKey = & $py -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

$lines = @(
    "# Social Media BOT - local configuration",
    "APP_ENV=production",
    "",
    "SECRET_KEY=$secretKey",
    "ENCRYPTION_KEY=$encryptionKey",
    "",
    "PUBLIC_BASE_URL=http://localhost:8000",
    "",
    "DATABASE_URL=$dbUrl",
    "DATA_ROOT=$data\data",
    "MEDIA_ROOT=$data\media",
    "LOG_ROOT=$data\logs",
    "LOG_LEVEL=INFO",
    "",
    "HOST=127.0.0.1",
    "PORT=8000",
    "BEHIND_PROXY=0",
    "FORCE_HTTPS=0",
    "MAX_UPLOAD_MB=2048",
    "",
    "FFMPEG_BINARY=ffmpeg",
    "FFPROBE_BINARY=ffprobe",
    "",
    "SCHEDULER_ENABLED=1",
    "UPLOAD_POLL_MINUTES=5",
    "STATS_INTERVAL_MINUTES=180",
    "TREND_INTERVAL_HOURS=6",
    "",
    "YOUTUBE_CLIENT_ID=",
    "YOUTUBE_CLIENT_SECRET=",
    "YOUTUBE_TREND_REGION=US",
    "",
    "ADMIN_USERNAME=admin"
)

# WriteAllLines, not Set-Content: Set-Content -Encoding utf8 adds a byte-order
# mark that would corrupt the first line (APP_ENV would be silently ignored).
[System.IO.File]::WriteAllLines("$PWD\.env", $lines)

Write-Output "`n.env created. Check the first line is exactly 'APP_ENV=production':"
Get-Content .env -TotalCount 2
```

The last two lines print the top of the file. If you see a stray character
before `APP_ENV`, the file has a BOM — delete it and paste the block again.

### What the important values mean

| Setting | Why it is set this way |
|---|---|
| `APP_ENV=production` | No debug toolbar and no debugger. "Development" mode would expose an interactive Python console to anything that reaches the port. |
| `FORCE_HTTPS=0` | There is no certificate on localhost. With this at `1` every page would redirect to `https://localhost:8000`, which nothing is listening on. |
| `BEHIND_PROXY=0` | No nginx/IIS in front of it here. |
| `HOST=127.0.0.1` | Binds to the loopback address only, so the site is reachable from this PC and from nowhere else. No firewall rule is needed and no one on your network or the internet can reach it. |
| `SCHEDULER_ENABLED=1` | This one process runs the automation as well as the website. |
| `PUBLIC_BASE_URL` | Must match the redirect URI you register with Google in Step 9, exactly. |

`.env` is listed in `.gitignore`, so it will not be committed.

> **Back up `ENCRYPTION_KEY`.** It is the only thing that can decrypt your
> stored YouTube tokens. If you lose it you have to reconnect the channel.

---

## Step 5 — Create the database and your login

```powershell
cd "C:\Users\tolia\OneDrive\Desktop\Pro Projects\Social_Media_BOT"
$env:FLASK_APP = "wsgi.py"

.\.venv\Scripts\flask.exe init-db
```

Expected output:

```
Database schema is up to date.
Migration history stamped at head.
Created built-in roles: Administrator, Editor, Analyst.
Default settings written.
```

Now create your administrator account. You will be prompted for a password
twice — **it must be at least 12 characters**:

```powershell
.\.venv\Scripts\flask.exe create-admin
```

A passphrase of four or five unrelated words is both stronger and easier to
remember than a short scrambled password.

> `$env:FLASK_APP = "wsgi.py"` only lasts for the current PowerShell window.
> Set it again whenever you open a new one to run `flask` commands.

---

## Step 6 — Run the configuration check

```powershell
.\.venv\Scripts\flask.exe check
```

You want to see:

```
[OK  ] SECRET_KEY is set and long enough
[OK  ] ENCRYPTION_KEY is set
[OK  ] Database reachable
[OK  ] At least one user exists
[OK  ] ffmpeg and ffprobe available
[FAIL] YouTube API credentials
[FAIL] At least one account connected
[OK  ] PUBLIC_BASE_URL uses https
```

The two `FAIL` lines are expected at this point — you fix them in Step 9.
Anything else failing should be dealt with before continuing; the check prints
the fix underneath each failure.

---

## Step 7 — Start it once, by hand

Before setting up the background task, confirm it runs:

```powershell
cd "C:\Users\tolia\OneDrive\Desktop\Pro Projects\Social_Media_BOT"
.\.venv\Scripts\waitress-serve.exe --listen=127.0.0.1:8000 wsgi:application
```

You should see, within a second or two:

```
Scheduler started: uploads every 5 min, statistics every 180 min, trends every 6 h.
Serving on http://127.0.0.1:8000
```

That first line is the automation starting inside the same process — that is
what makes a single background task enough.

Open <http://localhost:8000> in your browser and sign in with the account from
Step 5. Have a look around, then come back to PowerShell and press
**Ctrl+C** to stop it.

---

## Step 8 — Run it in the background

Windows Task Scheduler starts the bot when you log in and restarts it if it
ever crashes.

### Register the task

Open PowerShell **as Administrator** (right-click the Start button →
*Terminal (Admin)*), then paste this block:

```powershell
$proj = "C:\Users\tolia\OneDrive\Desktop\Pro Projects\Social_Media_BOT"

$action = New-ScheduledTaskAction -Execute "$proj\.venv\Scripts\waitress-serve.exe" -Argument "--listen=127.0.0.1:8000 wsgi:application" -WorkingDirectory $proj

$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"

$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit 0 -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew

$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType S4U -RunLevel Limited

Register-ScheduledTask -TaskName "SocialMediaBot" -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description "Social Media BOT - web interface and upload automation"
```

What each part does:

| Part | Why |
|---|---|
| `-AtLogOn` | Starts when you sign in to Windows |
| `-LogonType S4U` | Runs without a visible console window. This is the reason the block needs an Administrator prompt |
| `-ExecutionTimeLimit 0` | Never kill it for running too long — it is meant to run forever |
| `-RestartCount 3` | Restart up to 3 times, a minute apart, if it crashes |
| `-AllowStartIfOnBatteries` | Keep running on battery power |
| `-MultipleInstances IgnoreNew` | Never start a second copy |

### Start it now

```powershell
Start-ScheduledTask -TaskName "SocialMediaBot"
Start-Sleep -Seconds 5
Invoke-WebRequest "http://localhost:8000/health" -UseBasicParsing | Select-Object -ExpandProperty Content
```

Expected: `{"database": true, "status": "ok"}`.

Check the task's own view of things:

```powershell
Get-ScheduledTask -TaskName "SocialMediaBot" | Get-ScheduledTaskInfo
```

`LastTaskResult` of `267009` means "currently running" — that is what you want.
`0` means it exited.

### If you would rather not run as Administrator

Drop the `-Principal` line and register without it:

```powershell
Register-ScheduledTask -TaskName "SocialMediaBot" -Action $action -Trigger $trigger -Settings $settings -Description "Social Media BOT"
```

Everything works identically, except a console window stays open in your
taskbar while the bot runs. Minimise it and leave it alone — closing that
window stops the bot.

---

## Step 9 — Connect your YouTube channel

The bot cannot publish anything until you give it API credentials and authorise
your channel.

### 9.1 Create the Google credentials

Follow **[CONFIGURE.md → Part 2](CONFIGURE.md#part-2---youtube-api-credentials)**
for the full walkthrough. The short version:

1. <https://console.cloud.google.com/> → new project.
2. **APIs & Services → Library** → enable **YouTube Data API v3** and
   **YouTube Analytics API**.
3. **OAuth consent screen** → External → fill in the basics → add your own
   Google account under **Test users** → save → click **Publish app**.
4. **Credentials → Create credentials → OAuth client ID → Web application**.
5. Under **Authorised redirect URIs**, add exactly this:

   ```
   http://localhost:8000/accounts/oauth/callback/youtube
   ```

   Google allows plain `http` for `localhost`, so this works without a
   certificate. It must say `localhost` — not `127.0.0.1` — because that is
   what `PUBLIC_BASE_URL` says in your `.env`.

6. Copy the **Client ID** and **Client secret**.

> **Publish the app** (step 3). While the consent screen is in "Testing" mode,
> Google expires the refresh token after 7 days and you have to reconnect every
> week.

### 9.2 Put them in .env

Open `.env` in Notepad:

```powershell
notepad "C:\Users\tolia\OneDrive\Desktop\Pro Projects\Social_Media_BOT\.env"
```

Fill in the two empty values:

```ini
YOUTUBE_CLIENT_ID=1234567890-abcdefg.apps.googleusercontent.com
YOUTUBE_CLIENT_SECRET=GOCSPX-xxxxxxxxxxxxxxxxxxxx
```

Save, then restart the bot so it picks them up:

```powershell
Stop-ScheduledTask  -TaskName "SocialMediaBot"
Start-ScheduledTask -TaskName "SocialMediaBot"
```

### 9.3 Authorise the channel

1. Open <http://localhost:8000> and sign in.
2. **Accounts → Connect an account**.
3. Platform: YouTube. Name: anything, e.g. "Main channel". **Save and connect**.
4. Sign in with the Google account that owns the channel and approve the
   permissions.
5. If you see *"Google hasn't verified this app"*, click **Advanced → Go to …
   (unsafe)**. That warning is normal for a personal project.
6. Back on the Accounts page, press **Test**. It should say
   *"Connected to &lt;your channel&gt;"*.

---

## Step 10 — Publish your first video

### Test safely first

Go to **Settings** and set **Default privacy** to `unlisted`. The whole
pipeline then runs for real but nothing shows up publicly. Change it back to
`public` once you are happy.

### Add the video

1. **Videos → Add video**.
2. Choose a file. Already vertical and under 3 minutes → uploaded as-is.
   Anything else gets converted to 1080×1920 with ffmpeg; leave the tab open
   while that runs.
3. Fill in title, description and tags.
4. **Set the rights fields.** The bot will not publish anything whose rights
   are unverified:
   - *Owned / original* — you made it. Counts as monetisable.
   - *Commercially licensed* — you hold a licence. Counts as monetisable.
   - *Royalty-free* — CC0/CC-BY/stock. Publishable, but counts as view-bait,
     not revenue. Put the credit line in **Attribution** and the bot appends it
     to the description automatically.
   - *Rights unverified* — blocked from publishing.
5. **Add video** → it lands as a draft.

### Approve and publish

On the video page, tick the box and press **Confirm rights**. Status becomes
*ready*.

To publish immediately rather than waiting for a scheduled slot: choose an
account, press **Queue upload**, then go to the **Dashboard** and press
**Plan and run uploads**. The upload runs there and then and the page shows the
result.

From that point on the bot handles it: within five minutes of each publishing
slot it picks the next video, honouring the monetisable ratio and the daily
limit, and uploads it.

---

## Set the publishing times for your timezone

**Publishing times are UTC, not local time.** This PC is on Pacific time, so:

| Setting (UTC) | Your local time (PDT, summer) | Local (PST, winter) |
|---|---|---|
| 09:00 | 02:00 | 01:00 |
| 15:00 | 08:00 | 07:00 |
| 20:00 | 13:00 | 12:00 |

The defaults would try to publish at **2 a.m. your time**, when this PC is
probably asleep — so change them.

To convert: **UTC = your local time + 7 hours** in summer (PDT), **+ 8 hours**
in winter (PST). If the result goes past 24, subtract 24.

Example — to publish at 9 a.m., 1 p.m. and 7 p.m. local time in summer:

| Local | UTC to enter |
|---|---|
| 09:00 | 16:00 |
| 13:00 | 20:00 |
| 19:00 | 02:00 |

So put `16:00, 20:00, 02:00` in **Settings → Publishing times (UTC)**.

Check the current UTC time any time with:

```powershell
(Get-Date).ToUniversalTime().ToString("HH:mm")
```

Re-check these after the clocks change in March and November.

---

## Everyday commands

Run these from PowerShell. Only the register/unregister ones need
Administrator.

```powershell
# Start / stop / restart
Start-ScheduledTask -TaskName "SocialMediaBot"
Stop-ScheduledTask  -TaskName "SocialMediaBot"

# Is it running?
Get-ScheduledTask -TaskName "SocialMediaBot" | Get-ScheduledTaskInfo
Invoke-WebRequest "http://localhost:8000/health" -UseBasicParsing

# Watch the log live
Get-Content "C:\Users\tolia\SocialBotData\logs\socialbot.log" -Tail 50 -Wait

# Just the errors
Select-String -Path "C:\Users\tolia\SocialBotData\logs\socialbot.log" -Pattern "ERROR|WARNING" | Select-Object -Last 30
```

Management commands (set `FLASK_APP` first in each new window):

```powershell
cd "C:\Users\tolia\OneDrive\Desktop\Pro Projects\Social_Media_BOT"
$env:FLASK_APP = "wsgi.py"

.\.venv\Scripts\flask.exe check                       # diagnose the setup
.\.venv\Scripts\flask.exe list-users                  # who can sign in
.\.venv\Scripts\flask.exe reset-password admin        # forgot your password
.\.venv\Scripts\flask.exe run-job upload_queue        # publish now, in this window
.\.venv\Scripts\flask.exe run-job collect_statistics  # refresh view counts now
.\.venv\Scripts\flask.exe run-job research_trends     # research trends now
```

### Backing up

Two things cannot be recreated: `.env` (because of `ENCRYPTION_KEY`) and the
database.

```powershell
$stamp = Get-Date -Format "yyyyMMdd"
$dest  = "C:\Users\tolia\SocialBotBackup\$stamp"
New-Item -ItemType Directory -Force $dest | Out-Null
Copy-Item "C:\Users\tolia\OneDrive\Desktop\Pro Projects\Social_Media_BOT\.env" "$dest\env.backup"
Copy-Item "C:\Users\tolia\SocialBotData\data\socialbot.db" "$dest\socialbot.db"
Write-Output "backed up to $dest"
```

### After changing .env or updating the code

`.env` is only read at startup, so restart the task:

```powershell
Stop-ScheduledTask  -TaskName "SocialMediaBot"
Start-ScheduledTask -TaskName "SocialMediaBot"
```

If you pulled new code, update dependencies and the schema first:

```powershell
cd "C:\Users\tolia\OneDrive\Desktop\Pro Projects\Social_Media_BOT"
$env:FLASK_APP = "wsgi.py"
Stop-ScheduledTask -TaskName "SocialMediaBot"
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\flask.exe db upgrade
.\.venv\Scripts\flask.exe seed-roles
Start-ScheduledTask -TaskName "SocialMediaBot"
```

---

## Troubleshooting

### "Python was not found" / "python is not recognized"

You typed bare `python`. Use the virtual environment's copy instead:

```powershell
.\.venv\Scripts\python.exe --version
```

See [Three things about this PC](#three-things-about-this-pc).

### ffmpeg still not found after installing it

Almost always a stale PowerShell window. Close it, open a new one, and try
`ffmpeg -version` again.

If it is genuinely installed but not on PATH, find it and point `.env` at it
directly:

```powershell
Get-ChildItem "C:\Users\tolia\AppData\Local\Microsoft\WinGet\Packages" -Recurse -Filter ffmpeg.exe -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty FullName
```

Then put the full paths in `.env` and restart:

```ini
FFMPEG_BINARY=C:\full\path\to\ffmpeg.exe
FFPROBE_BINARY=C:\full\path\to\ffprobe.exe
```

### The first setting in .env is ignored

The file was saved with a byte-order mark, so the first key reads as
`\ufeffAPP_ENV` instead of `APP_ENV`. Check:

```powershell
(Get-Content ".env" -Encoding Byte -TotalCount 3) -join ' '
```

`239 187 191` means there is a BOM. Recreate the file with the block in
[Step 4](#step-4--create-the-env-file), which uses `WriteAllLines` and does not
add one. Notepad's "UTF-8" save option also adds a BOM — if you edit `.env` in
Notepad, use **Save as → Encoding: UTF-8** (not "UTF-8 with BOM").

### The browser cannot reach localhost:8000

Check the bot is actually running:

```powershell
Get-ScheduledTask -TaskName "SocialMediaBot" | Get-ScheduledTaskInfo
Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
```

If nothing is listening, run it in the foreground (Step 7) to see the error it
prints on startup.

### Port 8000 is already in use

Find what has it:

```powershell
Get-Process -Id (Get-NetTCPConnection -LocalPort 8000 -State Listen).OwningProcess
```

Either stop that program, or move the bot to another port. Changing the port
means updating **four** things: `PORT` and `PUBLIC_BASE_URL` in `.env`, the
`--listen=` argument in the scheduled task, and the redirect URI in Google
Cloud.

### The page keeps redirecting / "too many redirects"

`FORCE_HTTPS` is `1` but there is no certificate on localhost. Set
`FORCE_HTTPS=0` in `.env` and restart the task.

### "Error 400: redirect_uri_mismatch" when connecting YouTube

The URI registered in Google Cloud does not match what the bot sends. Compare
them character for character:

```powershell
Select-String -Path ".env" -Pattern "PUBLIC_BASE_URL"
```

Google must have exactly `<that value>/accounts/oauth/callback/youtube`. Common
mistakes: `127.0.0.1` on one side and `localhost` on the other, a trailing
slash, a missing port, or `https` instead of `http`.

The Accounts page in the bot displays the exact string to paste.

### It worked, then stopped connecting after a week

The OAuth consent screen is still in **Testing** mode, where Google expires
refresh tokens after 7 days. Go to the Google Cloud console → **OAuth consent
screen** → **Publish app**, then reconnect the account once.

### Nothing is being published

Open the **Dashboard** — the health panel explains most cases. Then check, in
order:

1. Is the task running? `Get-ScheduledTask -TaskName "SocialMediaBot" | Get-ScheduledTaskInfo`
2. **Settings → Automatic publishing** — is it on?
3. **Videos** — is anything at status *ready* with rights confirmed?
4. Publishing times are **UTC** — see
   [the timezone section](#set-the-publishing-times-for-your-timezone).
5. Was the PC asleep at the scheduled time?

Then force a run and read the explanation it prints:

```powershell
$env:FLASK_APP = "wsgi.py"
.\.venv\Scripts\flask.exe run-job upload_queue
```

It always says why, for example *"the daily limit of 3 uploads is reached"* or
*"no video is ready to publish"*.

### Uploads stop after about six videos in a day

That is the YouTube API quota: 10,000 units per day, and each upload costs
around 1,600. The bot marks the job retryable and resumes automatically after
the quota resets at midnight Pacific time. To publish more, request a quota
increase in the Google Cloud console.

### Conversion is very slow

ffmpeg is CPU-bound. Excluding the media folder from Windows Defender's
real-time scanning helps noticeably:

**Windows Security → Virus & threat protection → Manage settings → Exclusions →
Add an exclusion → Folder →** `C:\Users\tolia\SocialBotData\media`

### OneDrive is trying to sync video files

Your `.env` is pointing at a folder inside OneDrive. Check:

```powershell
Select-String -Path ".env" -Pattern "MEDIA_ROOT|DATA_ROOT|LOG_ROOT"
```

All three should be under `C:\Users\tolia\SocialBotData`, not under
`...\OneDrive\...`. Fix them and restart the task.

### I want to reach it from my phone

By design you cannot: `HOST=127.0.0.1` binds to this PC only. Changing it to
`0.0.0.0` would expose a login page over unencrypted HTTP to your whole
network, so do not do that. If you need real remote access, deploy it properly
with HTTPS using [CONFIGURE.md](CONFIGURE.md).

### Locked out of the web interface

```powershell
cd "C:\Users\tolia\OneDrive\Desktop\Pro Projects\Social_Media_BOT"
$env:FLASK_APP = "wsgi.py"
.\.venv\Scripts\flask.exe reset-password admin
```

That also clears the lockout from too many failed sign-in attempts.

---

## Removing it

```powershell
# 1. Stop and remove the background task (needs Administrator)
Stop-ScheduledTask -TaskName "SocialMediaBot" -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName "SocialMediaBot" -Confirm:$false

# 2. Delete the data (videos, database, logs) - irreversible
Remove-Item -Recurse -Force "C:\Users\tolia\SocialBotData"

# 3. Delete the configuration and virtual environment
cd "C:\Users\tolia\OneDrive\Desktop\Pro Projects\Social_Media_BOT"
Remove-Item -Force .env
Remove-Item -Recurse -Force .venv
```

Also revoke the bot's access to your Google account at
<https://myaccount.google.com/permissions>, and delete the Google Cloud project
if you no longer need it.

Videos already published to YouTube are unaffected — remove those from YouTube
Studio.
