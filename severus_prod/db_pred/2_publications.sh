#!/bin/bash

set -Eeuo pipefail
umask 077

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
WORKFLOW_ROOT=$(cd -- "$SCRIPT_DIR/.." && pwd)
PUBLICATION_SCRIPT="${PUBLICATION_SCRIPT:-/data/Projects/Hippip/scripts/publication}"
PYTHON="${PYTHON:-/usr/bin/python3}"
EMAIL="${EMAIL:-sat362@pitt.edu}"
export NCBI_EMAIL="${NCBI_EMAIL:-$EMAIL}"
export NCBI_API_KEY_FILE="${NCBI_API_KEY_FILE:-$WORKFLOW_ROOT/.ncbi_api_key}"
export PUBLICATION_STATE_DIR="${PUBLICATION_STATE_DIR:-$WORKFLOW_ROOT/publication_state}"

if [[ ${1:-} == --help || ${1:-} == -h ]]; then
  exec "$PYTHON" "$PUBLICATION_SCRIPT/update.py" --help
fi

if [[ -z ${PRODUCTION_DB:-} ]]; then
  read -r -p "MySQL Database [db_pred]: " PRODUCTION_DB
  PRODUCTION_DB="${PRODUCTION_DB:-db_pred}"
fi
if [[ -z ${DB_USER:-} ]]; then
  read -r -p "MySQL Username: " DB_USER
fi
if [[ ! -v DB_PASS ]]; then
  read -r -s -p "MySQL Password: " DB_PASS
  echo
fi
export PRODUCTION_DB DB_USER DB_PASS

# Keep logs with the selected workflow even when checkpoints are shared.
PUBLICATION_LOG_DIR="${PUBLICATION_LOG_DIR:-$SCRIPT_DIR/publication_state/logs}"
mkdir -p -- "$PUBLICATION_LOG_DIR"
LOG_FILE=$(mktemp "$PUBLICATION_LOG_DIR/publications-$(date +%Y%m%d-%H%M%S)-XXXXXX.log")

send_notice() {
  local outcome="$1"
  local detail="$2"
  if [[ ${PUBLICATION_EMAIL_NOTICES:-1} != 1 ]]; then return; fi
  if ! command -v sendmail >/dev/null 2>&1; then
    echo "[WARNING] sendmail is unavailable; update status is in $LOG_FILE" >&2
    return
  fi
  if ! sendmail "$EMAIL" <<EOF
Subject: Publication Update $outcome for $PRODUCTION_DB on $(hostname)
From: noreply@dbmi.pitt.edu
To: $EMAIL

$detail
Log: $LOG_FILE
EOF
  then
    echo "[WARNING] Could not send $outcome notification; update status is in $LOG_FILE" >&2
  fi
}

trap 'unset DB_PASS' EXIT
echo "Publication update log: $LOG_FILE"
# Keep the Python exit status even when tee succeeds. Neither secret is passed
# on the command line. Retry and checkpoint handling belong to the runner.
set +e
"$PYTHON" -u "$PUBLICATION_SCRIPT/update.py" "$@" 2>&1 | tee "$LOG_FILE"
pipeline_status=("${PIPESTATUS[@]}")
set -e
status=${pipeline_status[0]}
if (( pipeline_status[1] != 0 && status == 0 )); then status=1; fi

if (( status == 0 )); then
  if [[ " $* " == *" --check-config "* ]]; then
    echo "Publication configuration check succeeded."
  else
    send_notice SUCCESS "Publication workflow completed at $(date). Review the log for warnings and any PMIDs reported unavailable by NCBI."
  fi
elif (( status == 75 )); then
  send_notice POSTPONED "The 9 PM–5 AM Eastern window closed. Committed progress is saved. Run this command again to resume; this launch has exited."
else
  send_notice FAILED "Publication update exited with status $status at $(date). Committed batches are saved; inspect the log and rerun to resume."
fi
exit "$status"
