"""Depth, quotations, and explanatory parentheticals.

Every string below is taken from the live AG corpus, including the awkward
ones -- a closing quotation mark that reads as an opening one, a table's dot
leader inside quotation marks, page furniture landing between a citation and
the sentence it belongs to. Those are the cases that decide whether a `quote`
column is worth having, and each of them produced a wrong row before the rule
that now rejects it.

What is NOT tested here, because it deliberately does not exist: any notion of
whether a citation is approving or critical.
"""

from __future__ import annotations

from ca_citations import extract
from ca_citations.context import find_parenthetical, find_quote
from ca_citations.extra import find_ag_citations


def one(text: str, code: str, section: str):
    """The single ExtractedCite for (code, section), or fail loudly."""
    hits = [c for c in extract(text) if (c.code, c.section) == (code, section)]
    assert len(hits) == 1, f"expected exactly one {code} {section}, got {hits}"
    return hits[0]


# --- depth ------------------------------------------------------------------

def test_depth_counts_occurrences_not_rows() -> None:
    text = (
        "Government Code section 1090 prohibits self-dealing. Section 1090 of "
        "the Government Code has been construed broadly, and Gov. Code, § 1090 "
        "reaches consultants."
    )
    assert one(text, "GOV", "1090").depth == 3


def test_a_single_citation_has_depth_one() -> None:
    assert one("Under Government Code section 71180, does…", "GOV", "71180").depth == 1


def test_overlapping_matches_from_two_extractors_count_once() -> None:
    """"sections 4620 to 4636 of the Welfare and Institutions Code" is matched
    by the range extractor AND by the plural-list extractor. That is one
    occurrence of WIC 4620, and counting it twice would inflate depth on
    exactly the citations lawyers write most carefully."""
    text = "See sections 4620 to 4636, inclusive, of the Welfare and Institutions Code."
    assert one(text, "WIC", "4620").depth == 1


def test_depth_is_summed_across_text_fields() -> None:
    cite = one_across(
        "Does Government Code section 1090 apply?",
        "Government Code section 1090 does apply.",
    )
    assert cite.depth == 2


def one_across(*texts: str):
    hits = [c for c in extract(*texts) if (c.code, c.section) == ("GOV", "1090")]
    assert len(hits) == 1
    return hits[0]


# --- quotations -------------------------------------------------------------

def test_quote_after_a_colon_is_captured_verbatim() -> None:
    text = (
        'Government Code section 25303 provides in part: "The board of '
        'supervisors shall supervise the official conduct of all county '
        'officers." We conclude otherwise.'
    )
    cite = one(text, "GOV", "25303")
    assert cite.quoted is True
    assert cite.quote == (
        "The board of supervisors shall supervise the official conduct of all "
        "county officers."
    )


def test_quote_line_wrapping_is_normalized_but_nothing_else_is() -> None:
    """PDF text wraps mid-sentence; the line break is an artifact of the page,
    not of the statute. Everything else, ellipses included, is left alone."""
    text = (
        'Penal Code section 832.5 provides that "[e]ach department\n'
        '. . . shall\nestablish a procedure."'
    )
    assert one(text, "PEN", "832.5").quote == (
        "[e]ach department . . . shall establish a procedure."
    )


def test_a_closing_quotation_mark_is_not_read_as_an_opening_one() -> None:
    """Opinion 83-608. A straight quote is the same glyph both ways, so without
    the preceding-character rule the opinion's OWN prose gets captured and
    attributed to the statute -- worse than capturing nothing."""
    text = (
        'subject to Article 9 (commencing with Section 11120) of Title 2 of the '
        'Government Code."2 While it is thus clear that the meetings of the '
        'Regents are subject to the Act, the question posed is whether…'
    )
    assert one(text, "GOV", "11120").quote is None


def test_a_dot_leader_is_not_a_quotation() -> None:
    """Opinion 04-808 reproduces a statutory table whose dot leader sits inside
    the quotation marks. It clears the length bar and carries nothing to
    verify."""
    text = (
        "Chapter 7 (commencing with Section 13890) of Division 12 of the Health "
        'and Safety Code for fire protection. . . . " . . . . . . . . . . . . . '
        '. . . . . . . . . . . ." (Italics added.)'
    )
    assert one(text, "HSC", "13890").quote is None


def test_a_quotation_after_a_sentence_break_belongs_to_the_sentence_not_the_cite() -> None:
    """Opinion 94-604: the quoted passage is a court's rule of construction,
    not the text of the section cited before it."""
    text = (
        "Government Code sections 65852.3 and 65852.4 do not grant an exemption "
        'from the plain wording of the MPA. "Unless unreasonable or clearly '
        'contrary to the statutory language, the construction of a statute by '
        'an agency is entitled to great weight."'
    )
    assert one(text, "GOV", "65852.3").quote is None


def test_a_quotation_belonging_to_a_second_citation_is_left_to_that_citation() -> None:
    """Opinion 07-312. The quoted words are section 25283's, not 6103's."""
    text = (
        'Government Code section 6103 did not apply where Government Code '
        'section 25283 "specifically provides otherwise: the board may collect '
        'compensation from private parties."'
    )
    assert one(text, "GOV", "6103").quote is None


