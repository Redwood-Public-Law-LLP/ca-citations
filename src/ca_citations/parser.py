"""Parse a single California statutory citation string.

Handles Bluebook (`Cal. Civ. Code § 1714(a)(1)`), California Style Manual
(`Civ. Code, § 1714, subd. (a)(1)`), spelled-out (`Civil Code section 1714`),
informal (`CCP § 425.16`, `Penal Code 187`), and the various "subd." /
"subdivision" / glued-paren spellings that appear in actual practice.

For free prose, use citation.scanner.scan(text) which finds candidate spans
and runs this parser on each.
"""

from __future__ import annotations

import re

from ca_citations.codes import resolve_code
from ca_citations.models import ParsedCitation

# Section-number pattern. Three layered parts:
#   \d+              the base number
#   (?:\.\d+)*       decimal subsections ("425.16", "21080.5", "5473.10")
#   [A-Za-z]{0,2}    an OPTIONAL letter suffix ("5473a", "1203.1bb", "30459.2A")
# Letter suffixes are real, distinct sections in the California codes (522 of
# them across the non-CONS codes — e.g. HSC § 5473a, the delinquencies-only
# election, is a different provision from § 5473). They run 1-2 letters, either
# case, and can follow a decimal ("1317.9a"). Dropping the letter silently
# returned the BASE section's text at high confidence (found 2026-06-04). The
# suffix is captured as part of section_num so it survives into a database
# lookup (PUBINFO keys lettered sections as e.g. '5473a.'); case is the
# caller's to reconcile at lookup time. The {0,2} cap matches the data (no
# 3+-letter suffix exists); a malformed 3-letter input resolves to not_found
# rather than silently collapsing to the base number.
_SECTION_NUM = r"\d+(?:\.\d+)*[A-Za-z]{0,2}"

# Section anchor: § (single or doubled), or "section" / "sections" / "sec." /
# "secs." (case-insensitive), followed by the section number.
#
# The plural spellings are load-bearing, not cosmetic. Without them a string
# like "Penal Code sections 330a and 330.1" failed this regex entirely, fell
# through to _FALLBACK_RE, and died on resolve_code("Penal Code sections") —
# so every plural reference parsed as nothing at all. Plural lists are how
# California lawyers normally write, so that silently dropped the majority of
# citations in real prose.
_SECTION_RE = re.compile(
    r"(?P<marker>§{1,2}|sec(?:tions?|s?\.))\s*"
    r"(?P<section_num>" + _SECTION_NUM + r")",
    re.IGNORECASE,
)

# Fallback: <code-name> <digits> with no section marker, e.g. "Penal Code 187".
# Intentionally requires a word-boundary before the digits to avoid matching
# inside the code name (e.g. "1872" in "Civil Code (1872)").
_FALLBACK_RE = re.compile(
    r"^(?P<code>.*?)\s+(?P<section_num>" + _SECTION_NUM + r")\s*(?P<rest>.*)$"
)

# Subdivision label: parenthesized 1-2 letter alphabetic OR 1-3 digit numeric.
# Tight bounds on purpose — a parenthetical year like "(1872)" should NOT match
# (4 digits), and free-text parentheticals like "(see also)" should NOT match.
_LABEL_RE = re.compile(r"\(([A-Za-z]{1,2}|\d{1,3})\)")

# Detect range markers we should warn about even though we only resolve the
# first. A plural marker alone is NOT enough: "§§ 1714, 1715" is a list, not a
# range, and citation.scanner now expands lists into one citation each — so
# warning about a range there was doubly wrong. An actual range separator
# between two numbers is required.
_RANGE_HINT_RE = re.compile(
    r"(?:§§|\b(?:sections?|secs?\.))\s*\d[\d.]*[A-Za-z]{0,2}"
    r"\s*(?:\bto\b|\bthrough\b|–|—|-)\s*\d",
    re.IGNORECASE,
)

# --- California Constitution -------------------------------------------------
# Constitutional citations are shaped differently from code citations: they
# carry an *article* (e.g. "XIII D"), and a section number is NOT unique
# without it — every article has its own § 1, § 6, etc. We route these down a
# dedicated branch before the generic code parse.

# Cheap detector: does the string name the Constitution at all? "const." /
# "constitution" with a word boundary; deliberately does NOT match
# "constitutional" / "constituent" (the optional "itution" or empty branch
# both fail the trailing \b inside those longer words).
_CONST_PREFIX_RE = re.compile(r"\bconst(?:\.|itution)?\b", re.IGNORECASE)

# Const prefix + "art."/"article" + the article id. The article is a run of
# Roman-numeral letters optionally followed by a single sub-article letter
# ("XIII D", "X A"). The (?![A-Za-z]) guard keeps the optional letter from
# swallowing the "s" of a following "section" when there's no comma.
_CONST_ARTICLE_RE = re.compile(
    r"const(?:\.|itution)?\b\.?,?\s*"
    r"art(?:\.|icle)?\b\.?\s*"
    r"(?P<article>[IVXLCDM]+(?:\s+[A-Za-z](?![A-Za-z]))?)",
    re.IGNORECASE,
)


