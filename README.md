# Software Factory

An agentic delivery line for your own projects. Drop in a work item; it triages, specs, implements, reviews, verifies, and hands you a change to ship. Every time you step in to correct it, it writes down why — then rewrites its own instructions so it needs you less next time.

This repo is the machinery. It installs *into* your project repos and runs there.

```
new item → Triage ─┬─ needs a spec → Spec → ✋ approve the plan
                   └─ small enough → build it now
                                            │
                                            ▼
        Implement ⇄ Code review → Verify → ✋ ship it? → Deploy → Done
         (sent back until it passes)
```

Wherever you see ✋ the line stops and waits for you, and it stops too when it hits something only you can answer. **It never merges.** Stations branch, commit, and open pull requests; the merge button stays yours.

The sixth station is the whole point. **Retro** reads every place you stepped in — a send-back, a correction, an unblock — and proposes changes to the factory's own station instructions and gate policies, as a pull request you review. The number it exists to raise is the **one-shot ship rate**: the share of changes that ship with no human rework at all. The goal was never zero humans. It's zero rework, until your review is a rubber stamp.

## Try it

```bash
uv tool install /path/to/software-factory       # puts the `factory` CLI on PATH
python3 install/install.py /path/to/your/repo   # adopt it into a project
cd /path/to/your/repo && factory init
```

Then, in a Claude Code session in that repo:

```bash
factory new "the thing I want"
/factory          # drives it down the line until it needs you
/factory-status    # the board, the metrics, what's waiting on you
```

Or skip all of it: open a Claude Code session here and say *"install the factory into `<path>`"*. It runs fully local — no cloud accounts needed to start.

## Next

- **[FACTORY-MANUAL.md](FACTORY-MANUAL.md)** — operating it day to day, and what each gate is really asking you.
- **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** — how the machine is built, and why it's built that way.
- **[PRINCIPLES.md](PRINCIPLES.md)** — what it's for, where it's going, and what it doesn't do yet.

Proven end-to-end on real work, and still early — the cloud layer ships disabled. Meant to be used, stress-tested, and improved, increasingly by itself.

*Inspired by Zach Lloyd's "factory engineering" thesis and the patterns in [warpdotdev/common-skills](https://github.com/warpdotdev/common-skills).*
