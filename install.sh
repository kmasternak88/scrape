#!/usr/bin/env bash

# ==============================================================================
# NEXUS SCRAPER - UNIFIED LINUX INSTALLATION & DEPLOYMENT SCRIPT
# Optimized for standard Linux environments and Google AI Studio Apps
# ==============================================================================

set -eo pipefail

# --- Color Codes for Beautiful Logging ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${BLUE}[INFO] $(date '+%Y-%m-%d %H:%M:%S') - $1${NC}"
}

log_success() {
    echo -e "${GREEN}[SUCCESS] $(date '+%Y-%m-%d %H:%M:%S') - $1${NC}"
}

log_warn() {
    echo -e "${YELLOW}[WARNING] $(date '+%Y-%m-%d %H:%M:%S') - $1${NC}"
}

log_error() {
    echo -e "${RED}[ERROR] $(date '+%Y-%m-%d %H:%M:%S') - $1${NC}"
}

# --- Default Configurations ---
INSTALL_DIR="${INSTALL_DIR:-$HOME/nexus-scraper}"
REPO_URL="${REPO_URL:-https://github.com/PanPodloga/nexus-scraper.git}" # Placeholder / editable
PORT="${PORT:-8000}"
HOST="${HOST:-0.0.0.0}"

echo -e "${GREEN}"
echo "=================================================================="
echo "    _   _                      ____                               "
echo "   | \ | | ___  _   _ _   _ ___/ ___|  ___ _ __ __ _ _ __   ___ _ __ "
echo "   |  \| |/ _ \| | | | | | / __\___ \ / __| '__/ _\` | '_ \ / _ \ '__|"
echo "   | |\  |  __/| |_| | |_| \__ \___) | (__| | | (_| | |_) |  __/ |   "
echo "   |_| \_|\___| \__,_|\__,_|___/____/ \___|_|  \__,_| .__/ \___|_|   "
echo "                                                    |_|           "
echo "        UNIFIED AUTOMATIC INSTALLER FOR GOOGLE AI STUDIO / APPS   "
echo "=================================================================="
echo -e "${NC}"

# --- Check privileges ---
SUDO=""
if [ "$EUID" -ne 0 ]; then
    if command -v sudo >/dev/null 2>&1; then
        SUDO="sudo"
        log_info "Running with non-root privileges. Will use 'sudo' for package installation."
    else
        log_warn "Running as non-root and 'sudo' is not installed. Package installation might fail."
    fi
fi

# --- 1. System Package Update and Prerequisites ---
log_info "Updating system package repositories..."
if [ -n "$SUDO" ] || [ "$EUID" -eq 0 ]; then
    $SUDO apt-get update -y
    $SUDO apt-get install -y git curl build-essential libssl-dev zlib1g-dev \
        libbz2-dev libreadline-dev libsqlite3-dev wget llvm libncurses5-dev \
        libncursesw5-dev xz-utils tk-dev libffi-dev liblzma-dev libsqlite3-0
else
    log_warn "Skipping system package updates due to insufficient privileges."
fi

# --- 2. Check and Install Python 3.11+ ---
PYTHON_CMD="python3"
INSTALL_PYTHON=false

if command -v python3 >/dev/null 2>&1; then
    PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    log_info "Found Python version: $PYTHON_VERSION"
    
    # Check if Python is >= 3.11
    MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
    MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)
    
    if [ "$MAJOR" -lt 3 ] || { [ "$MAJOR" -eq 3 ] && [ "$MINOR" -lt 11 ]; }; then
        log_warn "Python version $PYTHON_VERSION is lower than 3.11. Python 3.11+ is required."
        INSTALL_PYTHON=true
    fi
else
    log_warn "Python3 is not installed."
    INSTALL_PYTHON=true
fi

