#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

"$PROJECT_ROOT/.venv/bin/tictoc-factory" cycle --project-root "$PROJECT_ROOT"
"$PROJECT_ROOT/.venv/bin/tictoc-factory" publish-due --project-root "$PROJECT_ROOT"

# ── Telegram Delivery ──────────────────────────────────────────────────────────
# Sends every newly rendered video to a Telegram chat (e.g. your iPhone).
# Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID as env vars or in a .env file.
DELIVERED_LOG="$PROJECT_ROOT/data/analytics/telegram_delivered.txt"
ENV_FILE="$PROJECT_ROOT/.env"

# Load .env if present
if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  set -a; source "$ENV_FILE"; set +a
fi

if [[ -z "${TELEGRAM_BOT_TOKEN:-}" || -z "${TELEGRAM_CHAT_ID:-}" ]]; then
  echo "[telegram] TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set — skipping delivery"
  exit 0
fi

touch "$DELIVERED_LOG"

for VIDEO in "$PROJECT_ROOT/data/output/videos/"*.mp4; do
  [[ -f "$VIDEO" ]] || continue
  BASENAME="$(basename "$VIDEO")"
  if grep -qxF "$BASENAME" "$DELIVERED_LOG"; then
    continue  # already sent
  fi

  SEND_FILE="$VIDEO"
  FILE_SIZE=$(stat -c%s "$VIDEO" 2>/dev/null || stat -f%z "$VIDEO")
  TG_LIMIT=$((48 * 1024 * 1024))  # 48 MB

  # Compress to under 48 MB if needed (Telegram bot API limit)
  if [[ "$FILE_SIZE" -gt "$TG_LIMIT" ]]; then
    echo "[telegram] Compressing $BASENAME for delivery …"
    COMPRESSED="/tmp/tg_compressed_${BASENAME}"
    # Calculate target bitrate: 48MB * 8 bits / duration in seconds
    DURATION=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$VIDEO" 2>/dev/null || echo 60)
    TARGET_KBITS=$(( (48 * 8 * 1024) / ${DURATION%.*} ))
    AUDIO_KBITS=128
    VIDEO_KBITS=$(( TARGET_KBITS - AUDIO_KBITS - 50 ))
    ffmpeg -y -i "$VIDEO" -c:v libx264 -b:v "${VIDEO_KBITS}k" -c:a aac -b:a "${AUDIO_KBITS}k" \
      -vf "scale=720:1280" -movflags +faststart "$COMPRESSED" -loglevel error
    SEND_FILE="$COMPRESSED"
  fi

  echo "[telegram] Sending $BASENAME …"
  HTTP_CODE=$(curl -s -o /tmp/tg_response.json -w "%{http_code}" \
    -F "chat_id=${TELEGRAM_CHAT_ID}" \
    -F "video=@${SEND_FILE}" \
    -F "caption=🎬 Neues TikTok bereit zum Posten!%0A${BASENAME}" \
    "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendVideo")

  # Clean up compressed temp file
  [[ "$SEND_FILE" != "$VIDEO" ]] && rm -f "$SEND_FILE"

  if [[ "$HTTP_CODE" == "200" ]]; then
    echo "$BASENAME" >> "$DELIVERED_LOG"
    echo "[telegram] ✅ Delivered: $BASENAME"
  else
    echo "[telegram] ❌ Failed (HTTP $HTTP_CODE): $(cat /tmp/tg_response.json)"
  fi
done
