# templates/ — live artifact shapes

Everything in this directory is **load-bearing**: some component of the factory points at it and fills it in. Each template has exactly one consumer, and nothing anywhere restates a template's shape a second time.

| Template | Consumer (the only one) |
| --- | --- |
| `REVIEW-PACKET.md` | the **`/factory` driver** (`.claude/commands/factory.md` §3) renders it at every human gate |

Three things deliberately **not** here:

- The spec shapes (`PRODUCT.md`, `TECH.md`) live in the skills that write them — `.claude/skills/write-product-spec` and `write-tech-spec` — because a fixed-heading template file fights their "optional sections earn their place" rule and would be a second home for the same shape.
- Formats rendered by engine *code* live in that code (e.g. the intervention record's shape is `src/factory/interventions.py`), so the engine stays self-contained when installed as a CLI tool.
- Human-facing guidance with no consumer lives in `docs/` or `FACTORY-MANUAL.md`, not here.

Editing a template changes real factory output — which also makes these files fair game for the **retro station** to improve.

Naming: templates and read-first human docs are `ALL-CAPS-WITH-HYPHENS.md`; machine-consumed config stays lowercase (`line.yml`, `policies.yml`).
