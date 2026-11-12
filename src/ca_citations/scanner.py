"""Scan free prose for California statutory and constitutional citations.

For each section anchor (`§`, `§§`, `section`, `sec.`) followed by digits we
identify what it cites in priority order:

1. Constitution: an "art. XIII D," immediately before the marker, or an "of
   article XIII D" right after the number. Attributed to the California
   Constitution when "Const." / "Constitution" is named with it, or anywhere
   earlier in the text; otherwise the anchor is dropped (an article of a city
   charter or a contract is not something this tool can resolve).
2. Backward: the longest run of tokens *before* the marker that resolves to a
   known code — handles "Cal. Civ. Code § 1714", "Penal Code § 187".
3. Forward: an "of the <Code>" phrase *after* the section number — handles the
   dominant CA drafting form "Section 241 of the Public Utilities Code", which
   the backward walk alone cannot see.
4. "Id." / "ibid." right before the marker: the previous citation's code.
5. Default: `default_law_code`, if the caller supplied one. This catches truly
   bare intra-code pointers ("as defined in subdivision (a) of Section 56134").
6. The document's own default: "All further statutory references are to the
   Government Code" — the California convention for bare "§ 54953" cites in
   opinions and briefs.
7. Carry-forward: the most recent code cited or named in the text before the
   anchor ("... the Government Code. Section 54953 requires ...").

(4), (6), and (7) come from context, so they carry a warning; (4) and (7) are
guesses and are emitted at medium confidence. Each citation's `attribution`
says which step found its code ("named" for 1-3). Steps 5-7 are skipped when the
marker directly follows some other source ("Stats. 2023, ch. 286, §",
"42 U.S.C. §", "Guidelines, §"): that anchor cites something this tool cannot
resolve, and guessing a code for it produced a wrong citation. With nothing
found, the anchor is dropped.

A "former" immediately before the citation sets `former=True`: the current text
at that number is not the text the citing document relied on.
"""

from __future__ import annotations

import re
from bisect import bisect_left
from typing import Literal

from ca_citations.codes import CodeEntry, resolve_code
from ca_citations.codes import _normalize as _normalize_code_name
from ca_citations.models import Attribution, Confidence, SpannedCitation
from ca_citations.parser import (
    _LABEL_RE,
    _SECTION_NUM,
    FORMER_WARNING,
    try_parse,
)

# Section anchor in free prose. Same shape as parser._SECTION_RE but with
# tighter word-boundaries on the spelled-out forms. The number reuses
# parser._SECTION_NUM so a lettered section keeps its suffix ("330a", not
# "330") — the parser treats those as distinct provisions, and the scanner
# used to truncate them.
_ANCHOR_RE = re.compile(
    r"(?P<marker>§{1,2}|\b(?:sections?|secs?\.))\s*(?P<num>" + _SECTION_NUM + r")",
    re.IGNORECASE,
)

# Markers that announce more than one section: "§§", "sections", "secs.".
_PLURAL_MARKERS = {"§§", "sections", "secs.", "secs"}

# Continuation of an enumerated list after a section number: ", 330.1",
# " and 330.1", ", and 330.1", " & 330.1". Only honoured after a plural
# marker — a comma-then-number after a singular "section" is far more often a
# reporter cite or a year than a second section.
_LIST_CONT_RE = re.compile(
    r"(?:\s*,\s*(?:(?:and|&)\s+)?|\s+(?:and|&)\s+)(?P<num>" + _SECTION_NUM + r")",
    re.IGNORECASE,
)

# Continuation of a range: "-54962", "–4636", " to 4636", " through 4636".
# Honoured after singular and plural markers alike; California section numbers
# do not contain hyphens, so a dash between two numbers is unambiguous.
_RANGE_CONT_RE = re.compile(
    r"\s*(?:-|–|—|\bto\b|\bthrough\b)\s*(?P<num>" + _SECTION_NUM + r")",
    re.IGNORECASE,
)

# A number after "to" / "through" / a dash that is a count or a year, not the
# end of a range of sections: "section 5 to 10 days", "section 187 through
# 2023".
_UNIT_AFTER_RE = re.compile(
    r"\s*(?:days?|weeks?|months?|years?|hours?|minutes?|percent\b|per\s+cent\b|%)",
    re.IGNORECASE,
)
_YEAR_RE = re.compile(r"(?:19|20)\d\d")


# Two ways of writing a number that California section numbers never use, so
# an anchor written either way does not cite a California section:
#
#   "section 2,235"  one number with a thousands comma, not sections 2 and
#                    235. Only after a singular marker: "§§ 187,190" is a list.
#   "§ 9-318"        an article-and-section number, as uniform acts and many
#                    municipal codes write them ("Uniform Commercial Code
#                    section 2-207", "Sec. 27-77"), not a range from 9 to 318.
#                    The shape is a one- or two-digit number joined by a bare
#                    hyphen to a longer one. A real range of that shape
#                    ("§§ 51-100") is lost with it; "sections 71-73",
#                    "§§ 54950-54962", and every "to"/"through" range are not.
_GROUPED_NUMBER_RE = re.compile(r"\d{1,3},\d{3}(?![\d,])")
_ARTICLE_SECTION_NUMBER_RE = re.compile(r"\d{1,2}[-\u2010-\u2015]\d{3,}")