if [ "$INSTALL_PYTHON" = true ]; then
    log_info "Installing Python 3.11 & virtual environment packages..."
    if [ -n "$SUDO" ] || [ "$EUID" -eq 0 ]; then
        $SUDO apt-get install -y software-properties-common
        $SUDO add-apt-repository ppa:deadsnakes/ppa -y
        $SUDO apt-get update -y
        $SUDO apt-get install -y python3.11 python3.11-venv python3.11-dev python3-pip
        PYTHON_CMD="python3.11"
        log_success "Python 3.11 installed successfully."
    else
        log_error "Cannot install Python 3.11 without root/sudo privileges. Please install it manually and run the script again."
        exit 1
    fi
fi

# Ensure python3-venv is present even if Python was already installed
if [ -n "$SUDO" ] || [ "$EUID" -eq 0 ]; then
    log_info "Ensuring python3-venv is present..."
    $SUDO apt-get install -y python3-venv python3-pip || true
fi

# --- 3. Downloading / Deploying Source Code ---
if [ -d "$INSTALL_DIR" ]; then
    log_warn "Destination directory '$INSTALL_DIR' already exists."
    # If we are already running inside the project folder, we don't need to clone/download
    if [ -f "./pyproject.toml" ] && [ -d "./nexus" ]; then
        log_info "Detected that script is executed directly inside the source tree. Copying files..."
        INSTALL_DIR=$(pwd)
    else
        log_info "Backing up old installation to ${INSTALL_DIR}_backup..."
        rm -rf "${INSTALL_DIR}_backup"
        mv "$INSTALL_DIR" "${INSTALL_DIR}_backup"
        log_info "Cloning source code from repository..."
        git clone "$REPO_URL" "$INSTALL_DIR"
    fi
