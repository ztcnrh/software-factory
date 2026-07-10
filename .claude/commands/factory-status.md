---
description: Show the factory board, the North Star metrics, and anything waiting on you.
allowed-tools: Bash
---

Board: !`factory status 2>/dev/null || echo "(factory not initialized here)"`

Metrics: !`factory metrics 2>/dev/null || echo "(no metrics yet)"`

Summarize for me: what's in flight, what's **waiting on me** at a human gate (give the exact `factory gate <id> --decision ...` command for each), and the current one-shot ship rate with a one-line read on it — how many ships it's over (a rate on 2 ships is noise) and where steers are concentrated. The metric is a cumulative point-in-time number, so don't infer a trend it can't show. If interventions have piled up, suggest running `/factory retro`.