def not_a_california_number(text: str, marker: str, num_start: int) -> bool:
    """Is the number at `num_start` written in a form no California section
    number takes? `marker` is the section marker before it ("§", "sections")."""
    if _ARTICLE_SECTION_NUMBER_RE.match(text, num_start):
        return True
    return not _is_plural_marker(marker) and bool(_GROUPED_NUMBER_RE.match(text, num_start))


def _plausible_range(start: str, end: str, text: str, end_pos: int) -> bool:
    """Can `end` close a range of sections that opens at `start`?"""
    start_digits = re.match(r"\d+", start)
    end_digits = re.match(r"\d+", end)
    if start_digits is None or end_digits is None:
        return False
    s, e = start_digits.group(0), end_digits.group(0)
    if int(e) < int(s):
        return False
    if _YEAR_RE.fullmatch(e) and len(s) < len(e):
        return False
    return _UNIT_AFTER_RE.match(text, end_pos) is None


def _range_warning(range_end: str) -> str:
    return (
        f"first section of a range through {range_end}: only this section is "
        "cited; the sections the range spans are not enumerated"
    )

# Greedy forward extension: zero or more `(label)` runs, optionally preceded
# by a comma and `subd.` / `subdivision` token.
_FORWARD_RE = re.compile(
    r"\s*(?:,?\s*(?:subdivisions?|subds?\.?)?\s*\([A-Za-z0-9]{1,4}\))+",
    re.IGNORECASE,
)

# Connector between a section number and a trailing "of the <Code>" phrase.
# All parts optional so "of the Penal Code", "of Penal Code", ", Penal Code",
# and a bare " Penal Code" all line up to the code tokens. ", inclusive," is
# allowed before "of": "Sections 81000 to 91015, inclusive, of the Government
# Code" is how the Political Reform Act is routinely described. No "^": it is
# used with .match(text, pos), which already anchors at pos — "^" would anchor
# at the start of the whole text and never match there.
_FORWARD_CONNECTOR_RE = re.compile(
    r"\s*\[?(?:,\s*)?(?:inclusive\s*,?\s*)?(?:of\s+)?(?:the\s+)?", re.IGNORECASE
)

# Maximum tokens to try when walking for the code name. Real CA citations
# rarely exceed 6 tokens (e.g., "Cal. Bus. & Prof. Code" ≈ 5).
_MAX_BACKWARD_TOKENS = 6

# How far before an anchor the backward walk looks. Six tokens of the longest
# code name ("Cal. Welf. & Inst. Code,") fit in well under this. Bounding the
# window is what keeps scan() linear: tokenizing the whole prefix before every
# anchor made a 160 KB opinion take over a second, and it grew quadratically.
_BACKWARD_WINDOW = 120

# One-word code names are ordinary English words in lowercase ("lab", "com",
# "fin", "pen", "civil"). In prose, a code name that normalizes to one word
# must be written as an all-caps acronym ("CCP", "PC") to count, so "the lab
# section 5" is not read as Labor Code § 5. Multi-word names ("Lab. Code") are
# unaffected. Checked after normalization because noise words ("the", "Cal.")
# would otherwise smuggle a lowercase word past a raw token count.
def _code_name_ok(candidate: str) -> bool:
    if " " in _normalize_code_name(candidate):
        return True
    last = candidate.split()[-1] if candidate.split() else ""
    letters = re.sub(r"[^A-Za-z]", "", last)
    return bool(letters) and letters.isupper()


# A code name that ends a sentence ("... in the Government Code. Section 54953
# requires ...", "... the Government Code. (§ 54953.)") is a mention, not the
# start of a citation: the citation's code is inferred, so it is carried, not
# named. A full closing word ("Code.", "Procedure.") directly before a
# capitalized marker or "§", optionally through an opening parenthesis, is
# that shape. Real cites put a comma or nothing there ("Gov. Code, § 54953",
# "Gov. Code § 54953"); an abbreviation ("Code Civ. Proc. § 425.16") is not a
# full word, so it is unaffected. Before "§" the opening parenthesis is
# required: "(Gov. Code. § 36503.)" is a typo inside one citation, and AG
# opinions have it often enough that treating it as a sentence end lost real
# cites (13 rows across 1,967 opinions, measured 2026-11-08).
_SENTENCE_END_CODE_RE = re.compile(r"\b(?:Code|Procedure)\.\s*[(\[]?\s*$")
_SENTENCE_END_CODE_BEFORE_SYMBOL_RE = re.compile(r"\b(?:Code|Procedure)\.\s*[(\[]\s*$")


def _tokens_in(text: str, lo: int, hi: int) -> list[tuple[int, int]]:
    """Whitespace-delimited tokens of text[lo:hi], as absolute offsets.

    A token cut in half by `lo` is dropped, so a window boundary can never
    manufacture a code name out of the tail of a longer word.
    """
    tokens = [
        (lo + tm.start(), lo + tm.end())
        for tm in re.finditer(r"\S+", text[lo:hi])
    ]
    if tokens and lo > 0 and tokens[0][0] == lo and not text[lo - 1].isspace():
        tokens = tokens[1:]
    return tokens


