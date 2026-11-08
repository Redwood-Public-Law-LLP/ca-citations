"""California citation finding and parsing.

Two layers:

* **Core** (`codes`, `models`, `parser`, `scanner`): California code and
  Constitution citations. `parser.parse` reads one citation string;
  `scanner.scan` finds every citation in prose, including context-derived ones
  (`Id.`, the document's "further statutory references" note, carry-forward),
  each marked by `attribution` so a caller can decide what to trust.
* **Extraction** (`extra`, `context`, `reporter`, `extract`): forms the core
  does not cover (CCR, AG opinions, "Sections X to Y, inclusive"), the verbatim
  quotation or parenthetical after a cite, and `extract.extract`, which
  deduplicates on (code, section) for a citation index and keeps only
  citations whose code is named in the text.

Consolidated 2026-11-07 from two copies that had drifted apart.
"""

from ca_citations.extract import ExtractedCite, extract
from ca_citations.models import ParsedCitation, SpannedCitation
from ca_citations.parser import CitationParseError, parse, try_parse
from ca_citations.scanner import scan

__all__ = [
    "CitationParseError",
    "ExtractedCite",
    "ParsedCitation",
    "SpannedCitation",
    "extract",
    "parse",
    "scan",
    "try_parse",
]
