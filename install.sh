#!/usr/bin/env bash
# Install, upgrade, or remove the software factory in a target repository.
# Upgrade = run again; git in the target shows what changed.
set -euo pipefail

usage() {
  cat <<USAGE
usage: install.sh <target-repo> [--with-cloud] [--uninstall]

  --with-cloud   also copy .github/workflows/factory.yml (needs the CLAUDE_CODE_OAUTH_TOKEN
                 secret and the FACTORY_TOOLKIT_GIT variable on the repo)
  --uninstall    remove exactly what this script installed; labels and issues stay
USAGE
}

here=$(cd "$(dirname "$0")" && pwd)
target="" cloud=0 uninstall=0
for arg in "$@"; do
  case $arg in
    --with-cloud) cloud=1 ;;
    --uninstall) uninstall=1 ;;
    -h|--help) usage; exit 0 ;;
    -*) echo "unknown flag $arg" >&2; usage; exit 2 ;;
    *) target=$arg ;;
  esac
done
[ -n "$target" ] && [ -d "$target/.git" ] || { usage; exit 2; }
target=$(cd "$target" && pwd)

skills=(factory factory-triage factory-spec factory-implement factory-review factory-retro
        write-product-spec write-tech-spec council research)

if [ $uninstall = 1 ]; then
  for s in "${skills[@]}"; do rm -rf "$target/.claude/skills/$s"; done
  rm -f "$target/.github/workflows/factory.yml"
  echo "removed the factory from $target"
  exit 0
fi

mkdir -p "$target/.claude/skills"
for s in "${skills[@]}"; do
  rm -rf "$target/.claude/skills/$s"
  cp -R "$here/.claude/skills/$s" "$target/.claude/skills/$s"
done
if [ $cloud = 1 ]; then
  mkdir -p "$target/.github/workflows"
  cp "$here/workflows/factory.yml" "$target/.github/workflows/factory.yml"
fi
if command -v factory >/dev/null; then
  (cd "$target" && factory labels)
else
  echo "factory CLI not on PATH: run 'uv tool install $here' then 'factory labels' in $target"
fi
echo "installed into $target: ${#skills[@]} skills under .claude/skills/$([ $cloud = 1 ] && echo ', .github/workflows/factory.yml')"
echo "next: commit these files, then in a Claude Code session there run  /factory new \"<title>\""