# Words that, directly before a code name, make it some other body of law:
# "Texas Penal Code", "N.Y. Civ. Code", "Model Penal Code", "Uniform Probate
# Code". Many states name their codes as California does, so the name alone
# does not say whose code it is. Full names are matched as bare words;
# abbreviations as written, with their periods.
_OTHER_JURISDICTIONS = frozenset({
    # the other states, the District, and the territories
    "Alabama", "Alaska", "Arizona", "Arkansas", "Colorado", "Connecticut", "Delaware",
    "District of Columbia", "Florida", "Georgia", "Guam", "Hawaii", "Idaho", "Illinois",
    "Indiana", "Iowa", "Kansas", "Kentucky", "Louisiana", "Maine", "Maryland",
    "Massachusetts", "Michigan", "Minnesota", "Mississippi", "Missouri", "Montana",
    "Nebraska", "Nevada", "New Hampshire", "New Jersey", "New Mexico", "New York",
    "North Carolina", "North Dakota", "Ohio", "Oklahoma", "Oregon", "Pennsylvania",
    "Puerto Rico", "Rhode Island", "South Carolina", "South Dakota", "Tennessee", "Texas",
    "Utah", "Vermont", "Virginia", "Washington", "West Virginia", "Wisconsin", "Wyoming",
    # their usual abbreviations
    "Ala.", "Ariz.", "Ark.", "Colo.", "Conn.", "Del.", "D.C.", "Fla.", "Ga.", "Haw.",
    "Ill.", "Ind.", "Kan.", "Ky.", "La.", "Me.", "Md.", "Mass.", "Mich.", "Minn.", "Miss.",
    "Mo.", "Mont.", "Neb.", "Nev.", "N.H.", "N.J.", "N.M.", "N.Y.", "N.C.", "N.D.",
    "Okla.", "Or.", "Ore.", "Pa.", "R.I.", "S.C.", "S.D.", "Tenn.", "Tex.", "Vt.", "Va.",
    "Wash.", "W.Va.", "Wis.", "Wyo.",
    # other countries' codes that share a name with a California code
    "French", "German", "Mexican", "Philippine", "Spanish", "Swiss",
})
_MODEL_QUALIFIERS = frozenset({"Model"})
# "Uniform" names a uniform act, with one exception: California enacted the
# Uniform Commercial Code as its Commercial Code and courts cite it both ways
# ("California Uniform Commercial Code section 9403", "Cal. U. Com. Code,
# § 2207"). Its hyphenated uniform-act sections are refused by number shape
# (`not_a_california_number`), not here.
_UNIFORM_QUALIFIERS = frozenset({"Uniform", "U."})
_OPENERS = "([{\"'\u201c\u2018"


def _names_other_law(text: str, before: list[tuple[int, int]], name_start: int,
                     entry: CodeEntry) -> bool:
    """Is the code name starting at `name_start` qualified, by the words just
    before it, as another jurisdiction's code, a model code, or a uniform act?

    `before` holds the tokens that precede the name. A name that opens a
    parenthetical or a quotation is not qualified by what came before it: in
    "on Washington (Veh. Code, § 21453)" the street is not a jurisdiction.
    """
    if not before or text[name_start] in _OPENERS:
        return False
    words = [text[a:b].lstrip(_OPENERS) for a, b in before[-3:]]
    last = words[-1]
    if last in _MODEL_QUALIFIERS:
        return True
    if last in _UNIFORM_QUALIFIERS:
        return entry.law_code != "COM"
    return any(" ".join(words[-n:]) in _OTHER_JURISDICTIONS for n in (1, 2, 3))


def _walk_backward_for_code(text: str, end: int) -> tuple[CodeEntry, int] | None:
    """Find the longest token-run ending at `end` that resolves to a code.

    Looks back at most `_BACKWARD_WINDOW` characters. Returns
    (entry, start_offset) on success, None otherwise: also when the name found
    is qualified as some other body of law ("Texas Penal Code", "Model Penal
    Code"), which is not a California code however it resolves.
    """
    tokens = _tokens_in(text, max(0, end - _BACKWARD_WINDOW), end)
    if not tokens:
        return None
    # "Penal Code; sections 1 and 2 of the Civil Code": a code name closed off
    # by ";" or ")" ended the previous citation and does not start this one.
    # ("]" is fine: "[Civil Code] section 2924g" is an editorial insertion.)
    if text[tokens[-1][1] - 1] in ";)":
        return None

    # Try longest suffix first so "Cal. Civ. Code" wins over "Code".
    upper = min(_MAX_BACKWARD_TOKENS, len(tokens))
    for n in range(upper, 0, -1):
        suffix = tokens[-n:]
        start, stop = suffix[0][0], suffix[-1][1]
        candidate = text[start:stop]
        if not _code_name_ok(candidate):
            continue
        entry = resolve_code(candidate)
        if entry is not None:
            if _names_other_law(text, tokens[:-n], start, entry):
                return None
            return entry, start
    return None


_GLUED_FOOTNOTE_RE = re.compile(r"(?<=Code)\.?\d{1,3}\W*$")


