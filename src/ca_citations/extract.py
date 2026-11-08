"""One entry point that runs every citation form over a document's text.

Precision beats recall here, by design: a citation must never be invented,
and a citation index is meant to answer "every opinion citing Gov. Code
§ 1091.5" exactly. So each extractor either resolves a
code confidently or declines — nothing is guessed from context.

What the `verifiable` flag means, and why it is stored per-row: a California
statute cite can be checked against the official code text, and a CCR cite
against the official CCR. CCR titles 6 (empty) and 24 (Building Standards,
published separately) cannot be checked that way. Storing the flag
means the MCP server can say which cites in a document it can stand behind.

Three MECHANICAL signals ride along with each citation — `depth`, `quote` and
`parenthetical`. All three are countable or verbatim; none of them says whether
the document approves of the authority or reasons against it. Free Law
Project shipped `depth`, left `treatment` commented out in their own model,
and built parenthetical extraction instead so
the reader sees the citing document's own words. That is the order followed
here, and a treatment label is deliberately absent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ca_citations import context, extra
from ca_citations.models import SpannedCitation
from ca_citations.scanner import scan

# The section anchor, for splitting a strict-scan span into code-name head and rest.
_SECTION_MARKER_RE = re.compile(
    r"\s*(?:§{1,2}|\bsections?\b|\bsecs?\.)", re.IGNORECASE
)


@dataclass(frozen=True)
class _Occurrence:
    """One appearance of one citation in one text field."""

    code: str
    section: str
    form: str
    verifiable: bool
    raw: str
    start: int
    end: int
    field_no: int  # which text field this came from; spans only compare within one
    text: str      # that field, for looking at what follows the citation


@dataclass(frozen=True)
class ExtractedCite:
    code: str
    section: str
    form: str          # 'section' | 'ccr' | 'range' | 'commencing' | '*-bare'
    verifiable: bool
    raw: str
    depth: int = 1
    quote: str | None = None
    parenthetical: str | None = None

    @property
    def quoted(self) -> bool:
        """True when statutory text was quoted at one of the occurrences."""
        return self.quote is not None


def _occurrences(
    text: str,
    field_no: int,
    default_code: str | None = None,
    default_range: tuple[int, int] | None = None,
) -> list[_Occurrence]:
    """Every citation occurrence in one text field, in no particular order.

    `default_code` / `default_range`: see `extract`. A section reference with
    no explicit code name is attributed to the default only if its number is
    inside the range; such occurrences carry a '-bare' form suffix.
    """
    out: list[_Occurrence] = []

    def add(code: str, section: str, form: str, verifiable: bool,
            raw: str, start: int, end: int) -> None:
        out.append(
            _Occurrence(code, section, form, verifiable, raw, start, end, field_no, text)
        )

    def code_name_is_explicit(raw: str) -> bool:
        # A code named BEFORE the section marker must be an explicit code name,
        # not an English word the resolver happens to know ("family. Section
        # 82029"). See extra.named_code_is_explicit. Forward forms ("Section
        # 241 of the Public Utilities Code") always carry the word "Code".
        head = _SECTION_MARKER_RE.split(raw, maxsplit=1)[0]
        return not head.strip() or extra.named_code_is_explicit(head)

    def named_explicitly(c: SpannedCitation, first_raw: dict[int, str]) -> bool:
        # Judged on the FIRST citation of the reference: in "Penal Code
        # sections 187 and 82044" the second citation's raw is just "82044",
        # and the code name lives in the first one's. For the Constitution,
        # "named" already means "Const." / "Constitution" was written with the
        # article; the code-name test does not apply to it.
        if c.attribution != "named":
            return False
        if c.law_code == "CONS":
            return True
        return code_name_is_explicit(first_raw.get(c.reference_start, c.raw))

    def first_raws(cites: list[SpannedCitation]) -> dict[int, str]:
        return {c.span_start: c.raw for c in cites if c.span_start == c.reference_start}

    # 1. Plain statutory sections, via the scanner.
    kept_spans: set[tuple[int, int]] = set()
    # "Former Government Code section 6254" cites a number whose current text
    # is not what the document construed, so it is not an occurrence of the
    # current section. Its span is remembered so the pattern extractors below
    # cannot re-add the same words under the current section.
    former_spans: list[tuple[int, int]] = []
    strict = scan(text)
    strict_first = first_raws(strict)
    for c in strict:
        if c.former:
            former_spans.append((c.span_start, c.span_end))
            continue
        # The scanner also infers codes from context (Id., the document's
        # default note, carry-forward). This index stores only what the text
        # names; the corpus default is handled, range-guarded, in 1b.
        if not named_explicitly(c, strict_first):
            continue
        # A Constitution section is meaningless without its article: every
        # article restarts its own numbering.
        if c.law_code == "CONS" and not c.article:
            continue
        kept_spans.add((c.span_start, c.span_end))
        if c.law_code == "CONS":
            # find_constitution's key ('XIII D-6'), so one authority never has
            # two identities in the table.
            add("CONS", f"{c.article}-{c.section_num}", "constitution", True, c.raw,
                c.span_start, c.span_end)
            continue
        form = "range" if c.range_end else "section"
        add(c.law_code, c.section_num, form, True, c.raw, c.span_start, c.span_end)

    # 1b. Bare sections attributed to the corpus default, range-guarded.
    # Anything the default run finds that the strict pass did not keep is, by
    # construction, an anchor with no explicit code name near it -- including
    # one whose only "code name" was a plain English word refused above.
    if default_code is not None and default_range is not None:
        defaulted = scan(text, default_law_code=default_code)
        defaulted_first = first_raws(defaulted)
        for c in defaulted:
            if c.former:
                former_spans.append((c.span_start, c.span_end))
                continue
            if (c.span_start, c.span_end) in kept_spans:
                continue
            if c.law_code != default_code and (
                c.attribution == "id" or named_explicitly(c, defaulted_first)
            ):
                # A real, explicit other code (the strict pass owns it), or an
                # "Id." pointing at one: neither is a bare cite to the default.
                continue
            if not _section_in_range(c.section_num, default_range):
                continue
            add(default_code, c.section_num, "section-bare", True, c.raw,
                c.span_start, c.span_end)

    # 2. Plural lists, dash ranges, chapter references, the Constitution.
    #    3. California Code of Regulations.
    named = (
        *extra.find_section_lists(text),
        *extra.find_ranges(text),
        *extra.find_commencing(text),
        *extra.find_constitution(text),
        *extra.find_ccr(text),
    )
    for e in named:
        add(e.code, e.section, e.form, e.verifiable, e.raw, e.start, e.end)

    # 2b. The same list/range forms, bare, under the corpus default.
    if default_code is not None and default_range is not None:
        named_keys = {(e.code, e.section, e.start) for e in named}
        for e in (
            *extra.find_section_lists(text, default_code=default_code),
            *extra.find_ranges(text, default_code=default_code),
        ):
            if (e.code, e.section, e.start) in named_keys:
                continue
            if e.code != default_code or not _section_in_range(e.section, default_range):
                continue
            add(e.code, e.section, e.form + "-bare", e.verifiable, e.raw, e.start, e.end)

    # "section 6 of article XIII D of the California Constitution": the scanner
    # stores CONS 'XIII D-6' and find_constitution sees only "article XIII D".
    # The article-only match is the same words, less precisely, so it goes.
    sectioned = [o for o in out if o.code == "CONS" and "-" in o.section]
    out = [
        o for o in out
        if not (
            o.code == "CONS" and "-" not in o.section
            and any(
                s.section.startswith(o.section + "-") and o.start < s.end and s.start < o.end
                for s in sectioned
            )
        )
    ]

    if former_spans:
        out = [
            o for o in out
            if not any(o.start < f_end and f_start < o.end for f_start, f_end in former_spans)
        ]
    return out


def _merge_overlapping(spans: list[_Occurrence]) -> list[_Occurrence]:
    """Collapse occurrences of ONE citation that describe the same text.

    Two extractors can both match the same words: "sections 4620 to 4636 of the
    Welfare and Institutions Code" is seen by `find_ranges` and again by
    `find_section_lists`. That is one occurrence of WIC 4620, not two, and
    counting it twice would inflate `depth` on exactly the citations lawyers
    write most carefully. Overlapping spans within the same (code, section) are
    therefore merged; the earliest-starting, most specific one survives.
    """
    kept: list[_Occurrence] = []
    for occ in sorted(spans, key=lambda o: (o.start, -(o.end - o.start))):
        if kept and occ.start < kept[-1].end:
            continue
        kept.append(occ)
    return kept


def _section_in_range(section: str, rng: tuple[int, int]) -> bool:
    """Is the integer part of a section number inside [lo, hi]? '82044' -> 82044,
    '18420.1' -> 18420, '330a' -> 330. Non-numeric leaders never qualify."""
    m = re.match(r"\d+", section)
    return m is not None and rng[0] <= int(m.group(0)) <= rng[1]


def extract(
    *texts: str | None,
    default_code: str | None = None,
    default_range: tuple[int, int] | None = None,
) -> list[ExtractedCite]:
    """Extract every citation from one or more text fields.

    Deduplicated on (code, section) -- that pair is the citations table's key.
    An opinion citing § 1090 six times is one ROW for § 1090, now carrying
    `depth = 6`: the count that used to be discarded is the cheapest signal of
    importance available, and it is a count rather than a judgment.

    `quote` and `parenthetical` take the FIRST value found in document order.
    An opinion that quotes a section twice quotes it once for our purposes; the
    stored passage is verbatim either way, and an attorney following it back to
    the document sees the rest.

    `default_code` and `default_range` -- both or neither. A corpus whose
    subject is ONE statute cites it bare: FPPC opinions write "Section 82044."
    and "section 85501 of the Act", never "Government Code section 82044", and
    without this the extractor found nothing in a clean, forty-mention opinion
    (St. Croix, 2005). When set, a section reference with NO explicit code name
    in the prose is attributed to `default_code` **only if** its number falls
    inside `default_range`. The range is what keeps this from being a guess:
    the Political Reform Act is Gov. Code §§ 81000-91015, so a
    bare "Section 82044" in an FPPC document can only be that Act, while a bare
    "Section 1090" or "Section 5.32" in the same document is still declined.
    Default-attributed cites carry a '-bare' form so they can be told apart.
    """
    if (default_code is None) != (default_range is None):
        raise ValueError("default_code and default_range must be given together")

    per_key: dict[tuple[str, str], list[_Occurrence]] = {}
    for field_no, text in enumerate(texts):
        if not text:
            continue
        for occ in _occurrences(text, field_no, default_code, default_range):
            per_key.setdefault((occ.code, occ.section), []).append(occ)

    out: list[ExtractedCite] = []
    for (code, section), spans in per_key.items():
        # Merge WITHIN a text field only: an offset in `question` and the same
        # offset in `full_text` describe different words, so comparing them
        # would merge unrelated occurrences.
        merged: list[_Occurrence] = []
        for field_no in sorted({o.field_no for o in spans}):
            merged += _merge_overlapping([o for o in spans if o.field_no == field_no])
        merged.sort(key=lambda o: (o.field_no, o.start))

        first = merged[0]
        quote = next(
            (q for q in (context.find_quote(o.text, o.end) for o in merged) if q), None
        )
        paren = next(
            (p for p in (context.find_parenthetical(o.text, o.end) for o in merged) if p),
            None,
        )
        out.append(
            ExtractedCite(
                code=code, section=section, form=first.form,
                verifiable=first.verifiable, raw=first.raw,
                depth=len(merged), quote=quote, parenthetical=paren,
            )
        )
    return out
