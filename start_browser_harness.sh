#!/usr/bin/env bash

# ==============================================================================
# BROWSER-HARNESS (LAYER 2) LAUNCHER FOR HEADLESS LINUX / GOOGLE APPS
# Launches Google Chrome Stable inside an Xvfb virtual framebuffer on CDP port 9222.
# ==============================================================================

set -eo pipefail

PORT=9222
CHROME_PROFILE="/tmp/chrome-harness-profile"

# --- Color Codes ---
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO] $(date '+%Y-%m-%d %H:%M:%S') - $1${NC}"; }
log_success() { echo -e "${GREEN}[SUCCESS] $(date '+%Y-%m-%d %H:%M:%S') - $1${NC}"; }
log_warn() { echo -e "${YELLOW}[WARNING] $(date '+%Y-%m-%d %H:%M:%S') - $1${NC}"; }
log_error() { echo -e "${RED}[ERROR] $(date '+%Y-%m-%d %H:%M:%S') - $1${NC}"; }

# --- Check Privileges ---
SUDO=""
if [ "$EUID" -ne 0 ]; then
    if command -v sudo >/dev/null 2>&1; then
        SUDO="sudo"
    fi
fi

# --- 1. Verify and Install Xvfb ---
if ! command -v Xvfb >/dev/null 2>&1; then
    log_info "Xvfb is not installed. Attempting installation..."
    if [ -n "$SUDO" ] || [ "$EUID" -eq 0 ]; then
        $SUDO apt-get update -y || true
        $SUDO apt-get install -y xvfb || true
    else
        log_warn "Missing sudo privileges. Xvfb install skipped. Please ensure it is installed."
    fi
fi

# --- 2. Verify and Install Google Chrome Stable ---
if ! command -v google-chrome >/dev/null 2>&1; then
    log_info "Official Google Chrome is not installed. Fetching stable debian package..."
    if [ -n "$SUDO" ] || [ "$EUID" -eq 0 ]; then
        wget -q https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb || true
        if [ -f "google-chrome-stable_current_amd64.deb" ]; then
            $SUDO apt-get update -y || true
            $SUDO apt-get install -y ./google-chrome-stable_current_amd64.deb || true
            rm -f google-chrome-stable_current_amd64.deb
        else
            log_error "Failed to download Google Chrome installer."
        fi
    else
        log_warn "Missing sudo privileges. Google Chrome install skipped. Please ensure it is installed."
    fi
fi

# --- 3. Run Chrome in Xvfb virtual frame in background ---
log_info "Checking if a process is already listening on port ${PORT}..."
if netstat -tuln 2>/dev/null | grep -q ":${PORT} "; then
    log_warn "A process is already active on port ${PORT}! Browser-Harness may already be running."
    exit 0
elif command -v lsof >/dev/null 2>&1 && lsof -i :${PORT} >/dev/null 2>&1; then
    log_warn "A process is already active on port ${PORT}! Browser-Harness may already be running."
    exit 0
fi

log_info "Starting Browser-Harness (Google Chrome inside Xvfb) on CDP port ${PORT}..."
mkdir -p "${CHROME_PROFILE}"

# Execute Chrome under Xvfb inside a headless screen/virtual display session
nohup xvfb-run --server-args="-screen 0 1920x1080x24" \
  google-chrome \
  --remote-debugging-port=${PORT} \
  --no-sandbox \
  --disable-setuid-sandbox \
  --user-data-dir="${CHROME_PROFILE}" \
  --disable-dev-shm-usage \
  --disable-gpu \
  --no-first-run \
  --no-default-browser-check > /tmp/chrome_harness.log 2>&1 &

CHROME_PID=$!

# Quick health check validation on CDP port
log_info "Waiting for Browser-Harness CDP to initialize..."
HEALTHY=false
for i in {1..10}; do
    sleep 1
    if curl -s "http://127.0.0.1:${PORT}/json/version" >/dev/null 2>&1; then
        HEALTHY=true
        break
    fi
    log_info "Initializing Browser-Harness... ($i/10)"
done

if [ "$HEALTHY" = true ]; then
    log_success "BROWSER-HARNESS STARTED SUCCESSFULLY ON PORT ${PORT} (PID: ${CHROME_PID})!"
    log_info "Log files are available at: /tmp/chrome_harness.log"
else
    log_error "Failed to start Browser-Harness cleanly. Check logs in: /tmp/chrome_harness.log"
    exit 1
fi
