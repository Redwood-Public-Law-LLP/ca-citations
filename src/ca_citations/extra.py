"""Pattern extractors that run beside the scanner in `extract`.

Written in 2026-09 for an index of advisory opinions, when the scanner lacked
several of these forms; consolidated here 2026-11-07. Since then the scanner has learned plural
lists, dash and "to ... inclusive" ranges, "commencing with", and Constitution
cites in prose, so for those forms these extractors are now a second pass:
`extract` merges overlapping matches of one (code, section) into a single
occurrence. CCR and AG-opinion citations exist only here.

**Section ranges.** "Sections 81000 to 91015, inclusive, of the Government
Code" — the Political Reform Act is routinely described this way. The pattern
was ported from an earlier TypeScript implementation. We record the FIRST
section of the range ("link first only"): storing every
section in a 10,000-section range would drown the citations table. The scanner
follows the same rule (`SpannedCitation.range_end`).

**"Chapter N (commencing with Section M)".** The standard California way of
naming a chapter. Ported from `RE_COMMENCING`. We record section M.

**Plural section lists and dash ranges.** In 2026-09 the scanner dropped every
plural reference, which cost 70% of the advisory-opinion index its citations:

    "Penal Code sections 330a and 330.1"
    "Health and Safety Code sections 8961.2 and 8961.3"
    "sections 9220.5 and 9221 of the Business and Professions Code"
    "Welfare and Institutions Code sections 4620-4636"   (en dash)
    "Gov. Code sections 54950-54962"                     (hyphen)

The scanner handles all five now; this extractor is
kept as a cross-check and for its corpus-default (`-bare`) pass.

**Constitutional provisions.** "article XIII A, section 1(b)" and the
run-together "article XIIIA". Proposition 13 and Proposition 218 are daily work
for California public agencies.

**California Code of Regulations.** FPPC advice letters cite 2 CCR § 18700
et seq. constantly, and AG opinions cite title 14 (CEQA Guidelines) regularly.
Patterns lifted from a CCR verification script, which is also a tool that can
VERIFY these — so unlike an unrecognized code, a CCR cite we extract is
checkable. Stored with
code `CCR-<title>`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ca_citations.codes import resolve_code
from ca_citations.reporter import REPORTER_RX, is_known
from ca_citations.scanner import _walk_backward_for_code, not_a_california_number

# --- California Code of Regulations -----------------------------------------
# Lifted from the CCR verification script. Three orderings occur in practice:
#   "14 CCR § 15332" / "14 Cal. Code Regs. § 15332" / "14 CA ADC § 15332"
#   "Cal. Code Regs., tit. 14, § 15332"
#   "tit. 14, § 15332"

_CCR_TITLE_FIRST = re.compile(
    r"""(?P<title>\d{1,2})\s*
        (?:C\.?C\.?R\.?|CCR|CA\s+ADC|Cal\.?\s*Code\s*Regs?\.?)\s*,?\s*
        (?:tit\.?\s*(?P=title)\s*,?\s*)?
        (?:§+|sec(?:tion)?s?\.?)\s*
        (?P<section>\d+(?:\.\d+)*[a-zA-Z]?)
    """,
    re.VERBOSE | re.IGNORECASE,
)
_CCR_CODE_FIRST = re.compile(
    r"""(?:Cal\.?\s*Code\s*Regs?\.?|C\.?C\.?R\.?|CCR|CA\s+ADC)\s*,?\s*
        tit\.?\s*(?P<title>\d{1,2})\s*,?\s*
        (?:§+|sec(?:tion)?s?\.?)\s*
        (?P<section>\d+(?:\.\d+)*[a-zA-Z]?)
    """,
    re.VERBOSE | re.IGNORECASE,
)
# Spelled out, as FPPC documents write it: "California Code of Regulations,
# title 2, section 18420.1" / "Code of Regulations, title 2, section 18420.1".
# Neither abbreviated pattern above admits the words "title" or "of
# Regulations", so this form was invisible until the FPPC load (2026-09-05).
_CCR_SPELLED = re.compile(
    r"""(?:California\s+)?Code\s+of\s+Regulations\s*,?\s*
        title\s+(?P<title>\d{1,2})\s*,?\s*
        (?:§+|sec(?:tion)?s?\.?)\s*
        (?P<section>\d+(?:\.\d+)*[a-zA-Z]?)
    """,
    re.VERBOSE | re.IGNORECASE,
)
_CCR_PATTERNS = (_CCR_CODE_FIRST, _CCR_TITLE_FIRST, _CCR_SPELLED)

# --- Statutory ranges and chapter references --------------------------------
# Ported from the earlier TypeScript patterns. CODE_NAME there is capitalized words
# ending in "Code"; we reuse codes.resolve_code to decide whether the captured
# name is one we know, which also declines "California Code of Regulations"
# (its name does not end in a bare "Code" the resolver recognizes).

_SECTION_NUM = r"\d+(?:\.\d+)*[a-zA-Z]?"
_CODE_NAME = r"(?:California\s+)?[A-Z][\w.&'-]*(?:\s+[\w.&'-]+)*?\s+Code"

_RANGE = re.compile(
    rf"Sections?\s+(?P<first>{_SECTION_NUM})\s+(?:to|through)\s+(?P<last>{_SECTION_NUM})"
    rf"(?:,?\s+inclusive)?(?:,?\s+of\s+the\s+(?P<code>{_CODE_NAME}))?",
    re.IGNORECASE,
)

_COMMENCING = re.compile(
    # The opener is optional and the marker may be "§": AG opinions write both
    # "Chapter 4 (commencing with Section 87100)" and the bare
    # "(commencing with § 500)".
    rf"(?:[Cc]hapter\s+(?P<chapter>\d+(?:\.\d+)?)\s*)?"
    rf"\(\s*commencing\s+with\s+(?:[Ss]ection|§)\s*(?P<section>{_SECTION_NUM})\s*\)"
    rf"(?:\s+of\s+(?:(?:Part|Division|Title|Chapter|Article)\s+[\w.]+\s+of\s+)*"
    rf"the\s+(?P<code>{_CODE_NAME}))?",
)


# --- Attorney General opinion citations (the in-corpus graph) --------------
#
# "62 Ops.Cal.Atty.Gen. 822" and its five observed typo variants. Same
# whitelist approach as the index parser: match the shape loosely, then verify
# the reporter token against known spellings rather than loosening the regex
# until it accepts anything.
#
# freelawproject/reporters-db carries this reporter too ("Ops.Cal.Atty.Gen.",
# cite_type "specialty"), which is why eyecite can read AG citations out of the
# box. We keep our own matcher because it already handles OAG's typos, which a
# canonical reporter database has no reason to.

_AG_CITE = re.compile(
    rf"(?P<volume>\d{{1,3}})\s*(?P<reporter>{REPORTER_RX})\s*(?P<page>\d{{1,4}})\b"
)

# Page-break furniture. When a citation spans a page break, pymupdf interleaves
# the running footer -- a footnote number plus the opinion's own file number --
# into the middle of it:
#
#   "...as does a member of a city council (37 2. 90-892 Ops.Cal.Atty.Gen. 21..."
#                                              ^^^^^^^^^ injected footer
#
# The real citation is 37 Ops.Cal.Atty.Gen. 21; without stripping this, "892"
# reads as the volume. Observed 14 times in the corpus, all yielding impossible
# volumes -- so the damage was lost citations, not false ones, but they are
# recoverable. The same artifact can split a statutory citation, so this is
# worth doing before any extraction, not just this one.
_PAGE_FURNITURE = re.compile(r"\b\d{1,2}\.\s*\d{2}-\d{3,4}\s+(?=[A-Za-z])")


def strip_page_furniture(text: str) -> str:
    """Remove interleaved running-footer text from extracted PDF prose."""
    return _PAGE_FURNITURE.sub("", text)


@dataclass(frozen=True)
class AgCite:
    """One occurrence of an AG opinion citation, with where it sat."""

    volume: int
    page: int
    # Span in the page-furniture-stripped text, so the caller can look at what
    # follows the citation -- an explanatory parenthetical, if there is one.
    start: int
    end: int


def find_ag_citations(text: str) -> list[AgCite]:
    """Return every AG opinion citation occurrence in `text`.

    NOT deduplicated: one entry per occurrence, because the caller counts them
    to get the `depth` figure, mirroring CourtListener's OpinionsCited.depth.
    """
    out: list[AgCite] = []
    for m in _AG_CITE.finditer(strip_page_furniture(text)):
        if is_known(m.group("reporter")):
            out.append(
                AgCite(int(m.group("volume")), int(m.group("page")), m.start(), m.end())
            )
    return out


# --- Plural section lists and dash ranges -----------------------------------

# A run of section numbers joined by commas, "and"/"or", or a dash. Section
# numbers may carry a letter suffix (Penal Code 330a) and decimal parts.
_NUM = r"\d+(?:\.\d+)*[a-zA-Z]{0,2}"
_NUM_LIST = rf"{_NUM}(?:\s*(?:,|and|or|through|to|[-\u2010-\u2015])\s*{_NUM})*"

_SECTION_LIST = re.compile(
    rf"(?:§§?|\bsections?\b|\bsecs?\.)\s*(?P<nums>{_NUM_LIST})",
    re.IGNORECASE,
)
# A dash between two numbers means a range: record the first only, as with
# _RANGE. A comma or "and" means a list: record every member.
_DASH = re.compile(r"[-\u2010-\u2015]|\bto\b|\bthrough\b", re.IGNORECASE)
_SPLIT = re.compile(r"\s*(?:,|\band\b|\bor\b)\s*", re.IGNORECASE)

# "of the <Code>" trailing a section reference.
_TRAILING_CODE = re.compile(rf"^[\s,]*(?:of\s+)?(?:the\s+)?(?P<code>{_CODE_NAME})",
                            re.IGNORECASE)

# --- California Constitution ------------------------------------------------
# "article XIII A, section 1(b)", "article XIIIA", "art. XIII D, § 6".
_ROMAN = r"[IVXL]+(?:\s*[A-D])?"

# Two guards, both learned from false positives in the live corpus:
#
# 1. The spelled-out "article" must be followed by WHITESPACE, never a period.
#    "...prescribed by this article. If after readvertising..." was matching as
#    "article I" -- the sentence-ending period read as an abbreviation dot and
#    the next word's leading "I" read as a Roman numeral. The abbreviated
#    "art." keeps its period, because there the period IS the abbreviation.
# 2. A trailing \b after the numeral. Without it, "article. It is not the
#    intent" yields "I" from "It". With it, the numeral must end at a real
#    word boundary, so "If"/"It"/"In" can no longer contribute an "I".
_CONST = re.compile(
    rf"\b(?:article\s+|arts?\.\s*)(?P<article>{_ROMAN})\b"
    rf"(?:\s*,?\s*(?:§+|sec(?:tion)?s?\.?)\s*(?P<section>\d+(?:\.\d+)*))?",
)


@dataclass(frozen=True)
class ExtraCite:
    code: str          # 'GOV', 'CCR-14', ...
    section: str
    form: str          # 'ccr' | 'range' | 'commencing'
    verifiable: bool   # can a verification tool check it?
    raw: str
    # Character span of the match in the text it was found in. Needed because
    # depth counts OCCURRENCES (overlapping matches from two extractors are one
    # occurrence, not two), and because a quotation or an explanatory
    # parenthetical is identified by what follows the citation -- see
    # shared/citations/context.py.
    start: int = 0
    end: int = 0


def find_ccr(text: str) -> list[ExtraCite]:
    """CCR cites. `verifiable=True`, except titles 6 and 24 (see find_ccr)."""
    out: dict[tuple[str, str], ExtraCite] = {}
    for pat in _CCR_PATTERNS:
        for m in pat.finditer(text):
            title = int(m.group("title"))
            # Title 6 is empty and Title 24 is published separately; the CCR
            # skill cannot verify either, so flag them honestly.
            key = (f"CCR-{title}", m.group("section"))
            out.setdefault(
                key,
                ExtraCite(
                    code=key[0], section=key[1], form="ccr",
                    verifiable=title not in (6, 24), raw=m.group(0).strip(),
                    start=m.start(), end=m.end(),
                ),
            )
    return list(out.values())


def find_ranges(text: str, default_code: str | None = None) -> list[ExtraCite]:
    """Section ranges. Records the FIRST section only -- see module docstring."""
    out: list[ExtraCite] = []
    for m in _RANGE.finditer(text):
        code = _resolve(m.group("code"), default_code)
        if code:
            out.append(
                ExtraCite(code=code, section=m.group("first"), form="range",
                          verifiable=True, raw=m.group(0).strip(),
                          start=m.start(), end=m.end())
            )
    return out


def find_commencing(text: str, default_code: str | None = None) -> list[ExtraCite]:
    """'Chapter N (commencing with Section M)'. Records section M.

    The code name can sit on either side of the parenthetical:

        "Chapter 4 (commencing with Section 87100) of the Government Code"
        "the Harbors and Navigation Code (commencing with § 500)"

    so a trailing "of the X Code" is tried first and a backward walk second.
    """
    out: list[ExtraCite] = []
    for m in _COMMENCING.finditer(text):
        code = _resolve(m.group("code"), None)
        if code is None:
            code = _explicit_code_before(text, m.start())
        if code is None:
            code = default_code
        if code:
            out.append(
                ExtraCite(code=code, section=m.group("section"), form="commencing",
                          verifiable=True, raw=m.group(0).strip(),
                          start=m.start(), end=m.end())
            )
    return out


def find_section_lists(text: str, default_code: str | None = None) -> list[ExtraCite]:
    """Plural section references and dash ranges. See the module docstring.

    `default_code` is used only when no code name can be found before or after
    the list -- the same rule as the scanner's `default_law_code`. The caller
    (extract) is responsible for confining default-attributed sections to a
    range it can justify.
    """
    out: list[ExtraCite] = []
    for m in _SECTION_LIST.finditer(text):
        nums = m.group("nums")
        if not _SPLIT.search(nums) and not _DASH.search(nums):
            continue  # singular -- the scanner already has it
        marker = text[m.start():m.start("nums")].strip()
        if not_a_california_number(text, marker, m.start("nums")):
            continue  # "section 2,235", "§ 9-318": see the scanner

        # Resolve the code: prefer a trailing "of the X Code", else walk back.
        code = None
        fwd = _TRAILING_CODE.match(text[m.end():])
        if fwd:
            entry = resolve_code(fwd.group("code"))
            code = entry.law_code if entry else None
        if code is None:
            code = _explicit_code_before(text, m.start())
        if code is None:
            code = default_code
        if code is None:
            continue  # never guess a code (precision beats recall)

        if _DASH.search(nums) and not _SPLIT.search(nums):
            first = re.match(_NUM, nums.strip())
            if first:
                out.append(ExtraCite(code, first.group(0), "range", True,
                                     m.group(0), m.start(), m.end()))
            continue

        for part in _SPLIT.split(nums):
            part = part.strip()
            if not part:
                continue
            if _DASH.search(part):  # a range nested inside a list
                first = re.match(_NUM, part)
                if first:
                    out.append(ExtraCite(code, first.group(0), "range", True,
                                         part, m.start(), m.end()))
                continue
            if re.fullmatch(_NUM, part):
                out.append(ExtraCite(code, part, "section-list", True,
                                     m.group(0), m.start(), m.end()))
    return out


def find_constitution(text: str) -> list[ExtraCite]:
    """California Constitution articles, with a section where one is given.

    Stored under code **'CONS'**, matching the scanner's `law_code` for the
    California Constitution. An earlier draft used 'CONST' and produced two
    codes for one authority in the same table -- which quietly breaks the whole
    point of the citations table, since "every opinion citing article XIII A"
    would then have to know both spellings. Section is 'XIII A' or 'XIII A-1'.
    Prop 13 (art. XIII A) and Prop 218 (art. XIII D) are core practice here.
    """
    out: list[ExtraCite] = []
    for m in _CONST.finditer(text):
        art = re.sub(r"\s+", " ", m.group("article").upper()).strip()
        # "XIIIA" written without a space is the same article as "XIII A".
        art = re.sub(r"^([IVXL]+)([A-D])$", r"\1 \2", art)
        section = m.group("section")
        out.append(
            ExtraCite(
                code="CONS",
                section=f"{art}-{section}" if section else art,
                form="constitution", verifiable=True, raw=m.group(0).strip(),
                start=m.start(), end=m.end(),
            )
        )
    return out


_ABBREV_RE = re.compile(r"^[A-Z][A-Z&.\s]{1,12}$")   # "CCP", "B&P", "P.U.C."


def named_code_is_explicit(code_text: str) -> bool:
    """Is this run of prose an explicit code name, not an English word?

    The code resolver accepts the bare words "family", "elections",
    "water", "education", "penal" and "civil" as code names, so the scanner's
    backward walk turns "...his immediate family. Section 82029..." into a
    Family Code citation and "...statewide special elections. (section
    85305)..." into an Elections Code one. Measured on the FPPC letters
    2026-09-06: 303 "Family Code" cites, essentially all of them this.

    An explicit code name either contains the word "Code" ("Family Code",
    "Civ.Code", "Gov't Code") or is an all-caps abbreviation ("CCP", "PUC").
    A single lowercase or capitalized English word is neither, and its
    section is left to the corpus default (which, for the FPPC, is the
    Political Reform Act -- where 82029 and 85305 actually live).
    Reported upstream as a resolver bug; this is the local guard.
    """
    t = code_text.strip().rstrip(".,;:")
    if re.search(r"\bcode\b", t, re.IGNORECASE):
        return True
    return bool(_ABBREV_RE.match(t))


def _explicit_code_before(text: str, end: int) -> str | None:
    """law_code of an explicit code name ending at `end`, else None.

    The scanner's backward walk finds the longest run of words before `end`
    that resolves to a code; `named_code_is_explicit` then refuses plain
    English words the resolver happens to know ("family", "elections").
    """
    back = _walk_backward_for_code(text, end)
    if back is None:
        return None
    entry, start = back
    if not named_code_is_explicit(text[start:end]):
        return None
    return entry.law_code


def _resolve(name: str | None, default_code: str | None) -> str | None:
    """Map a captured code name to its abbreviation, else fall back."""
    if name:
        entry = resolve_code(name)
        return entry.law_code if entry else None
    return default_code