def _walk_forward_for_code(text: str, pos: int) -> tuple[CodeEntry, int] | None:
    """Find an "of the <Code>" phrase starting at `text[pos]`.

    Returns (entry, end_offset) where end_offset is the absolute index just
    past the matched code name, or None if no leading token-prefix (after an
    optional `of`/`the`/`,` connector) resolves. Looks ahead at most
    `_BACKWARD_WINDOW` characters, for the same linear-time reason as the
    backward walk.
    """
    window_end = min(len(text), pos + _BACKWARD_WINDOW)
    connector = _FORWARD_CONNECTOR_RE.match(text, pos, window_end)
    base = connector.end() if connector else pos
    # The code name must follow the connector directly. Anything else there —
    # ". ", "; ", ".) " — ends the citation, and a code named past it belongs
    # to the next one ("42 U.S.C. § 1983; Penal Code § 187" is not Pen. § 1983).
    if base >= window_end or not text[base].isalpha():
        return None
    tokens = [
        (base + tm.start(), base + tm.end())
        for tm in re.finditer(r"\S+", text[base:window_end])
    ]
    # A token cut off by the window end is not a whole word.
    if tokens and window_end < len(text) and tokens[-1][1] == window_end:
        tokens = tokens[:-1]
    if not tokens:
        return None

    # Try longest prefix first so "Public Utilities Code" wins over "Public".
    upper = min(_MAX_BACKWARD_TOKENS, len(tokens))
    for n in range(upper, 0, -1):
        end = tokens[n - 1][1]
        candidate = text[base:end]
        # A footnote number printed against the code name: "of the Government
        # Code1 provides", "of the Education Code.1 (§§ ...)". Read the name
        # without it; the citation span stops at the name.
        glued = _GLUED_FOOTNOTE_RE.search(candidate)
        if glued is not None:
            candidate = candidate[: glued.start()]
            end = base + glued.start()
        if not _code_name_ok(candidate):
            continue
        entry = resolve_code(candidate)
        if entry is not None:
            return entry, end
    return None


# --- California Constitution -------------------------------------------------
# Roman-numeral article plus an optional single sub-article letter ("XIII D",
# "X A"). Uppercase only in prose: lowercase "article i" is far more likely to
# be something else. The (?![A-Za-z]) guard keeps the sub-article letter from
# swallowing the first letter of a following word.
_ARTICLE = r"(?P<article>[IVXLCDM]+(?:\s+[A-Z](?![A-Za-z]))?)"
_CONST_NAME = r"(?i:(?:Cal(?:ifornia)?\.?\s+)?Const(?:\.|itution\b))"

# "Cal. Const., art. XIII D, " / "California Constitution, article XIII A, " /
# "art. XIII C, " — immediately before the section marker.
_CONST_BACKWARD_RE = re.compile(
    r"(?:(?P<const>" + _CONST_NAME + r")\s*,?\s*)?"
    r"(?<![A-Za-z])(?i:art(?:\.|icle\b))\s*" + _ARTICLE + r"\s*,?\s*$"
)

# "of article XIII D" [", " | " of"] ["the" "California Constitution"] —
# immediately after the section number (and any subdivisions).
_CONST_FORWARD_RE = re.compile(
    r"\s*,?\s*(?i:of)\s+(?i:art(?:\.|icle\b))\s*" + _ARTICLE
    + r"(?P<tail>\s*,?\s*(?i:of\s+)?(?i:the\s+)?" + _CONST_NAME + r")?"
)

# "of the California Constitution" right after the number, for the form
# "article XIII D, section 6 of the California Constitution".
_CONST_AFTER_RE = re.compile(
    r"\s*,?\s*(?i:of\s+)?(?i:the\s+)?" + _CONST_NAME
)

# A mention of the Constitution anywhere, used to attribute a later bare
# "art. XIII D, § 6" short form.
_CONST_MENTION_RE = re.compile(r"\b" + _CONST_NAME)

_CONST_INFERRED_WARNING = (
    "article attributed to the California Constitution from an earlier "
    "mention of the Constitution in the text"
)

# --- Short forms -------------------------------------------------------------
# "(Id., § 54954.2.)", "ibid., section 5" — the previous citation's code.
_ID_RE = re.compile(r"\b(?:id|ibid)\.,?\s*$", re.IGNORECASE)

# A footnote number left in the text between a code name and the marker:
# "Gov. Code,2 § 945.4", "Gov. Code 1, § 3300", "Elections Code 7 sections".
_FOOTNOTE_AFTER_CODE_RE = re.compile(r"(?<=Code)(?:,?\s*\d{1,3}),?\s*$")

# "Division 4 (commencing with Section 1400) of the Probate Code": the code
# name sits past the closing parenthesis.
_COMMENCING_RE = re.compile(r"\(\s*commencing\s+with\s+$", re.IGNORECASE)
_CLOSE_PAREN_RE = re.compile(r"\s*\)")

# "former" directly before the citation or between code name and marker.
_FORMER_BEFORE_RE = re.compile(r"\bformer\s+$", re.IGNORECASE)
_FORMER_MARKER_RE = re.compile(r",?\s*\bformer\s+$", re.IGNORECASE)

_ID_WARNING = (
    "short-form citation ('Id.' / 'ibid.'): law code taken from the previous "
    "citation in the text; confirm it points where you think"
)


