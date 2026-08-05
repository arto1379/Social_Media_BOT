#!/usr/bin/env bash
# =============================================================================
#  Social Media BOT - Ubuntu installer
#
#  Installs and configures everything on a fresh Ubuntu 22.04 or 24.04 server:
#
#    * system packages (python3, ffmpeg, nginx, certbot)
#    * a dedicated unprivileged service account
#    * a Python virtual environment with the project's dependencies
#    * .env with freshly generated secrets
#    * the database and the first administrator
#    * two systemd services (web + background worker)
#    * nginx as a reverse proxy, HTTP redirected to HTTPS
#    * a Let's Encrypt certificate with automatic renewal
#
#  Usage (from the directory holding this repository):
#
#      sudo bash deploy/install_ubuntu.sh --domain bot.example.com \
#                                         --email you@example.com
#
#  Add --no-tls to skip certbot on a machine with no public DNS name.
#  The script is safe to re-run: it skips whatever is already in place.
# =============================================================================

set -euo pipefail

# --- Defaults ---------------------------------------------------------------
APP_NAME="socialbot"
APP_USER="socialbot"
APP_GROUP="socialbot"
INSTALL_DIR="/opt/socialbot"
DOMAIN=""
EMAIL=""
ADMIN_USER="admin"
USE_TLS=1
BIND_HOST="127.0.0.1"
BIND_PORT="8000"
# Uploads can be large and the ffmpeg conversion runs inside the request, so
# both nginx and gunicorn get a generous timeout.
REQUEST_TIMEOUT=600
MAX_UPLOAD_MB=2048

# --- Pretty output ----------------------------------------------------------
say()  { printf '\n\033[1;34m==>\033[0m %s\n' "$1"; }
ok()   { printf '    \033[0;32mok\033[0m   %s\n' "$1"; }
warn() { printf '    \033[0;33mwarn\033[0m %s\n' "$1"; }
die()  { printf '\n\033[0;31mERROR:\033[0m %s\n\n' "$1" >&2; exit 1; }

# --- Argument parsing -------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --domain)      DOMAIN="$2"; shift 2 ;;
        --email)       EMAIL="$2"; shift 2 ;;
        --admin-user)  ADMIN_USER="$2"; shift 2 ;;
        --install-dir) INSTALL_DIR="$2"; shift 2 ;;
        --port)        BIND_PORT="$2"; shift 2 ;;
        --no-tls)      USE_TLS=0; shift ;;
        -h|--help)
            sed -n '2,26p' "$0"
            exit 0
            ;;
        *) die "Unknown option: $1 (try --help)" ;;
    esac
done

[[ $EUID -eq 0 ]] || die "Run this script with sudo."
[[ -n "$DOMAIN" ]] || die "--domain is required (for example --domain bot.example.com)."
if [[ $USE_TLS -eq 1 && -z "$EMAIL" ]]; then
    die "--email is required for Let's Encrypt. Use --no-tls to skip certificates."
fi

# The repository root is the parent of this script's directory.
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cat <<BANNER

  Social Media BOT installer
  --------------------------
  Domain      : $DOMAIN
  Install dir : $INSTALL_DIR
  Service user: $APP_USER
  Source      : $SOURCE_DIR
  TLS         : $([[ $USE_TLS -eq 1 ]] && echo "Let's Encrypt ($EMAIL)" || echo "skipped")

BANNER

# =============================================================================
#  1. System packages
# =============================================================================
say "Installing system packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq \
    python3 python3-venv python3-pip \
    ffmpeg \
    nginx \
    git curl ca-certificates \
    >/dev/null
ok "python3, ffmpeg, nginx installed"

if [[ $USE_TLS -eq 1 ]]; then
    apt-get install -y -qq certbot python3-certbot-nginx >/dev/null
    ok "certbot installed"
fi

# =============================================================================
#  2. Service account
# =============================================================================
say "Creating the service account"
if id "$APP_USER" &>/dev/null; then
    ok "user '$APP_USER' already exists"
else
    # A system account with no login shell: if the web app is ever
    # compromised, the attacker lands on an account that cannot log in.
    adduser --system --group --home "$INSTALL_DIR" --shell /usr/sbin/nologin "$APP_USER"
    ok "user '$APP_USER' created"
fi

# =============================================================================
#  3. Application files
# =============================================================================
say "Copying the application to $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
if [[ "$SOURCE_DIR" != "$INSTALL_DIR" ]]; then
    # --exclude keeps the developer's local venv and data out of the server.
    if command -v rsync >/dev/null; then
        rsync -a --delete \
              --exclude '.git' --exclude '.venv' --exclude 'venv' \
              --exclude 'data' --exclude 'media' --exclude 'logs' \
              --exclude '.env' --exclude '__pycache__' \
              "$SOURCE_DIR"/ "$INSTALL_DIR"/
    else
        cp -r "$SOURCE_DIR"/. "$INSTALL_DIR"/
        rm -rf "$INSTALL_DIR/.git" "$INSTALL_DIR/.venv"
    fi
