# ca-citations

Finds and parses California legal citations in prose: code sections, the
California Constitution, the California Code of Regulations, and Attorney
General opinions. Pure Python; pydantic is the only dependency. No database,
no network.

Written for California public-agency law practice, where citations follow the
California Style Manual (4th ed.) and lawyers write "Section 241 of the Public
Utilities Code" as often as "Pub. Util. Code, § 241."

## Use

```python
from ca_citations import extract, parse, scan

parse("Cal. Gov. Code § 54953(a)")              # one citation string -> ParsedCitation
scan("... Gov. Code sections 54950-54962 ...")  # every citation in prose -> [SpannedCitation]
extract(opinion_text)                           # index rows, deduped on (code, section)
```

- **`scan`** is for checking a draft. It finds as much as it can, including
  codes inferred from context (`Id.`, a "further statutory references are to
  the X Code" note, the last code named). Every result says how its code was
  found in `attribution`; only `"named"` means the code is written beside the
  section.
- **`extract`** is for building an index. It keeps only citations whose code
  the text names, leaves out "former" sections, and records the first section
  of a range. It adds CCR and AG-opinion citations and the verbatim quotation
  or parenthetical that follows a cite.

Neither establishes that a provision exists, is current, or is good law.
Verify against the official code text, and KeyCite before relying on any
authority.

## Develop

```bash
uv sync --extra dev
```

```bash
uv run pytest -q
```

```bash
uv run ruff check src tests && uv run mypy src
```
