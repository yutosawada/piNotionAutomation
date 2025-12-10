#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CONFIG_FILE="${REPO_ROOT}/schedule_config.yml"

if [[ ! -f "${CONFIG_FILE}" ]]; then
  echo "Error: ${CONFIG_FILE} not found" >&2
  exit 1
fi

mapfile -t SCHEDULE_ENTRIES < <(
  awk '
  function emit() {
    if (script != "" && command != "" && interval != "")
      print script "|" command "|" interval
  }
  { sub(/\r$/, "") }
  /^scripts:/ { in_scripts=1; next }
  in_scripts != 1 { next }
  /^[[:space:]]*#/ { next }
  /^  [A-Za-z0-9_-]+:/ {
    emit()
    script=$0
    sub(/^  /, "", script)
    sub(/:.*/, "", script)
    command=""
    interval=""
    next
  }
  /^    command:/ {
    cmd=$0
    sub(/^    command:[[:space:]]*/, "", cmd)
    sub(/[[:space:]]+#.*/, "", cmd)
    command=cmd
    next
  }
  /^    interval_minutes:/ {
    val=$0
    sub(/^    interval_minutes:[[:space:]]*/, "", val)
    sub(/[[:space:]]+#.*/, "", val)
    interval=val
    next
  }
  END { emit() }
  ' "${CONFIG_FILE}"
)

if (( ${#SCHEDULE_ENTRIES[@]} == 0 )); then
  echo "No scripts defined in schedule_config.yml" >&2
  exit 0
fi

build_cron_line() {
  local interval="$1"
  local command="$2"

  if (( interval <= 0 )); then
    return 1
  fi

  local minute_part hour_part
  if (( 60 % interval == 0 )); then
    minute_part="*/${interval}"
    hour_part="*"
  elif (( interval >= 60 && interval % 60 == 0 )); then
    local hours=$(( interval / 60 ))
    minute_part="0"
    hour_part="*/${hours}"
  else
    minute_part="*/${interval}"
    hour_part="*"
  fi

  printf "%s %s * * * cd %s && %s >> %s/cron.log 2>&1\n" \
    "${minute_part}" "${hour_part}" "${REPO_ROOT}" "${command}" "${REPO_ROOT}"
}

CURRENT_CRON="$(crontab -l 2>/dev/null || true)"
NEW_LINES=()

for entry in "${SCHEDULE_ENTRIES[@]}"; do
  IFS="|" read -r name command interval <<< "${entry}"
  if [[ -z "${command}" || -z "${interval}" ]]; then
    echo "# Skipping ${name}: missing command or interval"
    continue
  fi

  if ! cron_line=$(build_cron_line "${interval}" "${command}"); then
    echo "# Skipping ${name}: invalid interval (${interval})"
    continue
  fi

  if grep -Fxq "${cron_line}" <<< "${CURRENT_CRON}"; then
    echo "# Already installed: ${name}"
  else
    NEW_LINES+=("${cron_line}")
  fi
done

if (( ${#NEW_LINES[@]} == 0 )); then
  echo "All cron entries are already installed. No changes applied."
  exit 0
fi

{
  if [[ -n "${CURRENT_CRON}" ]]; then
    printf "%s\n" "${CURRENT_CRON}"
  fi
  printf "%s\n" "${NEW_LINES[@]}"
} | crontab -

echo "Installed ${#NEW_LINES[@]} new cron entries:"
printf "%s\n" "${NEW_LINES[@]}"