fi
mkdir -p "$INSTALL_DIR"/{data,media,logs}
mkdir -p "$INSTALL_DIR"/media/{uploads,processed,thumbnails}
chown -R "$APP_USER:$APP_GROUP" "$INSTALL_DIR"
ok "files in place"

# =============================================================================
#  4. Virtual environment
# =============================================================================
say "Creating the Python virtual environment"
if [[ ! -x "$INSTALL_DIR/.venv/bin/python" ]]; then
    sudo -u "$APP_USER" python3 -m venv "$INSTALL_DIR/.venv"
fi
sudo -u "$APP_USER" "$INSTALL_DIR/.venv/bin/pip" install --quiet --upgrade pip wheel
sudo -u "$APP_USER" "$INSTALL_DIR/.venv/bin/pip" install --quiet -r "$INSTALL_DIR/requirements.txt"
ok "dependencies installed"

# =============================================================================
#  5. Configuration (.env)
# =============================================================================
say "Writing the configuration"
ENV_FILE="$INSTALL_DIR/.env"
if [[ -f "$ENV_FILE" ]]; then
    warn ".env already exists - keeping it (delete it to regenerate)"
    ADMIN_PASSWORD=""
else
    SECRET_KEY="$("$INSTALL_DIR/.venv/bin/python" -c 'import secrets; print(secrets.token_urlsafe(48))')"
    ENCRYPTION_KEY="$("$INSTALL_DIR/.venv/bin/python" -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
    ADMIN_PASSWORD="$("$INSTALL_DIR/.venv/bin/python" -c 'import secrets; print(secrets.token_urlsafe(15))')"
    SCHEME=$([[ $USE_TLS -eq 1 ]] && echo https || echo http)

    cat > "$ENV_FILE" <<ENVEOF
# Generated by deploy/install_ubuntu.sh on $(date -u +"%Y-%m-%d %H:%M:%S UTC")
APP_ENV=production

SECRET_KEY=$SECRET_KEY
ENCRYPTION_KEY=$ENCRYPTION_KEY

PUBLIC_BASE_URL=$SCHEME://$DOMAIN

DATABASE_URL=sqlite:///$INSTALL_DIR/data/socialbot.db
MEDIA_ROOT=$INSTALL_DIR/media
DATA_ROOT=$INSTALL_DIR/data
LOG_ROOT=$INSTALL_DIR/logs
LOG_LEVEL=INFO

HOST=$BIND_HOST
PORT=$BIND_PORT
BEHIND_PROXY=1
FORCE_HTTPS=$USE_TLS

MAX_UPLOAD_MB=$MAX_UPLOAD_MB
FFMPEG_BINARY=ffmpeg
FFPROBE_BINARY=ffprobe

# The web service leaves the schedule to the worker service; see the note in
# app/services/scheduler_service.py about why it must be a single process.
SCHEDULER_ENABLED=0
UPLOAD_POLL_MINUTES=5
STATS_INTERVAL_MINUTES=180
TREND_INTERVAL_HOURS=6

# Fill these in from the Google Cloud console, then:
#   sudo systemctl restart socialbot socialbot-worker
YOUTUBE_CLIENT_ID=
YOUTUBE_CLIENT_SECRET=
YOUTUBE_TREND_REGION=US

ADMIN_USERNAME=$ADMIN_USER
ENVEOF
    ok ".env generated with fresh secrets"
fi

# The file holds the keys to every connected channel: owner-only.
chown "$APP_USER:$APP_GROUP" "$ENV_FILE"
chmod 600 "$ENV_FILE"

# =============================================================================
#  6. Database and first administrator
# =============================================================================
say "Preparing the database"
run_flask() {
    sudo -u "$APP_USER" env -C "$INSTALL_DIR" FLASK_APP=wsgi.py \
        "$INSTALL_DIR/.venv/bin/flask" "$@"
}
run_flask init-db
ok "schema, roles and default settings ready"

if [[ -n "$ADMIN_PASSWORD" ]]; then
    sudo -u "$APP_USER" env -C "$INSTALL_DIR" FLASK_APP=wsgi.py \
        ADMIN_PASSWORD="$ADMIN_PASSWORD" \
        "$INSTALL_DIR/.venv/bin/flask" create-admin --username "$ADMIN_USER" >/dev/null
    ok "administrator '$ADMIN_USER' created"
else
    warn "administrator not created (.env already existed)"
fi

# =============================================================================
#  7. systemd services
# =============================================================================
say "Installing the systemd services"
sed -e "s|@INSTALL_DIR@|$INSTALL_DIR|g" \
    -e "s|@APP_USER@|$APP_USER|g" \
    -e "s|@APP_GROUP@|$APP_GROUP|g" \
    -e "s|@BIND_HOST@|$BIND_HOST|g" \
    -e "s|@BIND_PORT@|$BIND_PORT|g" \
    -e "s|@TIMEOUT@|$REQUEST_TIMEOUT|g" \
    "$INSTALL_DIR/deploy/socialbot.service" > /etc/systemd/system/socialbot.service

