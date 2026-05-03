# Factory v2 smoke fixtures

Each file is a JSON description of a Notion feature page used to drive a smoke
run through the v2 factory state machine. The `expected_outcome` field tells
the smoke runner what to assert.

| Fixture | Stories | Domains | Expected |
|---|---|---|---|
| trivial.json    | ~1 | backend       | Plan passes; no blockers |
| medium.json     | ~3 | backend       | Plan passes; no blockers |
| oversized.json  | ~5+ | db+frontend+infra+backend | Plan emits `feature_too_large` blocker; MarkBlocked posts a Notion comment with split |

## Running

```bash
bash scripts/factory_smoke_v2.sh trivial
bash scripts/factory_smoke_v2.sh medium
bash scripts/factory_smoke_v2.sh oversized
```

The runner creates a synthetic Notion page in the Features DB, starts an
execution of `nova-factory-v2-planonly`, polls until terminal, and asserts
the expected outcome.
