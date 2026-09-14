#!/usr/bin/env python3
"""Prefix each line of a unified diff with its side and number, so an inline review comment can
cite `path`, `side`, and `line` exactly as GitHub's review API wants them.

    annotate_diff.py < raw.patch > annotated.md

`[OLD:n]` is a removed line (LEFT), `[NEW:n]` an added line (RIGHT), `[OLD:n,NEW:m]` a context
line (RIGHT, m).
"""

from __future__ import annotations

import re
import sys

HUNK = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def annotate(patch: str) -> str:
    out, old, new = [], None, None
    for line in patch.splitlines():
        if line.startswith(("diff --git ", "Binary files ")):
            old = new = None
        elif m := HUNK.match(line):
            old, new = int(m[1]), int(m[2])
        elif old is not None and line[:1] == "-":
            out.append(f"[OLD:{old}] {line[1:]}")
            old += 1
            continue
        elif old is not None and line[:1] == "+":
            out.append(f"[NEW:{new}] {line[1:]}")
            new += 1
            continue
        elif old is not None and line[:1] == " ":
            out.append(f"[OLD:{old},NEW:{new}] {line[1:]}")
            old, new = old + 1, new + 1
            continue
        out.append(line)
    return "\n".join(out)


if __name__ == "__main__":
    sys.stdout.write(annotate(sys.stdin.read()) + "\n")