# "All further statutory references are to the Penal Code", "Undesignated
# section references are to the Code of Civil Procedure". Opinions put this in
# a footnote, and CourtListener's text puts footnotes at the end, so the
# declaration usually comes *after* the cites it governs.
_STATUTORY_DEFAULT_RE = re.compile(
    r"\b(?:(?:statutory|section|code)\s+(?:references|citations)"
    r"|references\s+to\s+(?:statutes|sections))\s+"
    r"(?:in\s+this\s+opinion\s+)?(?:are|will\s+be|refer)\s+to\s+(?:the\s+)?"
    r"(?P<name>[A-Z][\w&.,'\s]{0,60}?\bCode\b(?:\s+of\s+Civil\s+Procedure)?)",
    re.IGNORECASE,
)


def _statutory_defaults(text: str) -> list[tuple[int, str | None]]:
    """Every "further statutory references are to the X Code" declaration,
    as (offset, law_code), in order. law_code is None when the declared code
    is not a California code ("... are to the Los Angeles Administrative
    Code"): bare cites in that document belong to something we cannot
    resolve."""
    found: list[tuple[int, str | None]] = []
    for m in _STATUTORY_DEFAULT_RE.finditer(text):
        entry = resolve_code(m.group("name"))
        found.append((m.start(), None if entry is None or entry.law_code == "CONS"
                      else entry.law_code))
    return found


def _document_default(
    pos: int, defaults: list[tuple[int, str | None]]
) -> tuple[bool, str | None]:
    """(declared, law_code) for the declaration governing `pos`: the last one
    before it, else the first one in the document (a footnote printed after
    the text it annotates)."""
    if not defaults:
        return False, None
    i = bisect_left([offset for offset, _ in defaults], pos) - 1
    return True, defaults[max(i, 0)][1]


def _declared_warning(law_code: str) -> str:
    return (
        f"no code named with this section; attributed to {law_code} by the "
        "document's own note that undesignated statutory references are to it"
    )


# Text ending just before a bare marker that shows the "§" belongs to some
# other source: a number ("Stats. 2023, ch. 286, §", "tit. 5, §"), a
# parenthetical ("Corbin on Contracts (2024) §"), a capitalized abbreviation
# ("42 U.S.C. §", "Muni. Code, §"), or a named body of law this tool does not
# cover ("Guidelines, §", "Oakland Municipal Code §").
_OTHER_SOURCE_RE = re.compile(
    r"(?:\d|\)|\]|\b[A-Z][A-Za-z]*\.(?:[A-Z][A-Za-z]*\.)*"
    r"|\b(?:Code|Guidelines|Rules?|Regulations?|Charter|Act|Ordinance|Stat|Stats))"
    r",?\s*$"
)
# Abbreviations that sit before a bare California cite and are not a source.
_NOT_A_SOURCE = {"Id.", "Ibid.", "Cf.", "See.", "Accord."}


def _follows_other_source(text: str, anchor: re.Match[str]) -> bool:
    lo = max(0, anchor.start() - 40)
    before = text[lo:anchor.start()]
    stripped = before.rstrip().rstrip(",")
    last = stripped.split()[-1] if stripped.split() else ""
    if last in _NOT_A_SOURCE:
        return False
    if anchor.group("marker")[0].isupper() and re.search(r"[.?!][)\]”\"’']?$", stripped):
        # "Section 5" opening a sentence: the period ends the previous one.
        return False
    if re.search(r"[.?!][)\]]$", stripped):
        # "(Emphasis added.) section 85102(a)": the sentence ended inside the
        # parenthetical, so the ")" closes a sentence, not some other source
        # ("Corbin on Contracts (2024) §" has no period and still counts).
        return False
    return _OTHER_SOURCE_RE.search(before) is not None


def _carried_warning(law_code: str) -> str:
    return (
        f"no code named with this section; attributed to {law_code}, the "
        "code most recently cited or named earlier in the text — confirm it"
    )


# A code named in prose without a section: "the Government Code", "Code of
# Civil Procedure". Found by anchoring on the word "Code" and walking out.
_CODE_WORD_RE = re.compile(r"\bCode\b")


def _find_code_mentions(text: str) -> list[tuple[int, str]]:
    """Every place a code is named, as (end_offset, law_code), in order.

    Feeds carry-forward. Each "Code" word is tried as the end of a backward
    run ("the Government Code") and as the start of a forward one ("Code of
    Civil Procedure", "Code Civ. Proc."). Bounded windows keep it linear.
    """
    mentions: list[tuple[int, str]] = []
    for m in _CODE_WORD_RE.finditer(text):
        best: tuple[int, str] | None = None
        backward = _walk_backward_for_code(text, m.end())
        if backward is not None:
            best = (m.end(), backward[0].law_code)
        ahead = _tokens_in(text, m.start(), min(len(text), m.start() + 40))
        for n in range(min(4, len(ahead)), 1, -1):
            end = ahead[n - 1][1]
            entry = resolve_code(text[m.start():end])
            if entry is not None:
                best = (end, entry.law_code)
                break
        if best is not None and best[1] != "CONS":
            mentions.append(best)
    return mentions


def _is_plural_marker(marker: str) -> bool:
    return marker.strip().lower() in _PLURAL_MARKERS


