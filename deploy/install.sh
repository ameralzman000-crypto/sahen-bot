#!/bin/bash
set -euo pipefail

APP_DIR="${APP_DIR:-/home/ubuntu/aliasbot}"
SERVICE_NAME="${SERVICE_NAME:-aliasbot}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

echo "Installing Alias Telegram Bot into ${APP_DIR}"

export DEBIAN_FRONTEND=noninteractive
if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update
    sudo apt-get install -y python3 python3-venv python3-pip
fi

mkdir -p "${APP_DIR}/data"

if [ ! -f "${APP_DIR}/bot.py" ]; then
    echo "bot.py was not found in ${APP_DIR}"
    echo "Copy the project files into ${APP_DIR} first, then run this script again."
    exit 1
fi

if [ ! -d "${APP_DIR}/.venv" ]; then
    "${PYTHON_BIN}" -m venv "${APP_DIR}/.venv"
fi

"${APP_DIR}/.venv/bin/pip" install --upgrade pip
if [ -f "${APP_DIR}/requirements-prod.txt" ]; then
    "${APP_DIR}/.venv/bin/pip" install -r "${APP_DIR}/requirements-prod.txt"
else
    "${APP_DIR}/.venv/bin/pip" install -r "${APP_DIR}/requirements.txt"
fi

if [ ! -f "${APP_DIR}/.env" ]; then
    if [ -f "${APP_DIR}/.env.example" ]; then
        cp "${APP_DIR}/.env.example" "${APP_DIR}/.env"
    else
        printf "BOT_TOKEN=\nADMIN_ID=1441524960\nDB_PATH=%s/data/alias_group.db\n" "${APP_DIR}" > "${APP_DIR}/.env"
    fi
    echo "Created ${APP_DIR}/.env"
    echo "Edit that file and put BOT_TOKEN before starting the service."
fi

if grep -q "put-your-bot-token-here" "${APP_DIR}/.env"; then
    echo "BOT_TOKEN is still a placeholder. Edit ${APP_DIR}/.env then run:"
    echo "sudo systemctl enable --now ${SERVICE_NAME}"
    exit 0
fi

SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
sudo tee "${SERVICE_FILE}" >/dev/null <<EOF
[Unit]
Description=Alias Telegram Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$(id -un)
Group=$(id -gn)
WorkingDirectory=${APP_DIR}
EnvironmentFile=${APP_DIR}/.env
ExecStart=${APP_DIR}/.venv/bin/python3 ${APP_DIR}/bot.py
Restart=always
RestartSec=5
KillSignal=SIGINT
TimeoutStopSec=20

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now "${SERVICE_NAME}"
sudo systemctl --no-pager --full status "${SERVICE_NAME}" || true

echo "Bot service installed."
echo "Logs: journalctl -u ${SERVICE_NAME} -f"
