<#
=============================================================================
 Social Media BOT - Windows installer

 Sets up the application on Windows Server (or Windows 10/11 for testing):

   * checks Python 3.11+ and ffmpeg
   * creates the virtual environment and installs dependencies
   * generates .env with fresh secrets
   * creates the database and the first administrator
   * optionally registers a Windows service with NSSM so it survives a reboot

 Usage - run in an elevated PowerShell from the project directory:

     .\deploy\install_windows.ps1 -Domain bot.example.com
     .\deploy\install_windows.ps1 -Domain localhost -NoTls -InstallService:$false

 On Windows the app is served by waitress. TLS is NOT terminated by the
 application: put IIS (with ARR) or nginx for Windows in front of it, or use
 win-acme for a Let's Encrypt certificate. CONFIGURE.md walks through both.
=============================================================================
#>

[CmdletBinding()]
param(
    # Public host name used to build OAuth redirect URIs.
    [Parameter(Mandatory = $true)]
    [string]$Domain,

    # Where the app should live. Defaults to the current directory.
    [string]$InstallDir = (Get-Location).Path,

    # Address and port waitress binds to.
    [string]$BindHost = "127.0.0.1",
    [int]$Port = 8000,

    # First administrator's username.
    [string]$AdminUser = "admin",

    # Pass -NoTls when there is no HTTPS in front of the app (test servers).
    [switch]$NoTls,

    # Register Windows services with NSSM (must be on PATH).
    [bool]$InstallService = $true
)

$ErrorActionPreference = "Stop"

function Write-Step($message) { Write-Host "`n==> $message" -ForegroundColor Cyan }
function Write-Ok($message)   { Write-Host "    ok   $message" -ForegroundColor Green }
function Write-Warn($message) { Write-Host "    warn $message" -ForegroundColor Yellow }
function Write-Fail($message) { Write-Host "`nERROR: $message`n" -ForegroundColor Red; exit 1 }

Write-Host @"

  Social Media BOT installer (Windows)
  ------------------------------------
  Domain      : $Domain
  Install dir : $InstallDir
  Bind        : $BindHost`:$Port
  TLS in front: $(if ($NoTls) { "no (test server)" } else { "yes (reverse proxy)" })

"@

# ---------------------------------------------------------------------------
# 1. Prerequisites
# ---------------------------------------------------------------------------
Write-Step "Checking prerequisites"

$python = (Get-Command python -ErrorAction SilentlyContinue)
if (-not $python) { Write-Fail "Python was not found on PATH. Install Python 3.11 or newer from python.org and tick 'Add python.exe to PATH'." }

$versionText = (& python --version) -replace 'Python\s+', ''
$version = [version]($versionText -split '\s')[0]
if ($version -lt [version]"3.11") { Write-Fail "Python $versionText is too old. Version 3.11 or newer is required." }
Write-Ok "Python $versionText"

if (Get-Command ffmpeg -ErrorAction SilentlyContinue) {
    Write-Ok "ffmpeg found"
} else {
    Write-Warn "ffmpeg is not on PATH. Videos cannot be inspected or converted."
    Write-Warn "Install it with 'winget install Gyan.FFmpeg' and reopen PowerShell,"
    Write-Warn "or set FFMPEG_BINARY and FFPROBE_BINARY in .env to their full paths."
}

# ---------------------------------------------------------------------------
# 2. Virtual environment
# ---------------------------------------------------------------------------
Write-Step "Creating the virtual environment"
$venv = Join-Path $InstallDir ".venv"
$venvPython = Join-Path $venv "Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    & python -m venv $venv
    if (-not $?) { Write-Fail "Could not create the virtual environment." }
}
& $venvPython -m pip install --quiet --upgrade pip wheel
& $venvPython -m pip install --quiet -r (Join-Path $InstallDir "requirements.txt")
if (-not $?) { Write-Fail "Dependency installation failed." }
Write-Ok "dependencies installed"

# ---------------------------------------------------------------------------
# 3. Directories
# ---------------------------------------------------------------------------
Write-Step "Creating the data directories"
foreach ($sub in @("data", "logs", "media", "media\uploads", "media\processed", "media\thumbnails")) {
    $path = Join-Path $InstallDir $sub
    if (-not (Test-Path $path)) { New-Item -ItemType Directory -Force $path | Out-Null }
}
Write-Ok "data, logs and media ready"

# ---------------------------------------------------------------------------
# 4. Configuration
# ---------------------------------------------------------------------------
Write-Step "Writing the configuration"
$envFile = Join-Path $InstallDir ".env"
$adminPassword = $null

if (Test-Path $envFile) {
    Write-Warn ".env already exists - keeping it (delete it to regenerate)"
} else {
    $secretKey     = & $venvPython -c "import secrets; print(secrets.token_urlsafe(48))"
    $encryptionKey = & $venvPython -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    $adminPassword = & $venvPython -c "import secrets; print(secrets.token_urlsafe(15))"
    $scheme = if ($NoTls) { "http" } else { "https" }
    $forceHttps = if ($NoTls) { "0" } else { "1" }
    $behindProxy = if ($NoTls) { "0" } else { "1" }

    # A here-string keeps the file readable; single quotes stop PowerShell from
    # expanding anything that looks like a variable inside the generated values.
    $content = @"
# Generated by deploy\install_windows.ps1 on $(Get-Date -Format "yyyy-MM-dd HH:mm:ss")
APP_ENV=production

SECRET_KEY=$secretKey
ENCRYPTION_KEY=$encryptionKey

PUBLIC_BASE_URL=$scheme`://$Domain

