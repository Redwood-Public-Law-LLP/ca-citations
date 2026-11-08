# CLAUDE.md

A California citation parser used by several of the firm's tools: draft
cite-checking, and citation indexes of advisory opinions and appellate case
law. A change here reaches all of them, so treat any behavior change as a
change to a published contract.

## Ground rules

1. **No other copy.** If a tool needs a form this package lacks, add it here,
   with a test, rather than patching around it downstream.
2. **Precision beats recall for anything persisted.** `scan` may infer; every
   inference is visible in `attribution` and `warnings`. `extract` stores only
   what the text names.
3. **A range cites its first section** (decided 2026-11-07): one citation with
   `range_end` set, never the endpoint as its own cite.
4. **"Former" is never the current section.** `scan` sets `former=True`;
   `extract` leaves it out.
5. **Every behavior change gets a test built from real text** and a line in
   the PR saying what output changes.
6. Pure Python, pydantic only. No database, no network, no model calls.

## Conventions

- Python 3.11. `uv run pytest -q`, `uv run ruff check src tests`, and
  `uv run mypy src` before any PR; CI runs the same.
- Branches `claude/<topic>-<id>`; PRs against `main`; a maintainer reviews and
  merges.
- California Style Manual (4th ed.) forms are the reference for what must
  parse.
- Keep internal tool names, people, and client matters out of this repo; it is
  public.
