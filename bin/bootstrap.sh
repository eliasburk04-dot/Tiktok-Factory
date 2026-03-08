#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${1:-/opt/tictoc-factory}"
PROJECT_USER="${2:-${SUDO_USER:-$(id -un)}}"

export DEBIAN_FRONTEND=noninteractive

sudo mkdir -p "$PROJECT_ROOT"
sudo chown -R "$PROJECT_USER:$PROJECT_USER" "$PROJECT_ROOT"

sudo apt-get update
sudo apt-get install -y --no-install-recommends \
  espeak-ng \
  ffmpeg \
  fonts-dejavu-core \
  jq \
  python3 \
  python3-pip \
  python3-venv

mkdir -p \
  "$PROJECT_ROOT/src" \
  "$PROJECT_ROOT/configs" \
  "$PROJECT_ROOT/data/input/gameplay" \
  "$PROJECT_ROOT/data/input/gameplay_longform" \
  "$PROJECT_ROOT/data/input/longform/podcasts_streams" \
  "$PROJECT_ROOT/data/work" \
  "$PROJECT_ROOT/data/output/videos" \
  "$PROJECT_ROOT/data/output/audio" \
  "$PROJECT_ROOT/data/output/subtitles" \
  "$PROJECT_ROOT/data/output/scripts" \
  "$PROJECT_ROOT/data/analytics" \
  "$PROJECT_ROOT/data/queue/jobs" \
  "$PROJECT_ROOT/logs" \
  "$PROJECT_ROOT/bin" \
  "$PROJECT_ROOT/tests"

if [[ ! -d "$PROJECT_ROOT/.venv" ]]; then
  python3 -m venv "$PROJECT_ROOT/.venv"
fi

"$PROJECT_ROOT/.venv/bin/pip" install --upgrade pip setuptools wheel
"$PROJECT_ROOT/.venv/bin/pip" install -e "$PROJECT_ROOT[dev]"

if [[ ! -f "$PROJECT_ROOT/configs/factory.local.yaml" ]]; then
  cp "$PROJECT_ROOT/configs/factory.example.yaml" "$PROJECT_ROOT/configs/factory.local.yaml"
fi

if [[ ! -f "$PROJECT_ROOT/configs/accounts.local.yaml" ]]; then
  cp "$PROJECT_ROOT/configs/accounts.example.yaml" "$PROJECT_ROOT/configs/accounts.local.yaml"
fi

if [[ ! -f "$PROJECT_ROOT/configs/.env" ]]; then
  cp "$PROJECT_ROOT/configs/.env.example" "$PROJECT_ROOT/configs/.env"
fi

chmod +x "$PROJECT_ROOT/bin/"*.sh

sudo install -m 0644 "$PROJECT_ROOT/systemd/tictoc-factory.service" /etc/systemd/system/tictoc-factory.service
sudo install -m 0644 "$PROJECT_ROOT/systemd/tictoc-factory.timer" /etc/systemd/system/tictoc-factory.timer
sudo systemctl daemon-reload

echo "Bootstrap complete for $PROJECT_ROOT"