DATABASE_URL=sqlite:///$($InstallDir -replace '\\', '/')/data/socialbot.db
MEDIA_ROOT=$InstallDir\media
DATA_ROOT=$InstallDir\data
LOG_ROOT=$InstallDir\logs
LOG_LEVEL=INFO

HOST=$BindHost
PORT=$Port
BEHIND_PROXY=$behindProxy
FORCE_HTTPS=$forceHttps

MAX_UPLOAD_MB=2048
FFMPEG_BINARY=ffmpeg
FFPROBE_BINARY=ffprobe

# The web service leaves the schedule to the worker service.
SCHEDULER_ENABLED=0
UPLOAD_POLL_MINUTES=5
STATS_INTERVAL_MINUTES=180
TREND_INTERVAL_HOURS=6

YOUTUBE_CLIENT_ID=
YOUTUBE_CLIENT_SECRET=
YOUTUBE_TREND_REGION=US

ADMIN_USERNAME=$AdminUser
"@
    Set-Content -Path $envFile -Value $content -Encoding utf8
    Write-Ok ".env generated with fresh secrets"

    # Restrict the file to Administrators and SYSTEM: it holds the keys to
    # every connected channel.
    $acl = Get-Acl $envFile
    $acl.SetAccessRuleProtection($true, $false)
    foreach ($identity in @("BUILTIN\Administrators", "NT AUTHORITY\SYSTEM")) {
        $rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
            $identity, "FullControl", "Allow")
        $acl.AddAccessRule($rule)
    }
    Set-Acl -Path $envFile -AclObject $acl
    Write-Ok ".env locked down to Administrators and SYSTEM"
}

# ---------------------------------------------------------------------------
# 5. Database and administrator
# ---------------------------------------------------------------------------
Write-Step "Preparing the database"
$env:FLASK_APP = "wsgi.py"
Push-Location $InstallDir
try {
    & (Join-Path $venv "Scripts\flask.exe") init-db
    if (-not $?) { Write-Fail "Database initialisation failed." }
    Write-Ok "schema, roles and default settings ready"

    if ($adminPassword) {
        $env:ADMIN_PASSWORD = $adminPassword
        & (Join-Path $venv "Scripts\flask.exe") create-admin --username $AdminUser | Out-Null
        Remove-Item Env:\ADMIN_PASSWORD
        Write-Ok "administrator '$AdminUser' created"
    }
} finally {
    Pop-Location
}