class _Item:
    """One section in an enumerated tail ("..., 330.1", "and 54954")."""

    __slots__ = ("num", "num_start", "end", "range_end")

    def __init__(self, num: str, num_start: int, end: int) -> None:
        self.num = num
        self.num_start = num_start
        self.end = end
        self.range_end: str | None = None


def _collect_continuations(
    text: str, pos: int, allow_list: bool, first_num: str
) -> tuple[list[_Item], str | None, int]:
    """Walk the enumerated tail after a section number.

    Returns ``(items, anchor_range_end, tail_end)``. A list continuation
    (", 330.1", "and 330.1") adds an item. A range continuation ("-4636",
    "to 91015") adds nothing: it records its number as the ``range_end`` of
    the section before it — the anchor's (``anchor_range_end``) or the last
    item's — because a range cites its first section only (decided
    2026-11-07, matching the pattern extractors in `extra`). ``tail_end``
    is where the tail stops, including subdivision parentheticals, so a
    trailing "of the <Code>" phrase is looked for after it. Stops at the first
    token that is not a continuation, leaving ordinary prose alone, and at a
    "range" whose end is a count or a year (`_plausible_range`).
    """
    items: list[_Item] = []
    anchor_range_end: str | None = None

    while True:
        match = _RANGE_CONT_RE.match(text, pos)
        is_range = match is not None
        if match is None and allow_list:
            match = _LIST_CONT_RE.match(text, pos)
        if match is None:
            break

        item_end = match.end()
        fwd = _FORWARD_RE.match(text, item_end)
        if fwd:
            item_end = fwd.end()

        if is_range:
            start = items[-1].num if items else first_num
            if not _plausible_range(start, match.group("num"), text, match.end("num")):
                break
            if items:
                items[-1].range_end = match.group("num")
            else:
                anchor_range_end = match.group("num")
        else:
            items.append(_Item(match.group("num"), match.start("num"), item_end))
        pos = item_end

    return items, anchor_range_end, pos


# A section number followed by a space and more digits is a number broken by
# OCR ("Government Code Sections 8 1000 through 9 1014" is 81000-91014), never
# a citation to the first fragment. OCR also reads 0/1 as O/I/l, so letters
# from that set count when the token has at least one digit ("8 IO00").
_SPLIT_NUMBER_RE = re.compile(r"[ \t]+(?=[0-9IlO]*[0-9])[0-9IlO]{2,}(?![A-Za-z])")

# A "letter suffix" that is really an English word glued to the number:
# "section 82041of the Act". Real suffixes are one or two letters with no
# meaning ("330a", "1203.1bb"); these are words, so the number stands alone.
_WORD_SUFFIXES = {"of", "or", "to", "in", "on", "at", "as", "by", "is", "an", "if", "et"}


def _strip_word_suffix(section_num: str) -> str:
    m = re.search(r"[A-Za-z]+$", section_num)
    if m and m.group(0).lower() in _WORD_SUFFIXES:
        return section_num[: m.start()]
    return section_num


def _make_citation(
    text: str,
    section_num: str,
    num_start: int,
    item_end: int,
    span_start: int,
    span_end: int,
    law_code: str,
    confidence: Confidence,
    warnings: list[str],
    article: str | None = None,
    former: bool = False,
    attribution: Attribution = "named",
    range_end: str | None = None,
    reference_start: int | None = None,
) -> SpannedCitation:
    """Build a SpannedCitation for one enumerated section in a reference."""
    subsection_text = text[num_start + len(section_num) : item_end]
    warnings = list(warnings)
    if range_end is not None:
        warnings.append(_range_warning(range_end))
    return SpannedCitation(
        raw=text[span_start:span_end],
        law_code=law_code,
        section_num=_strip_word_suffix(section_num),
        article=article,
        subsection_path=_LABEL_RE.findall(subsection_text) or None,
        confidence=confidence,
        former=former,
        warnings=warnings,
        span_start=span_start,
        span_end=span_end,
        attribution=attribution,
        range_end=range_end,
        reference_start=span_start if reference_start is None else reference_start,
    )


class _Attribution:
    """What an anchor cites, before it is expanded into citations."""

    __slots__ = (
        "law_code", "article", "confidence", "span_start", "span_end", "warnings", "source",
    )

    def __init__(
        self,
        law_code: str,
        span_start: int,
        span_end: int,
        *,
        article: str | None = None,
        confidence: Confidence = "high",
        warnings: list[str] | None = None,
        source: Attribution = "named",
    ) -> None:
        self.law_code = law_code
        self.article = article
        self.confidence: Confidence = confidence
        self.span_start = span_start
        self.span_end = span_end
        self.warnings = list(warnings or [])
        self.source: Attribution = source


