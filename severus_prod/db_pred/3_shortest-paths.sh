#!/bin/bash
set -Eeuo pipefail

fail() {
  local msg="${1:-Unknown error}"
  if [[ -t 1 ]]; then echo "[$(tput setaf 1)ERROR$(tput sgr0)]"; else echo "[ERROR]"; fi
  echo "$msg" >&2
  sendmail "$EMAIL" <<EOF
Subject: Shortest Paths Update FAILED for $PRODUCTION_DB on $(hostname)
From: noreply@dbmi.pitt.edu
To: $EMAIL

The shortest paths update script failed.
Error: $msg
Check logs and rerun.
EOF
  exit 1
}
error(){ fail "${1:-Script error}"; }
trap 'fail "Line $LINENO: `$BASH_COMMAND` exited with status $?"' ERR

EMAIL="${EMAIL:-sat362@pitt.edu}"

ROOT_DIR="/data/Projects/Hippip"
SCRIPTS_DIR="$ROOT_DIR/scripts"
SP_SCRIPT="$SCRIPTS_DIR/shortest_paths/update_db.py"

read -p "MySQL Database: " PRODUCTION_DB
read -p "MySQL Username: " DB_USER
read -s -p "MySQL Password: " DB_PASS
echo

mysql -u "$DB_USER" -p"$DB_PASS" -D "$PRODUCTION_DB" -e ";" >/dev/null 2>&1 || error "Unable to access database $PRODUCTION_DB"

echo "Updating shortest paths... "
mysql -u "$DB_USER" -p"$DB_PASS" -D "$PRODUCTION_DB" -e "TRUNCATE \`shortest_paths\`;" >/dev/null 2>&1 || error "Failed to truncate table shortest_paths"
"$SP_SCRIPT" -d "$PRODUCTION_DB" -u "$DB_USER" -p "$DB_PASS" || error "Failed to update shortest path"
echo "[DONE]"
echo "Updated shortest path"

sendmail "$EMAIL" <<EOF
Subject: Shortest Path Data Pushed to $PRODUCTION_DB
From: noreply@dbmi.pitt.edu
To: $EMAIL

Dear Team,

The shortest path data has been successfully pushed to the $PRODUCTION_DB database. All processes for this operation have been completed.

Best regards,
Your Hippip Script
EOF