else
    # If there is a local workspace we can copy from, we use it as fallback
    if [ -f "./pyproject.toml" ] && [ -d "./nexus" ]; then
        log_info "Copying local workspace files to '$INSTALL_DIR'..."
        mkdir -p "$INSTALL_DIR"
        cp -r ./* "$INSTALL_DIR/"
    else
        log_info "Cloning source code from repository into '$INSTALL_DIR'..."
        git clone "$REPO_URL" "$INSTALL_DIR"
    fi
fi

cd "$INSTALL_DIR"

# --- 4. Python Virtual Environment Setup ---
log_info "Creating Python virtual environment in '$INSTALL_DIR/.venv'..."
$PYTHON_CMD -m venv .venv
source .venv/bin/activate

log_info "Upgrading pip and installing wheel..."
pip install --upgrade pip setuptools wheel

log_info "Installing dependencies from pyproject.toml / requirements.txt..."
if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt
elif [ -f "pyproject.toml" ]; then
    pip install .
else
    log_error "No requirements.txt or pyproject.toml found in '$INSTALL_DIR'!"
    exit 1
fi
log_success "Dependencies installed successfully."

# --- 5. Playwright & System Dependencies Configuration ---
log_info "Installing Playwright core and browser binaries..."
playwright install chromium

log_info "Installing Playwright system library dependencies..."
if [ -n "$SUDO" ] || [ "$EUID" -eq 0 ]; then
    $SUDO playwright install-deps chromium
else
    log_warn "Skipping 'playwright install-deps' because of non-root privileges. If Playwright fails to launch, run: 'sudo npx playwright install-deps' manually."
fi
log_success "Playwright browser binaries and dependencies installed."

# --- 6. Environmental Configuration (.env) ---
log_info "Configuring environmental variables..."
if [ ! -f ".env" ]; then
    # Generate a secure 32-character master API key
    SECURE_API_KEY=$(head -c 32 /dev/urandom | base64 | tr -dc 'a-zA-Z0-9' | head -c 32)
    cat <<EOF > .env
# --- Nexus Scraper Environment Variables ---
ENV=production
HOST=${HOST}
PORT=${PORT}
API_KEY=${SECURE_API_KEY}
DB_PATH=sqlite+aiosqlite:///nexus.db
REDIS_URL=
DEFAULT_TIMEOUT=30000
MAX_CONCURRENT_BROWSERS=2
EOF
    log_success "Generated new '.env' configuration with secure API_KEY."
else
    log_warn "An existing '.env' file was found. Preserving your configurations."
fi

# Load active config to show to the user
source .env 2>/dev/null || true

# --- 7. Smoke Test / Verification Loop (Given-When-Then Verification) ---
log_info "Running Smoke Test to verify API boot and core health..."

# Start uvicorn server in the background
export ENV=test
export API_KEY="smoke_test_key_$(date +%s)"
export DB_PATH="sqlite+aiosqlite:///:memory:"

log_info "Starting temporary FastAPI instance in background..."
.venv/bin/uvicorn nexus.main:app --host 127.0.0.1 --port 9099 > uvicorn_smoke.log 2>&1 &
UVICORN_PID=$!

cleanup_verification() {
    log_info "Cleaning up smoke test processes..."
    kill $UVICORN_PID 2>/dev/null || true
    wait $UVICORN_PID 2>/dev/null || true
    rm -f uvicorn_smoke.log
}

# Ensure background server is killed on exit
trap cleanup_verification EXIT

# Wait and poll healthcheck endpoint
log_info "Polling healthcheck endpoint at http://127.0.0.1:9099/health..."
HEALTHY=false
for i in {1..15}; do
    sleep 1
    if curl -s http://127.0.0.1:9099/health > response.json 2>/dev/null; then
        STATUS=$(grep -o '"status":"[^"]*' response.json | cut -d'"' -f4 || true)
        log_info "Response received: status is '$STATUS'"
        if [ "$STATUS" = "healthy" ] || [ "$STATUS" = "degraded" ] || [ "$STATUS" = "ok" ]; then
            HEALTHY=true
            break
        fi
    fi
    log_info "Uvicorn is booting, retrying... ($i/15)"
done

rm -f response.json

if [ "$HEALTHY" = true ]; then
    log_success "SMOKE TEST PASSED! The API successfully booted and responded to /health check."
else
    log_error "SMOKE TEST FAILED! See logs below:"
    cat uvicorn_smoke.log
    exit 1
fi

cleanup_verification
trap - EXIT

# --- 8. Final Setup Instructions and Success Banner ---
log_success "NEXUS SCRAPER AUTOMATIC INSTALLATION COMPLETED SUCCESSFULLY!"
echo -e "${GREEN}"
echo "=================================================================="
echo "                   INSTALLATION COMPLETE!                        "
echo "=================================================================="
echo -e "${NC}"
echo -e "Your API is installed in: ${YELLOW}${INSTALL_DIR}${NC}"
echo -e "Python Environment:       ${YELLOW}Active (Python 3.11+)${NC}"
echo -e "Master API Key:           ${RED}${API_KEY}${NC}"
echo -e "Run Command (Manual):     ${BLUE}cd ${INSTALL_DIR} && .venv/bin/uvicorn nexus.main:app --host ${HOST} --port ${PORT}${NC}"
echo ""
echo -e "${YELLOW}To run as a persistent Systemd Service daemon on Linux, execute:${NC}"
echo -e "1. Create file: sudo nano /etc/systemd/system/nexus-scraper.service"
echo -e "2. Paste the following configuration:"
echo -e "------------------------------------------------------------------"
echo -e "[Unit]"
echo -e "Description=Nexus Scraper API Service"
echo -e "After=network.target"
echo -e ""
echo -e "[Service]"
echo -e "User=$USER"
echo -e "WorkingDirectory=${INSTALL_DIR}"
echo -e "ExecStart=${INSTALL_DIR}/.venv/bin/uvicorn nexus.main:app --host ${HOST} --port ${PORT}"
echo -e "Restart=always"
echo -e "Environment=PATH=${INSTALL_DIR}/.venv/bin:/usr/bin:/bin"
echo -e ""
echo -e "[Install]"
echo -e "WantedBy=multi-user.target"
echo -e "------------------------------------------------------------------"
echo -e "3. Load and start the service:"
echo -e "   ${BLUE}sudo systemctl daemon-reload${NC}"
echo -e "   ${BLUE}sudo systemctl enable nexus-scraper.service${NC}"
echo -e "   ${BLUE}sudo systemctl start nexus-scraper.service${NC}"
echo ""
echo "=================================================================="
