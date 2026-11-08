"""Pydantic models for parsed citations."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Confidence = Literal["high", "medium", "low"]

# Where scan() got a citation's code. Only "named" means the code (or the
# Constitution) is written next to the section; every other value is inferred
# from context, and a caller building an index should decide whether to trust
# it. Measured on 258 published opinions (2026-10-30):
# document_default agreed with a careful reader 93% of the time, carried 53%,
# id 54%.
Attribution = Literal["named", "id", "caller_default", "document_default", "carried"]


class ParsedCitation(BaseModel):
    """A California statutory citation, parsed into queryable parts."""

    raw: str = Field(..., description="The original citation string as supplied.")
    law_code: str = Field(
        ...,
        description=(
            "Canonical California law-code abbreviation matching "
            "capublic.law_section_tbl.law_code (e.g. CIV, CCP, PEN, GOV, BPC)."
        ),
    )
    section_num: str = Field(
        ...,
        description=(
            "Section number as a string. Carries dots for suffixed numbers "
            "like '425.16' or '21080.5'. Matches law_section_tbl.section_num "
            "for codes; matches law_section_tbl.op_section for the "
            "Constitution (law_code CONS)."
        ),
    )
    article: str | None = Field(
        default=None,
        description=(
            "California Constitution article in canonical Roman-numeral form "
            "(e.g. 'XIII D', 'I', 'X A'). Set only for CONS citations, where a "
            "section number is not unique without its article. None for codes."
        ),
    )
    subsection_path: list[str] | None = Field(
        default=None,
        description=(
            "Parsed subdivision chain, e.g. ['a','1'] for '§ 1714(a)(1)'. "
            "None if the citation does not specify a subdivision."
        ),
    )
    confidence: Confidence = Field(
        default="high",
        description=(
            "Confidence in the law_code resolution. 'medium' typically means "
            "an ambiguous abbreviation like 'CC' was resolved heuristically; "
            "callers should consider surfacing the warning."
        ),
    )
    former: bool = Field(
        default=False,
        description=(
            "True when the citation is to a *former* section ('former section "
            "6254'). The number may since have been repealed, renumbered, or "
            "reused, so the current text at that number is NOT the text the "
            "citing document construed. Callers must not treat a resolution of "
            "a former citation as the cited text."
        ),
    )
    warnings: list[str] = Field(default_factory=list)


class SpannedCitation(ParsedCitation):
    """A ParsedCitation plus its character span in the source text."""

    span_start: int = Field(..., description="0-based start offset in the scanned text.")
    span_end: int = Field(..., description="Exclusive end offset in the scanned text.")
    attribution: Attribution = Field(
        default="named",
        description=(
            "How the law code was found. 'named': written with the section. "
            "'id': taken from the previous citation ('Id.', 'ibid.'). "
            "'caller_default': the default_law_code the caller passed. "
            "'document_default': the text's own 'further statutory references "
            "are to the X Code' note. 'carried': the code most recently cited or "
            "named earlier in the text, or a Constitution inferred from an "
            "earlier mention. Anything but 'named' is inferred."
        ),
    )
    reference_start: int = Field(
        default=0,
        description=(
            "span_start of the first citation in the same reference. A plural "
            "reference ('Penal Code sections 330a and 330.1') yields one "
            "citation per section; the later ones have a span covering only "
            "their own number, so this points back to the citation whose raw "
            "text holds the code name. Equals span_start for the first."
        ),
    )
    range_end: str | None = Field(
        default=None,
        description=(
            "Set when this citation is the first section of a range ('sections "
            "4620-4636', 'Sections 81000 to 91015, inclusive'): the last section "
            "of the range. Only the first section is cited; the sections the "
            "range spans, including this endpoint, are not enumerated or linked."
        ),
    )
