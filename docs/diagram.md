# The factory loop

This is the line encoded in [`line.yml`](../line.yml). **Stations are blue rectangles** (`deploy` is green-tinted because it's external — post-merge CI/CD, not an agent — and green means shipped), **human gates are soft-yellow ✋ diamonds**, **terminals are cylinders**. Solid green edges are the forward happy path; thin gray dashed edges are everything off it — the backward loops the learning loop tries to eliminate, plus the `park` shelving edges. `ship_review` approval is the human's go-ahead; **they** merge the item's PR, and that merge triggers the post-merge CI/CD `deploy` — a green deploy (health-wait baked in) is the ship point, so the item is *done* when it ships. No station or driver ever merges. Continuous monitoring is deferred; new work arrives via `factory new` or the **`factory intake`** sensor, which files GitHub issues labeled `intake` into triage (see [OPTIMIZATION-AREAS.md](OPTIMIZATION-AREAS.md)).

A pre-rendered copy lives at [`diagram.png`](diagram.png) — regenerate it with `scripts/render-diagram.sh` after editing the diagram below.

Not drawn: the `blocked` gate — any station can force an item there via its report's `human_required` escape hatch (and `spec`/`implement` route there explicitly), after which the human either unblocks it back to triage or parks it.

```mermaid
flowchart TD
    %% ---- forward happy path first: these edges set the top-to-bottom spine ----
    new([New task]) --> triage[Triage station]:::station
    triage -- "needs spec" --> spec[Spec station]:::station
    spec -- "ready for review" --> specrev{✋ Spec review}:::gate
    specrev -- "approved" --> impl[Implementation station]:::station
    triage -- "automatable" --> impl
    impl --> review[Code-review station]:::station
    review -- "pass" --> verify[Verification station]:::station
    verify -- "verified" --> shiprev{✋ Ready to ship?}:::gate
    shiprev -- "approved · human merges" --> deploy[Deploy · post-merge CI/CD]:::external
    deploy -- "succeeded" --> done[(Done)]
    triage -- "needs human clarification" --> clar{✋ Human clarification}:::gate
    clar -- "provided" --> triage

    %% ---- off the happy path: backward loops and shelving ----
    issues([New GitHub issue]) -. "factory intake" .-> triage
    verify -. "failed" .-> shiprev
    specrev -. "needs revision" .-> spec
    review -. "changes requested" .-> impl
    shiprev -. "not ready" .-> review
    shiprev -. "recheck" .-> verify
    deploy -. "failed" .-> review
    triage -. "park" .-> parked[(Parked)]
    clar -. "park" .-> parked
    specrev -. "park" .-> parked
    shiprev -. "park" .-> parked
    parked -. "revive" .-> triage

    %% ---- the learning loop, declared last so it doesn't anchor the layout ----
    %% interventions at the gates feed retro; retro proposes improvements back
    retro{{Retro station}}:::learn
    specrev <-. "interventions in / gate policies out" .-> retro
    shiprev <-. "interventions in / gate policies out" .-> retro
    retro -. "improves station skills" .-> spec

    %% edges 0-11 = solid happy path (green); 12-26 = dashed off-path (gray)
    linkStyle 0,1,2,3,4,5,6,7,8,9,10,11 stroke:#6a994e,stroke-width:2px
    linkStyle 12,13,14,15,16,17,18,19,20,21,22,23,24,25,26 stroke:#9a9a9a,stroke-width:1px

    classDef station fill:#cfe2ff,stroke:#2f6fba,color:#123a66
    classDef gate fill:#faf1cf,stroke:#c9a227,color:#6b5900,font-size:12px
    classDef external fill:#e4efdc,stroke:#6a994e,color:#33512a
    classDef learn fill:#d7c5f5,stroke:#5a32a3,color:#2a1550
```

The **Retro station** (purple) closes the learning loop: every human intervention at a gate feeds it, and it proposes improvements back — sharper station skills, gate policies that auto-clear proven-safe items — because in this factory the line doesn't just run, it re-tools itself from every human steer. See [LEARNING-LOOP.md](LEARNING-LOOP.md). (Note: `verify` routes to the ship gate on both `verified` and `failed` — the human always sees verification output — but only `verified` is the happy path, so `failed` is drawn dashed.)

The ship gate has two distinct ways back, and which one it is says where the problem was. **`not ready`** goes to code review: something is wrong with the change. **`recheck`** goes straight back to verification: nothing is wrong with the change — verification couldn't demonstrate part of it (missing access, an environment that wouldn't come up), the human cleared that blocker, and the item needs demonstrating rather than rebuilding. Both count as human steers against the North Star; `recheck` just costs one station run instead of three.