def test_a_block_quote_starting_a_new_sentence_is_not_attached_to_the_cite() -> None:
    """Opinion 84-702. The scanner's span swallows the period that ends the
    sentence, so the sentence-break rule cannot see it; without the separate
    guard, Education Code section 48201's text gets attributed to Welf. & Inst.
    Code section 17.1, which the finished sentence merely cross-referenced."""
    text = (
        "Residency, for the purpose of attendance in the public schools, shall "
        "be determined by Section 17.1 of the Welfare and Institutions Code.\n"
        '"Unless otherwise provided for in this code, a pupil shall not be '
        'enrolled for less than the minimum school day established by law."'
    )
    assert one(text, "WIC", "17.1").quote is None


def test_an_introduced_quotation_after_such_a_cite_is_still_captured() -> None:
    """The other half of opinion 84-702, and the reason the rule above turns on
    an empty gap rather than on the period alone: here the opinion says whose
    text it is about to quote."""
    text = (
        "determined by Section 17.1 of the Welfare and Institutions Code.\" "
        'That section provides as follows: "Unless otherwise provided under the '
        'provisions of this code, the residence of a minor is that of its '
        'parents."'
    )
    assert one(text, "WIC", "17.1").quote.startswith("Unless otherwise provided under")


def test_a_defined_term_in_quotation_marks_is_not_a_quotation_of_statutory_text() -> None:
    text = 'the Ralph M. Brown Act (Gov. Code, § 54950) defines a "legislative body"'
    assert one(text, "GOV", "54950").quote is None


def test_quoted_is_false_and_quote_is_null_when_nothing_is_quoted() -> None:
    cite = one("Government Code section 1090 prohibits self-dealing.", "GOV", "1090")
    assert cite.quoted is False and cite.quote is None


def test_an_unbalanced_opening_quote_is_declined_rather_than_swallowing_the_page() -> None:
    text = 'Government Code section 1090 provides: "the officers shall not be interested'
    assert find_quote(text, text.index("1090") + 4) is None


# --- explanatory parentheticals ---------------------------------------------

def test_parenthetical_on_a_statutory_citation() -> None:
    """Opinion 92-201, verbatim."""
    text = (
        "Penal Code section 626.10 (prohibiting the possession or bringing of "
        "weapons on public school grounds)."
    )
    assert one(text, "PEN", "626.10").parenthetical == (
        "(prohibiting the possession or bringing of weapons on public school grounds)"
    )


def test_a_bracketed_parenthetical_is_captured_too() -> None:
    """California Style Manual form: inside a citation parenthetical the
    explanation is bracketed. Opinion 23-302, verbatim."""
    text = (
        "(Gov. Code, § 1126 [prohibiting local agency personnel from engaging in "
        "certain incompatible outside activities].)"
    )
    assert one(text, "GOV", "1126").parenthetical == (
        "[prohibiting local agency personnel from engaging in certain "
        "incompatible outside activities]"
    )


def test_a_year_or_a_session_law_is_stepped_over_not_captured() -> None:
    text = (
        "Government Code section 68073.4 (Stats. 1981, ch. 301, § 1) (requiring "
        "the county treasurer to deposit the fee)."
    )
    assert one(text, "GOV", "68073.4").parenthetical == (
        "(requiring the county treasurer to deposit the fee)"
    )


def test_a_parenthetical_without_a_signal_word_is_declined() -> None:
    """No signal word means no way to tell an explanation from a cross-
    reference, an emphasis note, or a year. Precision beats recall."""
    for tail in ("(1982)", "(emphasis added)", "(a)", "(hereafter the Act)"):
        text = f"Government Code section 1090 {tail} applies."
        assert one(text, "GOV", "1090").parenthetical is None, tail


def test_a_parenthetical_two_sentences_later_is_not_attached() -> None:
    text = (
        "Government Code section 1090 applies here. We said as much last year "
        "(concluding that the contract was void)."
    )
    assert one(text, "GOV", "1090").parenthetical is None


def test_parenthetical_on_an_ag_to_ag_citation() -> None:
    """The in-corpus graph's version: the citing opinion's own words about the
    opinion it cites, including the pin cite and year in between."""
    text = (
        "See 85 Ops.Cal.Atty.Gen. 60, 62 (2002) (concluding that a city council "
        "member may not simultaneously serve as a planning commissioner)."
    )
    (cite,) = find_ag_citations(text)
    assert find_parenthetical(text, cite.end) == (
        "(concluding that a city council member may not simultaneously serve as "
        "a planning commissioner)"
    )


def test_nothing_produces_a_treatment_label() -> None:
    """The discipline this whole layer exists to keep. Every field on an extracted citation is a
    count, a flag about text, or text reproduced verbatim -- there is no field
    that says whether the document approves of the authority, and adding one
    should be a decision, not a drift."""
    text = (
        'We reject the argument. Government Code section 1090 (prohibiting '
        'self-dealing) provides: "shall not be financially interested in any '
        'contract made by them in their official capacity."'
    )
    cite = one(text, "GOV", "1090")
    assert set(vars(cite)) == {
        "code", "section", "form", "verifiable", "raw",
        "depth", "quote", "parenthetical",
    }
    # And each of the three carries source text or a count, nothing derived.
    assert cite.depth == 1
    assert cite.quote in text
    assert cite.parenthetical in text
