---
description: Show the factory board, the North Star metrics, and anything waiting on you.
allowed-tools: Bash
---

Board: !`factory status 2>/dev/null || echo "(factory not initialized here)"`

Metrics: !`factory metrics 2>/dev/null || echo "(no metrics yet)"`

Summarize for me: what's in flight, what's **waiting on me** at a human gate (give the exact `factory gate <id> --decision ...` command for each), and the current one-shot ship rate with a one-line read on it — how many ships it's over (a rate on 2 ships is noise) and where steers are concentrated. When the metrics show a `trend:` line (recent ships vs the window before), read it sample-size-first — a window of 5 is still small — and only call it a trend when the direction would survive one ship flipping. If no trend line is shown there aren't enough ships to compare windows; don't infer one. If steers have piled up, suggest running `/factory retro`.