# "former section 6254", "Gov. Code, former § 6254", "former Government Code
# section 6254". Only the word immediately before the code name or the section
# marker counts; "former" elsewhere in a sentence is ordinary prose.
_FORMER_LEAD_RE = re.compile(r"^\s*former\s+", re.IGNORECASE)
_FORMER_TRAIL_RE = re.compile(r",?\s*\bformer\s*$", re.IGNORECASE)

FORMER_WARNING = (
    "citation is to a FORMER section: the number may since have been "
    "repealed, renumbered, or reused, so the current text at this number is "
    "not the text the citing document relied on"
)


class CitationParseError(ValueError):
    """Raised when the input string cannot be parsed as a CA statutory citation."""


def parse(text: str) -> ParsedCitation:
    """Parse a citation string into a ParsedCitation.

    Raises CitationParseError if the string lacks a recognizable section
    marker AND no fallback `<code-name> <digits>` pattern is found, or if
    the code name cannot be resolved to a known California code.
    """
    raw = text.strip()
    if not raw:
        raise CitationParseError("empty citation")

    warnings: list[str] = []

    # Range warning is independent of whether we successfully parse below.
    if _RANGE_HINT_RE.search(raw):
        warnings.append(
            "citation appears to reference a range of sections; "
            "v1 resolves the first section only"
        )

    # Constitution citations have their own shape (article + section); route
    # them before the generic code parse.
    if _CONST_PREFIX_RE.search(raw):
        return _parse_constitution(raw, warnings)

    section_match = _SECTION_RE.search(raw)
    if section_match:
        code_raw = raw[: section_match.start()]
        # "former" sits either before the code name or between it and the
        # marker; strip it so the code name resolves, and remember it.
        former = False
        lead = _FORMER_LEAD_RE.match(code_raw)
        if lead:
            code_raw = code_raw[lead.end():]
            former = True
        trail = _FORMER_TRAIL_RE.search(code_raw)
        if trail:
            code_raw = code_raw[: trail.start()]
            former = True
        if former:
            warnings.append(FORMER_WARNING)
        section_num = section_match.group("section_num")
        rest = raw[section_match.end():]
    else:
        fallback = _FALLBACK_RE.match(raw)
        if not fallback:
            raise CitationParseError(
                f"no section marker (§ / section / sec.) found in: {raw!r}"
            )
        code_raw = fallback.group("code")
        section_num = fallback.group("section_num")
        rest = fallback.group("rest")
        former = False

    code_entry = resolve_code(code_raw)
    if code_entry is None:
        raise CitationParseError(
            f"could not resolve California code from: {code_raw!r}"
        )

    subsection_path = _LABEL_RE.findall(rest)

    if code_entry.confidence != "high":
        warnings.append(
            f"abbreviation '{code_raw.strip()}' is ambiguous; "
            f"resolved to {code_entry.law_code} ({code_entry.title})"
        )

    return ParsedCitation(
        raw=text,
        law_code=code_entry.law_code,
        section_num=section_num,
        subsection_path=subsection_path or None,
        confidence=code_entry.confidence,
        former=former,
        warnings=warnings,
    )


def _parse_constitution(raw: str, warnings: list[str]) -> ParsedCitation:
    """Parse a California Constitution citation, e.g. 'Cal. Const. art. XIII D, § 6'.

    A constitutional section is ambiguous without its article (every article
    has its own § 1, § 6, …), so both the article and a section are required;
    missing either raises CitationParseError with a targeted message.
    """
    art_match = _CONST_ARTICLE_RE.search(raw)
    if art_match is None:
        raise CitationParseError(
            "California Constitution citation requires an article "
            f"(e.g. 'Cal. Const. art. XIII D, § 6'); none found in: {raw!r}"
        )

    # Normalize to the DB's canonical form: uppercase, single-spaced
    # ("xiii  d" -> "XIII D").
    article = " ".join(art_match.group("article").upper().split())

    after = raw[art_match.end():]
    section_match = _SECTION_RE.search(after)
    if section_match is None:
        raise CitationParseError(
            f"California Constitution citation for article {article} requires a "
            f"section (e.g. '§ 6'); none found in: {raw!r}"
        )

    section_num = section_match.group("section_num")
    rest = after[section_match.end():]
    subsection_path = _LABEL_RE.findall(rest)

    return ParsedCitation(
        raw=raw,
        law_code="CONS",
        section_num=section_num,
        article=article,
        subsection_path=subsection_path or None,
        confidence="high",
        warnings=warnings,
    )


def try_parse(text: str) -> ParsedCitation | None:
    """Like parse(), but returns None on parse failure instead of raising."""
    try:
        return parse(text)
    except CitationParseError:
        return None
