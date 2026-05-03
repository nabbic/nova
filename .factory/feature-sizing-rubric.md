# Feature sizing rubric

The factory's Plan stage runs a deterministic check against this rubric after
Haiku produces the structured PRD. Any **hard breach** routes the feature to
`MarkBlocked` in Notion with a suggested decomposition. Use this rubric when
writing a feature in Notion to self-size before submitting.

## Hard limits (any breach blocks)

| Threshold | Limit | Rationale |
|---|---|---|
| Total stories                                      | ≤ 4   | At a 6-Ralph-turn cap, 4 stories ≈ 1.5 turns/story |
| Total acceptance criteria (sum across stories)     | ≤ 12  | Tracks token-output budget reliably |
| Distinct scope domains (`db` / `backend` / `frontend` / `infra`) | ≤ 2 | Multi-domain features are nearly always too big |

## Soft signals (raise a `risk_flag`, may contribute to a hard block if extreme)

| Signal | Soft threshold | Hard threshold |
|---|---|---|
| Haiku-estimated files changed | > 15 | > 25 |
| Touches `app/db/migrations/` | always raise `migration` flag | — |
| Mentions OAuth, IAM cross-account, or webhook signing | always raise `auth` flag | — |

## Self-sizing tips

- **One verb per story.** "Buyers can export an engagement" — not "Buyers can
  export, edit, and re-import."
- **Acceptance criteria are observable, not implementation steps.** Bad:
  "Adds an `engagement_exports` table." Good: "GET /api/engagements/{id}/export
  returns 200 with the engagement payload for the owner buyer org."
- **Multi-domain features almost always split cleanly.** A typical bad shape
  is "ship the report PDF" — that's backend (rendering), frontend (download
  link), infra (S3 + CloudFront for the PDFs), db (a `reports` table). Each
  is its own feature; ship them in dependency order.

## What happens when a feature is blocked

The factory posts a structured Notion comment listing the breach and a
suggested decomposition (one bullet per sub-feature). You re-file each as a
fresh `Ready to Build` feature. The factory does not auto-create the children —
that's a deliberate human checkpoint.
