#!/usr/bin/env bash
set -euo pipefail

if crontab -l >/dev/null 2>&1; then
  echo "# Current crontab entries:"
  crontab -l
else
  echo "No crontab entries found."
fi
