#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-$HOME/bhaforge-ocr}"

mkdir -p "$APP_DIR"
rsync -av --delete ./ "$APP_DIR"/
cd "$APP_DIR"

python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo "Deployed to $APP_DIR"
echo "Next:"
echo "  sudo cp bhaforge-ocr.service /etc/systemd/system/"
echo "  sudo systemctl daemon-reload"
echo "  sudo systemctl enable --now bhaforge-ocr"
