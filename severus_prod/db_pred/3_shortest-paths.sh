#!/bin/bash
set -Eeuo pipefail

EMAIL="${EMAIL:-sat362@pitt.edu}"

fail() {
    local msg="${1:-Unknown error}"
    trap - ERR
    printf '[ERROR] %s\n' "$msg" >&2
    if [[ ${UPDATE_EMAIL_NOTICES:-1} == 1 ]] && command -v sendmail >/dev/null 2>&1; then
        if ! sendmail "$EMAIL" <<EOF
Subject: Shortest paths update FAILED for ${PRODUCTION_DB:-not selected} on $(hostname)
From: noreply@dbmi.pitt.edu
To: $EMAIL

The shortest paths update failed.
Error: $msg
Check logs and rerun.
EOF
        then
            echo "[WARNING] Could not send failure notification" >&2
        fi
    fi
    exit 1
}

error() { fail "${1:-Script error}"; }
trap 'fail "Line $LINENO failed with status $?. See the preceding output."' ERR

shortest_workflow() {
ROOT_DIR="${HIPPIP_ROOT:-/data/Projects/Hippip}"
SCRIPTS_DIR="$ROOT_DIR/scripts"
SP_SCRIPT="$SCRIPTS_DIR/shortest_paths/update_db.py"

if [[ ${1:-} == --help || ${1:-} == -h ]]; then
    echo "Usage: $(basename "$0")"
    echo "Rebuild shortest_paths in the selected database. Configure PRODUCTION_DB, DB_USER and DB_PASS or answer the prompts."
    echo "Options: --workers N, --batch-size N, --restart. Default: 6 workers, 5000 paths per transaction; rerun to resume."
    exit 0
fi
if (( $# )); then
    shortest_validate_arguments "$@"
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
if [[ -z $PRODUCTION_DB || -z $DB_USER ]]; then
    error "Database name and username are required"
fi
echo "Selected database: $PRODUCTION_DB"

# Retained legacy access check; the helper uses the configured host/socket and DB_PASS.
# mysql -u "$DB_USER" -p"$DB_PASS" -D "$PRODUCTION_DB" -e ";" >/dev/null 2>&1 || error "Unable to access database $PRODUCTION_DB"
shortest_check_access

echo "Updating shortest paths... "
# Retained legacy command; truncating here would erase resumable progress.
# mysql -u "$DB_USER" -p"$DB_PASS" -D "$PRODUCTION_DB" -e "TRUNCATE \`shortest_paths\`;" >/dev/null 2>&1 || error "Failed to truncate table shortest_paths"
# Retained legacy invocation and message; the password now comes from DB_PASS.
# "$SP_SCRIPT" -d "$PRODUCTION_DB" -u "$DB_USER" -p "$DB_PASS" || error "Failed to update shortest paths"
export PRODUCTION_DB DB_USER DB_PASS
trap 'unset DB_PASS' EXIT
"$SP_SCRIPT" -d "$PRODUCTION_DB" -u "$DB_USER" "$@" || error "Failed to update shortest paths"
echo "[DONE]"
echo "Updated shortest paths in $PRODUCTION_DB"

if [[ ${UPDATE_EMAIL_NOTICES:-1} == 1 ]] && command -v sendmail >/dev/null 2>&1; then
    if ! sendmail "$EMAIL" <<EOF
Subject: Shortest Path Data Pushed to $PRODUCTION_DB
From: noreply@dbmi.pitt.edu
To: $EMAIL

The shortest paths data has been successfully rebuilt in $PRODUCTION_DB.
EOF
    then
        echo "[WARNING] Could not send success notification" >&2
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
