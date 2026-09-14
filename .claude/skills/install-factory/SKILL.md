---
name: install-factory
description: Install, upgrade, or remove the software factory in a target repository from this toolkit checkout. Use when someone asks to install / adopt / set up the factory, pull the latest toolkit into a project, or uninstall it. Toolkit-only; not copied into target repos.
disable-model-invocation: true
allowed-tools: Bash Read
---

You run the adoption lifecycle for the human from this toolkit's root. `./install.sh -h` is the flag reference.

## Install

1. Confirm the target path is a git repository with a GitHub remote and that `gh auth status` is logged in for it.
2. `./install.sh <target>` copies the five station skills plus `write-product-spec`, `write-tech-spec`, `council`, and `research` into `.claude/skills/`, copies `templates/factory.yml` to `.github/workflows/factory.yml`, and creates the `factory:*` labels.
3. Tell them the three steps the installer printed: commit the files (and point the workflow's `uses:` line at their fork of the toolkit if they have one), add the `CLAUDE_CODE_OAUTH_TOKEN` secret (`claude setup-token`) or `ANTHROPIC_API_KEY`, and allow GitHub Actions to create and approve pull requests in the repository's Actions settings.
4. First drive: open a small issue in the target; the factory triages it and says what to do next.

## Upgrade

Pull the latest toolkit, rerun `./install.sh <target>`, and have them read `git diff` in the target. The installer overwrites the factory's files and touches nothing else; a local edit they want to keep shows up as a reverted hunk, and git is the merge tool. The reusable workflow itself updates with the toolkit's `main`; nothing to reinstall for that.

## Uninstall

`./install.sh <target> --uninstall` removes exactly the paths the installer created. Labels and issues stay; delete them by hand if wanted.
