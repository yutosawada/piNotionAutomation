#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CONFIG_FILE="${REPO_ROOT}/schedule_config.yml"

if [[ ! -f "${CONFIG_FILE}" ]]; then
  echo "Error: ${CONFIG_FILE} not found" >&2
  exit 1
fi

# Parse schedule_config.yml to extract script entries
# Format: script_name|command|schedule
mapfile -t SCHEDULE_ENTRIES < <(
  awk '
  function emit() {
    if (script != "" && command != "" && schedule != "")
      print script "|" command "|" schedule
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
    schedule=""
    next
  }
  /^    command:/ {
    cmd=$0
    sub(/^    command:[[:space:]]*/, "", cmd)
    sub(/[[:space:]]+#.*/, "", cmd)
    command=cmd
    next
  }
  /^    schedule:/ {
    val=$0
    sub(/^    schedule:[[:space:]]*/, "", val)
    # Remove surrounding quotes if present
    gsub(/^"/, "", val)
    gsub(/"[[:space:]]*$/, "", val)
    gsub(/"[[:space:]]+#.*/, "", val)
    sub(/[[:space:]]+#.*/, "", val)
    schedule=val
    next
  }
  END { emit() }
  ' "${CONFIG_FILE}"
)

if (( ${#SCHEDULE_ENTRIES[@]} == 0 )); then
  echo "No scripts defined in schedule_config.yml" >&2
  exit 0
fi

# Validate cron schedule format (5 fields: min hour dom month dow)
validate_cron_schedule() {
  local schedule="$1"
  local field_count
  field_count=$(echo "${schedule}" | awk '{print NF}')
  if (( field_count != 5 )); then
    return 1
  fi
  return 0
}

# Build cron line from schedule and command
build_cron_line() {
  local schedule="$1"
  local command="$2"

  if ! validate_cron_schedule "${schedule}"; then
    return 1
  fi

  printf "%s cd %s && %s >> %s/cron.log 2>&1\n" \
    "${schedule}" "${REPO_ROOT}" "${command}" "${REPO_ROOT}"
}

CURRENT_CRON="$(crontab -l 2>/dev/null || true)"
NEW_LINES=()

for entry in "${SCHEDULE_ENTRIES[@]}"; do
  IFS="|" read -r name command schedule <<< "${entry}"
  if [[ -z "${command}" || -z "${schedule}" ]]; then
    echo "# Skipping ${name}: missing command or schedule"
    continue
  fi

  if ! cron_line=$(build_cron_line "${schedule}" "${command}"); then
    echo "# Skipping ${name}: invalid schedule format (${schedule})"
    echo "#   Expected format: 'min hour day month weekday' (5 fields)"
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
