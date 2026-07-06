# The factory loop

This is the line encoded in [`line.yml`](../line.yml) — a faithful redraw of the source factory diagram. Stations are rectangles, human gates are diamonds, the dashed edges are the backward loops the learning loop tries to eliminate.

```mermaid
flowchart TD
    new([New task or issue]) --> triage[Triage station]
    triage --> outcome{Triage outcome}

    outcome -->|needs spec| spec[Spec station]
    outcome -->|automatable| impl[Implementation station]
    outcome -->|needs clarification| clar[/✋ Human provides input/]
    outcome -->|park| parked[(Parked)]
    clar --> triage

    spec --> specrev{✋ Spec review}
    specrev -->|approved| impl
    specrev -.needs revision.-> spec

    impl --> review[Code-review station]
    review --> verify[Verification station]
    review -.changes requested.-> impl
    verify --> shiprev{✋ Ready to ship?}
    shiprev -.not ready.-> review
    shiprev -->|approved| ci[CI / CD]

    ci --> ship[Ship it]
    ship --> monitor[Monitoring station]
    monitor --> detected{Issue detected?}
    detected -->|no| monitor
    detected -->|yes — open new item| newitem[Create work item]
    newitem -.factory loop continues.-> triage

    retro{{Retro station}} -.learns from every ✋.-> spec
    retro -.proposes gate policies.-> specrev
    retro -.proposes gate policies.-> shiprev

    classDef gate fill:#fbe7a2,stroke:#b8860b;
    classDef learn fill:#d7c5f5,stroke:#5a32a3;
    class specrev,shiprev,clar gate;
    class retro learn;
```

The one element not in the original diagram is the **Retro station** (purple), drawn with dashed edges into the stations and gates it improves — because in this factory the line doesn't just run, it re-tools itself from every human touch. See [LEARNING-LOOP.md](LEARNING-LOOP.md).
