#!/usr/bin/env bash
# Smoke the installer and the CLI against the sandbox repo with a throwaway issue.
set -euo pipefail
sandbox=${SANDBOX:-$HOME/Desktop/repos/factory-sandbox}
here=$(cd "$(dirname "$0")/.." && pwd)
"$here/install.sh" "$sandbox"
cd "$sandbox"
n=$(gh issue create --title "drive: throwaway $(date +%s)" --body "smoke" --label factory:triage \
    --json number -q .number 2>/dev/null || gh issue create --title "drive: throwaway" --body "smoke" \
    --label factory:triage | sed -E 's#.*/##')
factory board | grep -q "#$n"
cat > /tmp/drive-report.json <<JSON
{"station":"triage","verdict":"park","summary":"drive smoke","model":"none","cost_usd":0,
 "session_id":"drive-$n","turns":0,"duration_ms":0,"run_url":null,"ts":"2026-01-01T00:00:00Z"}
JSON
factory apply "$n" /tmp/drive-report.json | grep -q "factory:parked"
factory gate "$n" retriage --why "drive" | grep -q "factory:triage"
factory gate "$n" done | grep -q "factory:done"
factory metrics --since 1d | grep -q "#$n"
gh issue close "$n" --comment "drive smoke done" >/dev/null
echo "drive ok (#$n)"
