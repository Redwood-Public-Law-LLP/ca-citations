"""California law-code abbreviation map.

A hardcoded canonical map covering Bluebook, California Style Manual, and
informal lawyer abbreviations is the source of truth for what users will type.
There is no runtime augmentation from capublic.codes_tbl (an earlier version of
this docstring claimed one; it was never built). Informal cite forms like 'CCP'
or 'CC' will never appear in the DB and must be hardcoded anyway.

Lookup is case-insensitive and tolerant of internal whitespace, periods, and
ampersands. Callers should pass the raw code-name token (the run of words
before the section marker) and let `resolve_code` strip the noise. Keys are
run through the same normalizer as lookups, so a key and a citation that differ
only in noise ("&" vs "and", "Code of Civil Procedure" vs "Code Civil
Procedure") always meet.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

Confidence = Literal["high", "medium", "low"]

# Canonical mapping. Keys are normalized (lowercased, ascii-only, single-spaced,
# no punctuation). Values are the law_code abbreviation used in
# capublic.law_section_tbl.law_code, plus a confidence band and a human title.
#
# Confidence bands:
#   high   — the form is unambiguous in CA legal writing
#   medium — the form is ambiguous (e.g. "CC" colloquially means Civil Code in
#            California but means something else in federal contexts); the
#            parser should surface a warning
#
# Sources cross-checked: the Legislature's PUBINFO codes table (the runtime
# authority), California Style Manual 4th ed. table of code abbreviations,
# and Bluebook T1.3.


@dataclass(frozen=True)
class CodeEntry:
    law_code: str
    title: str
    confidence: Confidence


_CANONICAL: dict[str, CodeEntry] = {
    # Business & Professions Code
    "business and professions code": CodeEntry("BPC", "Business and Professions Code", "high"),
    "bus and prof code": CodeEntry("BPC", "Business and Professions Code", "high"),
    "bus prof code": CodeEntry("BPC", "Business and Professions Code", "high"),
    "bpc": CodeEntry("BPC", "Business and Professions Code", "high"),
    # California Constitution. Normalizes to "const" / "constitution" since
    # "cal"/"california" are noise words. Unlike a code, a CONS citation also
    # needs an article (parsed separately); this entry resolves the code name
    # and full title only.
    "constitution": CodeEntry("CONS", "California Constitution", "high"),
    "const": CodeEntry("CONS", "California Constitution", "high"),
    # Civil Code
    "civil code": CodeEntry("CIV", "Civil Code", "high"),
    "civ code": CodeEntry("CIV", "Civil Code", "high"),
    "civ": CodeEntry("CIV", "Civil Code", "high"),
    "cc": CodeEntry("CIV", "Civil Code", "medium"),
    # Code of Civil Procedure
    "code of civil procedure": CodeEntry("CCP", "Code of Civil Procedure", "high"),
    "code civ proc": CodeEntry("CCP", "Code of Civil Procedure", "high"),
    "civ proc code": CodeEntry("CCP", "Code of Civil Procedure", "high"),
    "civil procedure code": CodeEntry("CCP", "Code of Civil Procedure", "high"),
    "ccp": CodeEntry("CCP", "Code of Civil Procedure", "high"),
    # Commercial Code
    "commercial code": CodeEntry("COM", "Commercial Code", "high"),
    "com code": CodeEntry("COM", "Commercial Code", "high"),
    "com": CodeEntry("COM", "Commercial Code", "high"),
    # Corporations Code
    "corporations code": CodeEntry("CORP", "Corporations Code", "high"),
    "corp code": CodeEntry("CORP", "Corporations Code", "high"),
    "corp": CodeEntry("CORP", "Corporations Code", "high"),
    # Education Code
    "education code": CodeEntry("EDC", "Education Code", "high"),
    "educ code": CodeEntry("EDC", "Education Code", "high"),
    "ed code": CodeEntry("EDC", "Education Code", "high"),
    "edc": CodeEntry("EDC", "Education Code", "high"),
    # Elections Code
    "elections code": CodeEntry("ELEC", "Elections Code", "high"),
    "elec code": CodeEntry("ELEC", "Elections Code", "high"),
    "elec": CodeEntry("ELEC", "Elections Code", "high"),
    # Evidence Code
    "evidence code": CodeEntry("EVID", "Evidence Code", "high"),
    "evid code": CodeEntry("EVID", "Evidence Code", "high"),
    "evid": CodeEntry("EVID", "Evidence Code", "high"),
    # Family Code
    "family code": CodeEntry("FAM", "Family Code", "high"),
    "fam code": CodeEntry("FAM", "Family Code", "high"),
    "fam": CodeEntry("FAM", "Family Code", "high"),
    # Financial Code
    "financial code": CodeEntry("FIN", "Financial Code", "high"),
    "fin code": CodeEntry("FIN", "Financial Code", "high"),
    "fin": CodeEntry("FIN", "Financial Code", "high"),
    # Fish and Game Code
    "fish and game code": CodeEntry("FGC", "Fish and Game Code", "high"),
    "fish game code": CodeEntry("FGC", "Fish and Game Code", "high"),
    "fgc": CodeEntry("FGC", "Fish and Game Code", "high"),
    "fish and g code": CodeEntry("FGC", "Fish and Game Code", "high"),  # CSM
    # Food and Agricultural Code
    "food and agricultural code": CodeEntry("FAC", "Food and Agricultural Code", "high"),
    "food agric code": CodeEntry("FAC", "Food and Agricultural Code", "high"),
    "fac": CodeEntry("FAC", "Food and Agricultural Code", "high"),
    "food and agr code": CodeEntry("FAC", "Food and Agricultural Code", "high"),  # CSM
    "food and agriculture code": CodeEntry("FAC", "Food and Agricultural Code", "high"),
    # Government Code
    "government code": CodeEntry("GOV", "Government Code", "high"),
    "govt code": CodeEntry("GOV", "Government Code", "high"),
    "gov code": CodeEntry("GOV", "Government Code", "high"),
    "gov": CodeEntry("GOV", "Government Code", "high"),
    # Harbors and Navigation Code
    "harbors and navigation code": CodeEntry("HNC", "Harbors and Navigation Code", "high"),
    "harb nav code": CodeEntry("HNC", "Harbors and Navigation Code", "high"),
    "hnc": CodeEntry("HNC", "Harbors and Navigation Code", "high"),
    # Health and Safety Code
    "health and safety code": CodeEntry("HSC", "Health and Safety Code", "high"),
    "health safety code": CodeEntry("HSC", "Health and Safety Code", "high"),
    "hsc": CodeEntry("HSC", "Health and Safety Code", "high"),
    "health and saf code": CodeEntry("HSC", "Health and Safety Code", "high"),  # CSM
    # Insurance Code
    "insurance code": CodeEntry("INS", "Insurance Code", "high"),
    "ins code": CodeEntry("INS", "Insurance Code", "high"),
    "ins": CodeEntry("INS", "Insurance Code", "high"),
    # Labor Code
    "labor code": CodeEntry("LAB", "Labor Code", "high"),
    "lab code": CodeEntry("LAB", "Labor Code", "high"),
    "lab": CodeEntry("LAB", "Labor Code", "high"),
    # Military and Veterans Code
    "military and veterans code": CodeEntry("MVC", "Military and Veterans Code", "high"),
    "mil vet code": CodeEntry("MVC", "Military and Veterans Code", "high"),
    "mvc": CodeEntry("MVC", "Military and Veterans Code", "high"),
    # Penal Code
    "penal code": CodeEntry("PEN", "Penal Code", "high"),
    "pen code": CodeEntry("PEN", "Penal Code", "high"),
    "pen": CodeEntry("PEN", "Penal Code", "high"),
    "pc": CodeEntry("PEN", "Penal Code", "medium"),
    # Probate Code
    "probate code": CodeEntry("PROB", "Probate Code", "high"),
    "prob code": CodeEntry("PROB", "Probate Code", "high"),
    "prob": CodeEntry("PROB", "Probate Code", "high"),
    # Public Contract Code
    "public contract code": CodeEntry("PCC", "Public Contract Code", "high"),
    "pub cont code": CodeEntry("PCC", "Public Contract Code", "high"),
    "pcc": CodeEntry("PCC", "Public Contract Code", "high"),
    "pub contract code": CodeEntry("PCC", "Public Contract Code", "high"),  # CSM
    # Public Resources Code
    "public resources code": CodeEntry("PRC", "Public Resources Code", "high"),
    "pub res code": CodeEntry("PRC", "Public Resources Code", "high"),
    "prc": CodeEntry("PRC", "Public Resources Code", "high"),
    "pub resources code": CodeEntry("PRC", "Public Resources Code", "high"),  # CSM
    "pub resource code": CodeEntry("PRC", "Public Resources Code", "high"),
    # Public Utilities Code
    "public utilities code": CodeEntry("PUC", "Public Utilities Code", "high"),
    "pub util code": CodeEntry("PUC", "Public Utilities Code", "high"),
    "puc": CodeEntry("PUC", "Public Utilities Code", "high"),
    "pub utilities code": CodeEntry("PUC", "Public Utilities Code", "high"),
    "pub utils code": CodeEntry("PUC", "Public Utilities Code", "high"),
    # Revenue and Taxation Code
    "revenue and taxation code": CodeEntry("RTC", "Revenue and Taxation Code", "high"),
    "rev tax code": CodeEntry("RTC", "Revenue and Taxation Code", "high"),
    "rev and tax code": CodeEntry("RTC", "Revenue and Taxation Code", "high"),
    "rtc": CodeEntry("RTC", "Revenue and Taxation Code", "high"),
    # Streets and Highways Code
    "streets and highways code": CodeEntry("SHC", "Streets and Highways Code", "high"),
    "sts hwy code": CodeEntry("SHC", "Streets and Highways Code", "high"),
    "shc": CodeEntry("SHC", "Streets and Highways Code", "high"),
    "sts and hy code": CodeEntry("SHC", "Streets and Highways Code", "high"),  # CSM
    "sts and high code": CodeEntry("SHC", "Streets and Highways Code", "high"),  # Bluebook
    # Unemployment Insurance Code
    "unemployment insurance code": CodeEntry("UIC", "Unemployment Insurance Code", "high"),
    "unemp ins code": CodeEntry("UIC", "Unemployment Insurance Code", "high"),
    "uic": CodeEntry("UIC", "Unemployment Insurance Code", "high"),
    # Vehicle Code
    "vehicle code": CodeEntry("VEH", "Vehicle Code", "high"),
    "veh code": CodeEntry("VEH", "Vehicle Code", "high"),
    "veh": CodeEntry("VEH", "Vehicle Code", "high"),
    "vc": CodeEntry("VEH", "Vehicle Code", "medium"),
    # Water Code
    "water code": CodeEntry("WAT", "Water Code", "high"),
    "wat code": CodeEntry("WAT", "Water Code", "high"),
    "wat": CodeEntry("WAT", "Water Code", "high"),
    # Welfare and Institutions Code
    "welfare and institutions code": CodeEntry(
        "WIC", "Welfare and Institutions Code", "high"
    ),
    "welf inst code": CodeEntry("WIC", "Welfare and Institutions Code", "high"),
    "wic": CodeEntry("WIC", "Welfare and Institutions Code", "high"),
}

# Words to strip from the candidate code-name before lookup. "Cal." and
# "California" are the common "of California" markers; "the" handles spelled-out
# forms like "the Civil Code"; "of" makes "Code of Civil Procedure" and "Code
# Civ. Proc." differ only in abbreviation, not in shape.
_NOISE_WORDS = {"cal", "california", "the", "of"}

# Conjunction inside a code name. "&" and "and" are interchangeable ("Bus. &
# Prof." / "Bus. and Prof." / "Bus. Prof."), so both are dropped — but only
# BETWEEN two other words. A leading or trailing "and" is kept, so it fails the
# lookup: in prose, "the Civil Code and section 1714 of the Penal Code" must not
# let the scanner's backward walk read "Civil Code and" as a code name.
_CONJUNCTIONS = {"and"}

_NORMALIZE_RE = re.compile(r"[^\w&]+", re.UNICODE)


def _normalize(text: str) -> str:
    """Lowercase, strip punctuation, drop noise words, collapse whitespace.

    Examples:
      "Cal. Civ. Code"           -> "civ code"
      "California Civil"         -> "civil"
      "Civ. Proc. Code,"         -> "civ proc code"
      "Bus. & Prof. Code"        -> "bus prof code"
      "Business and Professions" -> "business professions"
      "Code of Civil Procedure"  -> "code civil procedure"
    """
    text = text.lower()
    # Strip apostrophes (curly + straight) so "gov't" becomes "govt", not "gov t".
    text = text.replace("\u2019", "").replace("'", "")
    # "&" becomes the word "and" so it obeys the interior-only rule below.
    text = text.replace("&", " and ")
    text = _NORMALIZE_RE.sub(" ", text)
    parts = [w for w in text.split() if w and w not in _NOISE_WORDS]
    if len(parts) > 2:
        parts = [parts[0]] + [w for w in parts[1:-1] if w not in _CONJUNCTIONS] + [
            parts[-1]
        ]
    return " ".join(parts)


# Lookup table: every _CANONICAL key run through _normalize, so a key spelled
# "fish and game code" and a citation spelled "Fish & Game Code" land on the
# same string. Building it from the literal keys keeps _CANONICAL readable.
_LOOKUP: dict[str, CodeEntry] = {}
for _key, _entry in _CANONICAL.items():
    _norm_key = _normalize(_key)
    _existing = _LOOKUP.get(_norm_key)
    if _existing is not None and _existing != _entry:  # pragma: no cover
        raise RuntimeError(f"code-name key collision after normalization: {_key!r}")
    _LOOKUP[_norm_key] = _entry

# One-word forms that resolve when "Code" is omitted ("Penal 187").
_BARE_TITLE_WORDS = {
    "civil", "penal", "vehicle", "evidence", "family", "labor", "education",
    "elections", "insurance", "commercial", "corporations", "probate", "water",
    "government",
}


def resolve_code(raw: str) -> CodeEntry | None:
    """Resolve a raw code-name token (run of words before the section marker).

    Returns None if no match. Caller is responsible for surfacing a warning
    based on entry.confidence.
    """
    norm = _normalize(raw)
    if not norm:
        return None
    if norm in _LOOKUP:
        return _LOOKUP[norm]
    # Heuristic: single-word collapse — "civil" alone resolves to CIV, "penal"
    # alone to PEN, etc.
    if norm in _BARE_TITLE_WORDS:
        return _LOOKUP.get(f"{norm} code")
    return None


def all_canonical_keys() -> list[str]:
    """Return all known canonical lookup keys (for tests / introspection)."""
    return sorted(_CANONICAL.keys())