sed -e "s|@INSTALL_DIR@|$INSTALL_DIR|g" \
    -e "s|@APP_USER@|$APP_USER|g" \
    -e "s|@APP_GROUP@|$APP_GROUP|g" \
    "$INSTALL_DIR/deploy/socialbot-worker.service" > /etc/systemd/system/socialbot-worker.service

systemctl daemon-reload
systemctl enable --now socialbot socialbot-worker >/dev/null 2>&1 || true
systemctl restart socialbot socialbot-worker
ok "socialbot and socialbot-worker started"

# =============================================================================
#  8. nginx
# =============================================================================
say "Configuring nginx"
sed -e "s|@DOMAIN@|$DOMAIN|g" \
    -e "s|@INSTALL_DIR@|$INSTALL_DIR|g" \
    -e "s|@BIND_HOST@|$BIND_HOST|g" \
    -e "s|@BIND_PORT@|$BIND_PORT|g" \
    -e "s|@MAX_UPLOAD_MB@|$MAX_UPLOAD_MB|g" \
    -e "s|@TIMEOUT@|$REQUEST_TIMEOUT|g" \
    "$INSTALL_DIR/deploy/nginx-socialbot.conf" > /etc/nginx/sites-available/socialbot

# nginx runs as www-data and needs to traverse into the static directory to
# serve CSS and JavaScript itself.
chmod o+x "$INSTALL_DIR" "$INSTALL_DIR/app" "$INSTALL_DIR/app/static"

ln -sf /etc/nginx/sites-available/socialbot /etc/nginx/sites-enabled/socialbot
# The default site would otherwise answer for this server name too.
rm -f /etc/nginx/sites-enabled/default

nginx -t >/dev/null 2>&1 || die "The nginx configuration is not valid. Run 'nginx -t' to see why."
systemctl reload nginx
ok "nginx configured for $DOMAIN"

# =============================================================================
#  9. TLS
# =============================================================================
if [[ $USE_TLS -eq 1 ]]; then
    say "Requesting a Let's Encrypt certificate"
    echo "    The domain must already point at this server's public IP address."
    if certbot --nginx \
               --non-interactive --agree-tos \
               --email "$EMAIL" \
               --domains "$DOMAIN" \
               --redirect; then
        ok "certificate installed, HTTP redirects to HTTPS"
        # certbot ships its own systemd timer; confirm it is armed.
        systemctl enable --now certbot.timer >/dev/null 2>&1 || true
        ok "automatic renewal enabled (certbot.timer)"
    else
        warn "certbot failed. The site is running on plain HTTP."
        warn "Fix DNS, then run: sudo certbot --nginx -d $DOMAIN --redirect"
    fi
else
    warn "TLS skipped. Do not expose this to the internet without HTTPS -"
    warn "passwords and API tokens would cross the network in clear text."
fi

# =============================================================================
#  10. Firewall (only if ufw is already in use)
# =============================================================================
if command -v ufw >/dev/null && ufw status 2>/dev/null | grep -q "Status: active"; then
    say "Opening the firewall for nginx"
    ufw allow 'Nginx Full' >/dev/null
    ok "ports 80 and 443 allowed"
fi

# =============================================================================
#  Done
# =============================================================================
say "Checking the installation"
run_flask check || true

SCHEME=$([[ $USE_TLS -eq 1 ]] && echo https || echo http)
cat <<DONE

=============================================================================
 Installation finished.

   Web interface : $SCHEME://$DOMAIN
   Username      : $ADMIN_USER
DONE

if [[ -n "$ADMIN_PASSWORD" ]]; then
cat <<DONE
   Password      : $ADMIN_PASSWORD

 Write that password down now - it is not stored anywhere.
DONE
fi

cat <<DONE

 Next steps
 ----------
 1. Sign in and change the password.
 2. Create a Google Cloud project, enable "YouTube Data API v3" and
    "YouTube Analytics API", and create an OAuth client (Web application)
    with this redirect URI:

        $SCHEME://$DOMAIN/accounts/oauth/callback/youtube

 3. Put the client id and secret in $INSTALL_DIR/.env, then:

        sudo systemctl restart socialbot socialbot-worker

 4. Open the Accounts page and connect your channel.
 5. Add videos, confirm their rights, and let the bot publish them.

 Useful commands
 ---------------
   sudo systemctl status socialbot socialbot-worker
   sudo journalctl -u socialbot -f
   sudo journalctl -u socialbot-worker -f
   sudo -u $APP_USER env -C $INSTALL_DIR FLASK_APP=wsgi.py $INSTALL_DIR/.venv/bin/flask check

 Troubleshooting is covered in $INSTALL_DIR/CONFIGURE.md.
=============================================================================

DONE
