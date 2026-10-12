#!/bin/bash
set -Eeuo pipefail

fail() {
  local msg="${1:-Unknown error}"
  trap - ERR
  if [[ -t 1 ]]; then echo "[$(tput setaf 1)ERROR$(tput sgr0)]"; else echo "[ERROR]"; fi
  echo "$msg" >&2
  if [[ ${UPDATE_EMAIL_NOTICES:-1} == 1 ]] && command -v sendmail >/dev/null 2>&1; then
if ! sendmail "$EMAIL" <<EOF
Subject: Shortest Paths Update FAILED for ${PRODUCTION_DB:-not selected} on $(hostname)
From: noreply@dbmi.pitt.edu
To: $EMAIL

The shortest paths update script failed.
Error: $msg
Check logs and rerun.
EOF
then
    echo "[WARNING] Could not send shortest-path notification" >&2
fi
fi
  exit 1
}
error(){ fail "${1:-Script error}"; }
# Retained legacy trap:
# trap 'fail "Line $LINENO: `$BASH_COMMAND` exited with status $?"' ERR
trap 'fail "Line $LINENO failed with status $?. See the preceding output."' ERR

EMAIL="${EMAIL:-sat362@pitt.edu}"

shortest_workflow() {
ROOT_DIR="/data/Projects/Hippip"
SCRIPTS_DIR="$ROOT_DIR/scripts"
SP_SCRIPT="$SCRIPTS_DIR/shortest_paths/update_db.py"

if [[ ${1:-} == --help || ${1:-} == -h ]]; then
    echo "Usage: $(basename "$0") [--workers N] [--batch-size N] [--restart]"
    echo "Rebuild shortest_paths in the selected database. Configure PRODUCTION_DB, DB_USER and DB_PASS or answer the prompts."
    echo "Default: 6 workers, 5000 paths per transaction; rerun to resume."
    exit 0
fi
if (( $# )); then
    shortest_validate_arguments "$@"
fi

read -p "MySQL Database: " PRODUCTION_DB
read -p "MySQL Username: " DB_USER
read -s -p "MySQL Password: " DB_PASS
echo

# Retained legacy access check; the helper uses the configured host/socket and DB_PASS.
# mysql -u "$DB_USER" -p"$DB_PASS" -D "$PRODUCTION_DB" -e ";" >/dev/null 2>&1 || error "Unable to access database $PRODUCTION_DB"
shortest_check_access

echo "Updating shortest paths... "
# Retained legacy command; truncating here would erase resumable progress.
# mysql -u "$DB_USER" -p"$DB_PASS" -D "$PRODUCTION_DB" -e "TRUNCATE \`shortest_paths\`;" >/dev/null 2>&1 || error "Failed to truncate table shortest_paths"
# Retained legacy invocation and message; the password now comes from DB_PASS.
# "$SP_SCRIPT" -d "$PRODUCTION_DB" -u "$DB_USER" -p "$DB_PASS" || error "Failed to update shortest path"
export PRODUCTION_DB DB_USER DB_PASS
trap 'unset DB_PASS' EXIT
"$SP_SCRIPT" -d "$PRODUCTION_DB" -u "$DB_USER" "$@" || error "Failed to update shortest path"
echo "[DONE]"
echo "Updated shortest path"

if [[ ${UPDATE_EMAIL_NOTICES:-1} == 1 ]] && command -v sendmail >/dev/null 2>&1; then
if ! sendmail "$EMAIL" <<EOF
Subject: Shortest Path Data Pushed to $PRODUCTION_DB
From: noreply@dbmi.pitt.edu
To: $EMAIL

Dear Team,

The shortest path data has been successfully pushed to the $PRODUCTION_DB database. All processes for this operation have been completed.

Best regards,
Your Hippip Script
EOF
then
    echo "[WARNING] Could not send shortest-path notification" >&2
fi
fi
}

# Added launch helpers. The Python runner owns staged writes and database checkpoints.
shortest_validate_arguments() {
    while (( $# )); do
        case "$1" in
            --restart) shift ;;
            -w|--workers|--batch-size)
                if (( $# < 2 )); then error "Missing value for $1"; fi
                shift 2 ;;
            --workers=*|--batch-size=*) shift ;;
            *) error "Unexpected arguments; use --help for usage" ;;
        esac
    done
}

shortest_check_access() {
    local mysql_args=(-u "$DB_USER" -D "$PRODUCTION_DB")
    if [[ -n ${DB_SOCKET:-} ]]; then
        mysql_args+=(--protocol SOCKET --socket "$DB_SOCKET")
    else
        mysql_args+=(--host "${DB_HOST:-localhost}" --port "${DB_PORT:-3306}")
    fi
    MYSQL_PWD="$DB_PASS" mysql "${mysql_args[@]}" -e ";" >/dev/null 2>&1 || error "Unable to access database $PRODUCTION_DB"
}

shortest_workflow "$@"
