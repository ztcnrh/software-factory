#!/usr/bin/env bash
# Install, upgrade, or remove the software factory in a target repository.
# Upgrade = run again; git in the target shows what changed.
set -euo pipefail

usage() {
  cat <<USAGE
usage: install.sh <target-repo> [--uninstall]

  Copies the station skills and the caller workflow into the target and creates the
  factory:* labels on its GitHub repository (needs \`gh\` logged in for it).
  --uninstall    remove exactly what this script installed; labels and issues stay
USAGE
}

here=$(cd "$(dirname "$0")" && pwd)
target="" uninstall=0
for arg in "$@"; do
  case $arg in
    --uninstall) uninstall=1 ;;
    -h|--help) usage; exit 0 ;;
    -*) echo "unknown flag $arg" >&2; usage; exit 2 ;;
    *) target=$arg ;;
  esac
done
[ -n "$target" ] && [ -d "$target/.git" ] || { usage; exit 2; }
target=$(cd "$target" && pwd)

skills=(factory-triage factory-spec factory-implement factory-review factory-retro
        write-product-spec write-tech-spec council research)

if [ $uninstall = 1 ]; then
  for s in "${skills[@]}"; do rm -rf "$target/.claude/skills/$s"; done
  rm -f "$target/.github/workflows/factory.yml"
  echo "removed the factory from $target"
  exit 0
fi

mkdir -p "$target/.claude/skills" "$target/.github/workflows"
for s in "${skills[@]}"; do
  rm -rf "$target/.claude/skills/$s"
  cp -R "$here/.claude/skills/$s" "$target/.claude/skills/$s"
done
cp "$here/templates/factory.yml" "$target/.github/workflows/factory.yml"
(cd "$target" && PYTHONPATH=$here python3 -m factory.cli labels)

cat <<NEXT
installed into $target: ${#skills[@]} skills under .claude/skills/, .github/workflows/factory.yml

next:
  1. commit those files (the workflow's \`uses:\` line names the toolkit; point it at your fork if you have one)
  2. add the CLAUDE_CODE_OAUTH_TOKEN secret (\`claude setup-token\`) or ANTHROPIC_API_KEY
  3. in Settings → Actions → General, allow GitHub Actions to create and approve pull requests
then open an issue: the factory triages it.
NEXT