# ---------------------------------------------------------------------------
# 6. Windows services (optional, needs NSSM)
# ---------------------------------------------------------------------------
if ($InstallService) {
    Write-Step "Registering Windows services"
    $nssm = Get-Command nssm -ErrorAction SilentlyContinue

    if (-not $nssm) {
        Write-Warn "NSSM was not found on PATH, so no services were registered."
        Write-Warn "Install it with 'winget install NSSM.NSSM' and re-run this script,"
        Write-Warn "or start the app by hand with the commands printed below."
    } else {
        $waitress = Join-Path $venv "Scripts\waitress-serve.exe"

        # --- Web service -------------------------------------------------
        & nssm install SocialBotWeb $waitress "--listen=$BindHost`:$Port" "--threads=8" "wsgi:application"
        & nssm set SocialBotWeb AppDirectory $InstallDir
        & nssm set SocialBotWeb DisplayName "Social Media BOT - web"
        & nssm set SocialBotWeb Description "Web interface for the Social Media BOT"
        & nssm set SocialBotWeb Start SERVICE_AUTO_START
        & nssm set SocialBotWeb AppStdout (Join-Path $InstallDir "logs\service-web.log")
        & nssm set SocialBotWeb AppStderr (Join-Path $InstallDir "logs\service-web.log")
        Write-Ok "SocialBotWeb registered"

        # --- Worker service ----------------------------------------------
        # Runs the schedule. Exactly one instance, for the same reason as on
        # Ubuntu: two would publish every video twice.
        & nssm install SocialBotWorker $venvPython (Join-Path $InstallDir "worker.py")
        & nssm set SocialBotWorker AppDirectory $InstallDir
        & nssm set SocialBotWorker DisplayName "Social Media BOT - worker"
        & nssm set SocialBotWorker Description "Background uploads, statistics and trend research"
        & nssm set SocialBotWorker Start SERVICE_AUTO_START
        & nssm set SocialBotWorker AppStdout (Join-Path $InstallDir "logs\service-worker.log")
        & nssm set SocialBotWorker AppStderr (Join-Path $InstallDir "logs\service-worker.log")
        Write-Ok "SocialBotWorker registered"

        Start-Service SocialBotWeb, SocialBotWorker
        Write-Ok "both services started"
    }
}

# ---------------------------------------------------------------------------
# 7. Check and summary
# ---------------------------------------------------------------------------
Write-Step "Checking the installation"
Push-Location $InstallDir
try { & (Join-Path $venv "Scripts\flask.exe") check } catch { } finally { Pop-Location }

$scheme = if ($NoTls) { "http" } else { "https" }

Write-Host @"

=============================================================================
 Installation finished.

   Web interface : $scheme`://$Domain`:$Port
   Username      : $AdminUser
"@ -ForegroundColor Green

if ($adminPassword) {
    Write-Host "   Password      : $adminPassword" -ForegroundColor Green
    Write-Host "`n Write that password down now - it is not stored anywhere." -ForegroundColor Yellow
}

Write-Host @"

 Starting it by hand (if you did not register services)
 ------------------------------------------------------
   .venv\Scripts\waitress-serve.exe --listen=$BindHost`:$Port wsgi:application
   .venv\Scripts\python.exe worker.py

 Next steps
 ----------
 1. Sign in and change the password.
 2. Create a Google Cloud project, enable "YouTube Data API v3" and
    "YouTube Analytics API", create an OAuth client (Web application) with
    this redirect URI:

        $scheme`://$Domain/accounts/oauth/callback/youtube

 3. Put the client id and secret in .env, then restart both services.
 4. Put IIS or nginx in front for HTTPS - see CONFIGURE.md.

=============================================================================

"@
