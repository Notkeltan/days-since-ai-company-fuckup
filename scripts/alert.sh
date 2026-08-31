#!/usr/bin/env bash
# Push an alert to keltan's phone via Pushover.
#
#   scripts/alert.sh "title" "message" [priority] [url]
#
# Silent no-op when the secrets are absent, so a fork or a local run does not
# fail for want of a Pushover account. Never fails its caller: an alert that
# breaks the workflow it was meant to report on is worse than no alert.
set -uo pipefail

TITLE="${1:?title required}"
MESSAGE="${2:?message required}"
PRIORITY="${3:-1}"          # -2 quiet .. 1 high (bypasses quiet hours)
URL="${4:-}"

if [ -z "${PUSHOVER_TOKEN:-}" ] || [ -z "${PUSHOVER_USER:-}" ]; then
  echo "[alert] Pushover not configured; would have sent: $TITLE - $MESSAGE"
  exit 0
fi

# A sound nothing else on the phone uses is the whole point - override with the
# PUSHOVER_SOUND repo variable.
SOUND="${PUSHOVER_SOUND:-siren}"

code=$(curl -s -o /tmp/pushover.out -w "%{http_code}" \
  --form-string "token=${PUSHOVER_TOKEN}" \
  --form-string "user=${PUSHOVER_USER}" \
  --form-string "title=${TITLE}" \
  --form-string "message=${MESSAGE}" \
  --form-string "priority=${PRIORITY}" \
  --form-string "sound=${SOUND}" \
  ${URL:+--form-string "url=${URL}"} \
  ${URL:+--form-string "url_title=Open the run"} \
  https://api.pushover.net/1/messages.json) || true

if [ "$code" = "200" ]; then
  echo "[alert] sent: $TITLE"
else
  echo "[alert] Pushover returned $code: $(cat /tmp/pushover.out 2>/dev/null)"
fi
exit 0