def _attribute_constitution(
    text: str,
    anchor: re.Match[str],
    subsection_end: int,
    const_seen: bool,
) -> _Attribution | Literal[False] | None:
    """Constitution attribution for an anchor.

    Returns an _Attribution for a constitutional cite, False when the anchor
    carries an article that is NOT attributable to the Constitution (so the
    anchor must be dropped rather than misread as a code section), and None
    when no article is involved at all.
    """
    lo = max(0, anchor.start() - _BACKWARD_WINDOW)
    back = _CONST_BACKWARD_RE.search(text, lo, anchor.start())
    if back is not None:
        article = " ".join(back.group("article").split())
        if back.group("const"):
            return _Attribution("CONS", back.start(), subsection_end, article=article)
        after = _CONST_AFTER_RE.match(text, subsection_end)
        if after is not None:
            return _Attribution("CONS", back.start(), after.end(), article=article)
        if const_seen:
            return _Attribution(
                "CONS",
                back.start(),
                subsection_end,
                article=article,
                confidence="medium",
                warnings=[_CONST_INFERRED_WARNING],
                source="carried",
            )
        return False

    fwd = _CONST_FORWARD_RE.match(text, subsection_end)
    if fwd is not None:
        article = " ".join(fwd.group("article").split())
        if fwd.group("tail"):
            return _Attribution("CONS", anchor.start(), fwd.end(), article=article)
        if const_seen:
            return _Attribution(
                "CONS",
                anchor.start(),
                fwd.end(),
                article=article,
                confidence="medium",
                warnings=[_CONST_INFERRED_WARNING],
                source="carried",
            )
        return False
    return None


def scan(
    text: str,
    default_law_code: str | None = None,
    default_article: str | None = None,
) -> list[SpannedCitation]:
    """Find and parse every California statutory citation in `text`.

    When `default_law_code` is set, a bare "Section X" anchor with no
    code-name word in the preceding prose is attributed to that code rather
    than dropped or carried forward. CA statutes write intra-code pointers
    this way ("as defined in subdivision (a) of Section 56134"), so
    cross-reference callers pass the parent's law_code here to catch
    same-code references. For the Constitution (`default_law_code="CONS"`),
    pass the parent's `default_article` too; a constitutional section is
    meaningless without its article, so CONS without one is ignored.

    Without a default, a bare anchor takes the code most recently cited or named
    earlier in the text, at medium confidence with a warning; with no code
    anywhere before it, the anchor is dropped.

    Plural lists are expanded, not collapsed: "Gov. Code sections 54950,
    54953, and 54954" yields three citations sharing the resolved code. A
    range cites its first section only: "sections 54950-54962" yields § 54950
    with `range_end="54962"` and a warning; the endpoint is not a citation of
    its own (decided 2026-11-07).

    Every citation carries `attribution`; anything but "named" was inferred
    from context, and callers that persist links should treat it that way.
    """
    out: list[SpannedCitation] = []
    seen: set[tuple[int, int]] = set()

    if default_law_code == "CONS" and default_article is None:
        default_law_code = None
    if default_law_code != "CONS":
        default_article = None

    mentions = _find_code_mentions(text)
    mention_ends = [end for end, _ in mentions]
    declared = _statutory_defaults(text)
    const_positions = [m.start() for m in _CONST_MENTION_RE.finditer(text)]

    for anchor in _ANCHOR_RE.finditer(text):
        if _SPLIT_NUMBER_RE.match(text, anchor.end()):
            continue  # "Sections 8 1000": an OCR-split number, not § 8
        if not_a_california_number(text, anchor.group("marker"), anchor.start("num")):
            continue  # "section 2,235", "§ 9-318": not a California section number
        # Greedy forward extension for trailing subdivisions / subd. text.
        subsection_end = anchor.end()
        fwd = _FORWARD_RE.match(text, subsection_end)
        if fwd:
            subsection_end = fwd.end()

        extras, anchor_range_end, tail_end = _collect_continuations(
            text,
            subsection_end,
            allow_list=_is_plural_marker(anchor.group("marker")),
            first_num=anchor.group("num"),
        )
        # The "of the <Code>" phrase, when there is one, sits after the whole
        # enumerated tail, so the forward walk starts at tail_end.

        # "former" between a code name and the marker ("Gov. Code, former
        # § 6254"): note it and walk back from before it.
        code_end = anchor.start()
        former = False
        lo = max(0, code_end - _BACKWARD_WINDOW)
        former_marker = _FORMER_MARKER_RE.search(text, lo, code_end)
        if former_marker is not None:
            former = True
            code_end = former_marker.start()
        footnote = _FOOTNOTE_AFTER_CODE_RE.search(text, lo, code_end)
        if footnote is not None:
            code_end = footnote.start()

        const_seen = bisect_left(const_positions, anchor.start()) > 0
        attribution = _attribute_constitution(text, anchor, subsection_end, const_seen)
        if attribution is False:
            continue
        if attribution is None:
            attribution = _attribute_code(
                text,
                anchor,
                code_end,
                subsection_end,
                tail_end,
                bool(extras),
                default_law_code,
                default_article,
                out,
                mentions,
                mention_ends,
                declared,
            )
        if attribution is None:
            continue

        if not former:
            lo = max(0, attribution.span_start - _BACKWARD_WINDOW)
            former = _FORMER_BEFORE_RE.search(text, lo, attribution.span_start) is not None

        warnings = attribution.warnings
        if former and FORMER_WARNING not in warnings:
            warnings.append(FORMER_WARNING)

        candidates = [
            _make_citation(
                text,
                anchor.group("num"),
                anchor.start("num"),
                subsection_end,
                attribution.span_start,
                attribution.span_end,
                attribution.law_code,
                attribution.confidence,
                warnings,
                attribution.article,
                former,
                attribution.source,
                anchor_range_end,
            )
        ]
        candidates += [
            _make_citation(
                text,
                item.num,
                item.num_start,
                item.end,
                item.num_start,
                item.end,
                attribution.law_code,
                attribution.confidence,
                warnings,
                attribution.article,
                former,
                attribution.source,
                item.range_end,
                attribution.span_start,
            )
            for item in extras
        ]

        for cite in candidates:
            key = (cite.span_start, cite.span_end)
            if key in seen:
                continue
            seen.add(key)
            out.append(cite)

    return out


