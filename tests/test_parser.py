"""Tests for citation.parser."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ca_citations.parser import CitationParseError, parse, try_parse


def _load_corpus() -> list[dict]:
    path = Path(__file__).parent / "fixtures" / "citations_corpus.json"
    return json.loads(path.read_text())


CORPUS = _load_corpus()


@pytest.mark.parametrize("entry", CORPUS, ids=[c["id"] for c in CORPUS])
def test_corpus_parses_correctly(entry: dict) -> None:
    """Every corpus entry must parse to its expected (law_code, section_num,
    subsection_path, confidence)."""
    result = parse(entry["input"])
    assert result.law_code == entry["law_code"], (
        f"law_code mismatch for {entry['id']!r}: "
        f"got {result.law_code!r}, expected {entry['law_code']!r}"
    )
    assert result.section_num == entry["section_num"], (
        f"section_num mismatch for {entry['id']!r}: "
        f"got {result.section_num!r}, expected {entry['section_num']!r}"
    )
    assert result.subsection_path == entry["subsection_path"], (
        f"subsection_path mismatch for {entry['id']!r}: "
        f"got {result.subsection_path!r}, expected {entry['subsection_path']!r}"
    )
    assert result.confidence == entry["confidence"], (
        f"confidence mismatch for {entry['id']!r}: "
        f"got {result.confidence!r}, expected {entry['confidence']!r}"
    )


@pytest.mark.parametrize(
    "bad_input",
    [
        "",
        "   ",
        "Some random text",
        "§ 1714",  # no code
        "Cal. § 1714",  # "Cal." alone is not a code name
        "Civil Code",  # no section
    ],
)
def test_unparseable_inputs_raise(bad_input: str) -> None:
    with pytest.raises(CitationParseError):
        parse(bad_input)


def test_try_parse_returns_none_for_bad_input() -> None:
    assert try_parse("not a citation") is None


def test_ambiguous_abbreviation_carries_warning() -> None:
    result = parse("CC § 1714")
    assert result.confidence == "medium"
    assert any("ambiguous" in w.lower() for w in result.warnings)


def test_range_marker_warns() -> None:
    result = parse("Cal. Civ. Code §§ 1714.1 through 1714.5")
    assert any("range" in w.lower() for w in result.warnings)


def test_raw_preserved() -> None:
    raw = "Cal. Civ. Code § 1714(a)"
    result = parse(raw)
    assert result.raw == raw


# --- California Constitution -------------------------------------------------


@pytest.mark.parametrize(
    "raw, article, section_num, subsection_path",
    [
        ("Cal. Const. art. XIII D, § 6", "XIII D", "6", None),
        ("Cal. Const. art. XIII D, § 6(a)", "XIII D", "6", ["a"]),
        ("California Constitution, article XIII D, section 6", "XIII D", "6", None),
        ("Cal. Const. art. I, § 7", "I", "7", None),
        ("Cal. Const. art. X A, § 1", "X A", "1", None),
        # No comma between article and section: the optional sub-article letter
        # must NOT swallow the leading "s" of "section".
        ("Cal. Const. art. XIII D section 6", "XIII D", "6", None),
        # Lowercase / extra-spaced article normalizes to the DB's canonical form.
        ("cal. const. art. xiii  d, § 6", "XIII D", "6", None),
    ],
)
def test_constitution_citations_parse(
    raw: str, article: str, section_num: str, subsection_path: list[str] | None
) -> None:
    result = parse(raw)
    assert result.law_code == "CONS"
    assert result.article == article
    assert result.section_num == section_num
    assert result.subsection_path == subsection_path
    assert result.confidence == "high"


def test_code_citation_has_no_article() -> None:
    assert parse("Cal. Civ. Code § 1714(a)").article is None


def test_constitution_without_article_raises() -> None:
    with pytest.raises(CitationParseError, match="requires an article"):
        parse("Cal. Const. § 6")


def test_constitution_without_section_raises() -> None:
    with pytest.raises(CitationParseError, match="requires a section"):
        parse("Cal. Const. art. XIII D")


# --- Letter-suffixed sections (e.g. HSC § 5473a) -----------------------------


@pytest.mark.parametrize(
    "raw, section_num, subsection_path",
    [
        ("Health & Safety Code § 5473a", "5473a", None),
        ("HSC § 5473a(b)", "5473a", ["b"]),          # suffix + subdivision
        ("Pen. Code § 1203.1bb", "1203.1bb", None),  # two-letter suffix
        ("HSC § 1317.9a", "1317.9a", None),          # letter after a decimal
        ("Rev. & Tax. Code § 30459.2A", "30459.2A", None),  # uppercase suffix
        # Regressions: no suffix must still parse exactly as before.
        ("HSC § 5473", "5473", None),
        ("HSC § 5473.1", "5473.1", None),
        ("Cal. Civ. Code § 1714(a)", "1714", ["a"]),  # subdivision, not suffix
        ("Cal. Civ. Code § 1714(a)(1)", "1714", ["a", "1"]),
    ],
)
def test_letter_suffix_preserved(
    raw: str, section_num: str, subsection_path: list[str] | None
) -> None:
    result = parse(raw)
    assert result.section_num == section_num
    assert result.subsection_path == subsection_path


def test_letter_suffix_does_not_collapse_to_base() -> None:
    """The core of the 2026-06-04 bug: § 5473a must NOT parse to '5473'."""
    assert parse("HSC § 5473a").section_num != "5473"
    assert parse("HSC § 5473a").section_num == "5473a"


def test_plural_section_marker_parses() -> None:
    """`sections` (plural) used to fail _SECTION_RE, fall through to the
    fallback, and die on resolve_code('Penal Code sections')."""
    result = parse("Penal Code sections 330a and 330.1")
    assert result.law_code == "PEN"
    assert result.section_num == "330a"


def test_plural_abbreviated_section_marker_parses() -> None:
    result = parse("Gov. Code secs. 54950 and 54953")
    assert result.law_code == "GOV"
    assert result.section_num == "54950"


def test_plural_list_is_not_warned_as_a_range() -> None:
    """A list is not a range; the scanner expands lists, so the range warning
    would be misleading here."""
    result = parse("Cal. Civ. Code §§ 1714, 1715")
    assert not any("range" in w.lower() for w in result.warnings)


# --- "former" sections (2026-10-30 review, item 3) ---------------------------
# "former section 6254" used to resolve silently to the CURRENT § 6254, linking
# an old opinion to text it never construed.


@pytest.mark.parametrize(
    "raw",
    [
        "former Gov. Code section 6254",
        "Former Government Code § 6254",
        "Gov. Code, former § 6254",
        "Gov. Code former section 6254",
    ],
)
def test_former_is_flagged_and_code_still_resolves(raw: str) -> None:
    parsed = parse(raw)
    assert (parsed.law_code, parsed.section_num) == ("GOV", "6254")
    assert parsed.former is True
    assert any("FORMER" in w for w in parsed.warnings)


def test_current_cite_is_not_former() -> None:
    parsed = parse("Gov. Code § 7920.000")
    assert parsed.former is False
    assert not parsed.warnings
