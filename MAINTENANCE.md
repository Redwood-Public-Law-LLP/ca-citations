# Maintenance record — ca-citations

```toml
name = "ca-citations"
status = "pilot"               # production | pilot | prototype | dormant | archived
owner = "Redwood Public Law, LLP"
summary = "Python parser for California code, Constitution, CCR, and AG-opinion citations in prose."

blast_radius = "Indirect: a regression changes what the firm's cite-checking finds in drafts and what its citation indexes link. Nothing is deployed from this repo."
tier = 2                       # 1 = attorneys feel it same-day, 2 = within a week, 3 = internal only
catalog_entries = []           # reaches users only through the tools that import it

[dependencies]
upstream = ["pydantic"]
downstream = ["the firm's cite-checking server", "advisory-opinion index", "case-law index"]

[costs]
monthly_usd = 0.0
as_of = "2026-11-07"
basis = "A library; nothing runs on its own. CI minutes only."

[review]
cadence = "quarterly"
next = "2027-02-07"
last = "2026-11-07"

[sunset]
criteria = "None while any tool parses California citations."
```

## Runbook

Nothing runs here. If a tool's citation counts change after a version bump,
compare `scan` output for the same text at both versions; every behavior
change should have a test and a PR line saying what output changed.