def _attribute_code(
    text: str,
    anchor: re.Match[str],
    code_end: int,
    subsection_end: int,
    tail_end: int,
    has_extras: bool,
    default_law_code: str | None,
    default_article: str | None,
    previous: list[SpannedCitation],
    mentions: list[tuple[int, str]],
    mention_ends: list[int],
    declared: list[tuple[int, str | None]],
) -> _Attribution | None:
    """Code attribution for a non-constitutional anchor (steps 2-7 of the
    module docstring). Returns None when the anchor should be dropped."""
    backward = _walk_backward_for_code(text, code_end)
    if (
        backward is not None
        and (
            (anchor.group("marker")[0].isupper()
             and _SENTENCE_END_CODE_RE.search(text, backward[1], code_end))
            or (anchor.group("marker")[0] == "§"
                and _SENTENCE_END_CODE_BEFORE_SYMBOL_RE.search(text, backward[1], code_end))
        )
    ):
        backward = None  # sentence-final mention; carry-forward picks it up
    if backward is not None:
        # Code named before the marker — reuse the parser on the full span so
        # its ambiguity warnings ("CC", "PC") carry over.
        entry, span_start = backward
        if entry.law_code == "CONS":
            # "Constitution § 6" with no article: unresolvable, not a code.
            return None
        # Parse the code name and the cite without whatever sat between them
        # ("former", a footnote number); `former` is tracked by the caller.
        parsed = try_parse(text[span_start:code_end] + " " + text[anchor.start():subsection_end])
        if parsed is None:
            return None
        warnings = [w for w in parsed.warnings if w != FORMER_WARNING]
        return _Attribution(
            parsed.law_code,
            span_start,
            subsection_end,
            confidence=parsed.confidence,
            warnings=warnings,
        )

    forward_from = tail_end
    if _COMMENCING_RE.search(text, max(0, anchor.start() - 40), anchor.start()):
        close = _CLOSE_PAREN_RE.match(text, tail_end)
        if close is not None:
            forward_from = close.end()
    forward = _walk_forward_for_code(text, forward_from)
    if forward is not None:
        # "Section X of the <Code>" — code named after the number.
        entry, fwd_end = forward
        if entry.law_code == "CONS":
            return None
        # With an enumerated tail the code phrase belongs to no single
        # section, so the first citation's span stops at its own number.
        span_end = subsection_end if has_extras else fwd_end
        return _Attribution(entry.law_code, anchor.start(), span_end)

    before = max(0, anchor.start() - _BACKWARD_WINDOW)
    id_match = _ID_RE.search(text, before, anchor.start())
    if id_match is not None and previous:
        prior = previous[-1]
        if prior.law_code == "CONS" and prior.article is None:  # pragma: no cover
            return None
        return _Attribution(
            prior.law_code,
            id_match.start(),
            subsection_end,
            article=prior.article,
            confidence="medium",
            warnings=[_ID_WARNING],
            source="id",
        )

    if _follows_other_source(text, anchor):
        return None

    if default_law_code is not None:
        # Bare "Section X" with no code anywhere — use the caller's code.
        return _Attribution(
            default_law_code,
            anchor.start(),
            subsection_end,
            article=default_article,
            source="caller_default",
        )

    is_declared, document_default = _document_default(anchor.start(), declared)
    if is_declared:
        if document_default is None:
            return None  # the document's bare cites are to a non-state code
        return _Attribution(
            document_default,
            anchor.start(),
            subsection_end,
            warnings=[_declared_warning(document_default)],
            source="document_default",
        )

    carried = _most_recent_code(anchor.start(), previous, mentions, mention_ends)
    if carried is None:
        return None
    law_code, article = carried
    return _Attribution(
        law_code,
        anchor.start(),
        subsection_end,
        article=article,
        confidence="medium",
        warnings=[_carried_warning(law_code)],
        source="carried",
    )


def _most_recent_code(
    pos: int,
    previous: list[SpannedCitation],
    mentions: list[tuple[int, str]],
    mention_ends: list[int],
) -> tuple[str, str | None] | None:
    """The code most recently cited or named before `pos`, as (law_code,
    article). A prior constitutional citation carries its article; a bare
    mention of the Constitution never counts (no article to attach)."""
    best_pos = -1
    best: tuple[str, str | None] | None = None
    i = bisect_left(mention_ends, pos + 1) - 1
    if i >= 0:
        best_pos, best = mentions[i][0], (mentions[i][1], None)
    for prior in reversed(previous):
        if prior.span_end > pos:
            continue
        if prior.span_end > best_pos:
            best = (prior.law_code, prior.article)
        break
    return best

