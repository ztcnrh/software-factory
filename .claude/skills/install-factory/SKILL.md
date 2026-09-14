---
name: install-factory
description: Install, upgrade, or remove the software factory in a target repository from this toolkit checkout. Use when someone asks to install / adopt / set up the factory, pull the latest toolkit into a project, or uninstall it. Toolkit-only; not copied into target repos.
disable-model-invocation: true
allowed-tools: Bash Read
---

You run the adoption lifecycle for the human from this toolkit's root. `./install.sh -h` is the flag reference.

## Install

1. Confirm the target path is a git repository with a GitHub remote and that `gh auth status` is logged in for it.
2. `./install.sh <target>` copies `.claude/skills/factory*`, `.claude/skills/{write-product-spec,write-tech-spec,council,research}` into the target and creates the `factory:*` labels. Add `--with-cloud` to also copy `.github/workflows/factory.yml`.
3. `uv tool install <toolkit path>` puts the `factory` CLI on PATH.
4. Tell them to commit the installed files, and, for cloud, to add the `CLAUDE_CODE_OAUTH_TOKEN` secret (`claude setup-token`), set the `FACTORY_TOOLKIT_GIT` repository variable to a pip-installable ref of this toolkit, and enable "Allow GitHub Actions to create and approve pull requests" in the repository's Actions settings.
5. First drive, in a Claude Code session in the target: `/factory new "<something small>"`.

## Upgrade

Pull the latest toolkit, rerun `./install.sh <target>` with the same flags, and have them read `git diff` in the target. The installer overwrites the factory's files and touches nothing else; a local edit they want to keep shows up as a reverted hunk, and git is the merge tool.

## Uninstall

`./install.sh <target> --uninstall` removes exactly the paths the installer created. Labels and issues stay; delete them by hand if wanted.
