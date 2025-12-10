#!/usr/bin/env bash
set -euo pipefail

if crontab -l >/dev/null 2>&1; then
  crontab -r
  echo "✓ Cleared existing crontab entries."
else
  echo "No crontab entries to clear."
fi
