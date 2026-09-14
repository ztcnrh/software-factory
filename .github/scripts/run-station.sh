#!/usr/bin/env bash
# Run one station with `claude -p` and write its report. Called by .github/workflows/factory.yml
# from the adopter's checkout, with the toolkit at $TOOLKIT and the packet at $PACKET.
#
#   STATION  triage | spec | implement | review | retro
#   ISSUE PR BRANCH HEAD   what route found; empty when there is none
#   BASE     the default branch, where PRs go
#   PACKET   directory of Markdown the context job built
#   OUT      where report.json and the raw stream go
#   OAUTH_TOKEN / API_KEY   one of them; exported under the name Claude Code expects
set -euo pipefail
: "${STATION:?}" "${TOOLKIT:?}" "${PACKET:?}" "${OUT:?}"
mkdir -p "$OUT"

# Exactly one credential: an ANTHROPIC_API_KEY outranks the OAuth token even when empty.
if [ -n "${OAUTH_TOKEN:-}" ]; then export CLAUDE_CODE_OAUTH_TOKEN="$OAUTH_TOKEN"
elif [ -n "${API_KEY:-}" ]; then export ANTHROPIC_API_KEY="$API_KEY"
else echo "::error::set the CLAUDE_CODE_OAUTH_TOKEN or ANTHROPIC_API_KEY secret"; exit 1; fi
unset OAUTH_TOKEN API_KEY

skill=.claude/skills/factory-$STATION/SKILL.md
model=$(sed -n 's/^model: *//p' "$skill" | head -1)
tools=$(sed -n 's/^allowed-tools: *//p' "$skill" | head -1)
[ -n "$model" ] || { echo "::error::$skill has no model: in its frontmatter"; exit 1; }

case $STATION in
  triage) prompt="/factory-triage Issue #$ISSUE. Packet: $PACKET/." ;;
  spec|implement)
    if [ -z "${BRANCH:-}" ]; then where="Branch: none yet."
    elif [ -n "${PR:-}" ]; then where="Branch: $BRANCH (PR #$PR)."
    else where="Branch: $BRANCH (no PR yet)."; fi
    prompt="/factory-$STATION Issue #$ISSUE. Packet: $PACKET/. Base: ${BASE:-main}. $where" ;;
  review) prompt="/factory-review PR #$PR for issue #$ISSUE. Packet: $PACKET/." ;;
  retro) prompt="/factory-retro Packet: $PACKET/." ;;
  *) echo "::error::unknown station $STATION"; exit 1 ;;
esac

# Commits a station makes are the factory's, so a human's commit on its PR stays distinguishable.
export GIT_AUTHOR_NAME=factory GIT_AUTHOR_EMAIL=factory@users.noreply.github.com
export GIT_COMMITTER_NAME=factory GIT_COMMITTER_EMAIL=factory@users.noreply.github.com
echo "factory: $prompt  [$model]"

# A structured-output call occasionally leaks its tool-call envelope into a string field; that
# report would be refused by apply, so the run is repeated once before giving up.
for attempt in 1 2; do
# shellcheck disable=SC2086  # $tools is a space-separated list by design
claude -p "$prompt" \
  --output-format stream-json --verbose \
  --model "$model" ${tools:+--allowedTools $tools} \
  --permission-prompts none \
  --json-schema "$(PYTHONPATH=$TOOLKIT python3 -m factory.cli schema "$STATION")" \
  --append-system-prompt "$(cat "$TOOLKIT/factory/prompts/station.md")" \
  < /dev/null \
  | tee "$OUT/stream.jsonl" \
  | jq -r --unbuffered '
      select(.type == "assistant") | .message.content[]? |
      if .type == "tool_use" then
        "  ▸ \(.name) \((.input.command // .input.file_path // .input.pattern // .input.description // "") | tostring | .[0:110])"
      elif .type == "text" and (.text | length) > 0 then "  · \(.text | .[0:200])"
      else empty end' || true

result=$(jq -c 'select(.type == "result")' "$OUT/stream.jsonl" | tail -1)
[ -n "$result" ] || { echo "::error::claude produced no result event"; tail -n 5 "$OUT/stream.jsonl"; exit 1; }

# The station's structured output plus what only the runner knows.
jq -n --argjson r "$result" --arg station "$STATION" --arg run_url "${RUN_URL:-}" \
      --arg head "${HEAD:-}" --arg pr "${PR:-}" '
  ($r.structured_output
   | if type == "object" then . else error("no structured report (" + ($r.subtype // "?") + ")") end)
  + {station: $station,
     model: (($r.modelUsage // {}) | to_entries
             | if length > 0 then max_by(.value.costUSD).key else null end),
     cost_usd: ((($r.total_cost_usd // 0) * 10000 | round) / 10000),
     session_id: $r.session_id, turns: $r.num_turns, duration_ms: $r.duration_ms,
     run_url: (if $run_url == "" then null else $run_url end), ts: (now | todate),
     head: (if $head == "" then null else $head end),
     pr: (if $pr == "" then null else ($pr | tonumber) end)}' > "$OUT/report.json" \
  || { echo "::error::no station report came back"; jq 'del(.structured_output)' <<<"$result"; exit 1; }
if grep -q '<parameter name=' "$OUT/report.json" && [ "$attempt" = 1 ]; then
  echo "::warning::the report carries tool-call markup (malformed structured output); running again"
  mv "$OUT/stream.jsonl" "$OUT/stream-malformed.jsonl"
  continue
fi
break
done
jq -r '"factory: \(.station) → \(.verdict) · $\(.cost_usd) · \(.turns) turns"' "$OUT/report.json"
