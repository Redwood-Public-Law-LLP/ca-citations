"""Citation extraction.

Most strings below were taken from published AG opinions and FPPC letters, not
invented. The plural forms in particular cost 70% of that corpus its citations
on the first run, when the scanner anchored on them and the strict parser then
rejected them.
"""

from __future__ import annotations

import pytest

from ca_citations import extract
from ca_citations.extra import find_commencing, find_constitution


def codes(text: str) -> set[tuple[str, str]]:
    return {(c.code, c.section) for c in extract(text)}


# --- the singular form the scanner always handled ----------------------------

def test_singular_section_with_code_before() -> None:
    assert ("GOV", "71180") in codes("Under Government Code section 71180, does…")


def test_singular_section_with_code_after() -> None:
    """The dominant California drafting form."""
    assert ("PUC", "241") in codes("Section 241 of the Public Utilities Code")


# --- plural lists: the big gap ----------------------------------------------

@pytest.mark.parametrize(
    "text,expected",
    [
        ("a device proscribed by Penal Code sections 330a and 330.1?",
         {("PEN", "330a"), ("PEN", "330.1")}),
        ("In view of Health and Safety Code sections 8961.2 and 8961.3",
         {("HSC", "8961.2"), ("HSC", "8961.3")}),
        ("Do sections 9220.5 and 9221 of the Business and Professions Code apply?",
         {("BPC", "9220.5"), ("BPC", "9221")}),
    ],
)
def test_plural_section_lists(text: str, expected: set) -> None:
    assert expected <= codes(text)


def test_letter_suffixed_section_numbers_survive() -> None:
    """Penal Code 330a -- the letter is part of the number, not noise."""
    assert ("PEN", "330a") in codes("Penal Code sections 330a and 330.1")


# --- ranges: first section only ---------------------------------------------

@pytest.mark.parametrize(
    "text,first",
    [
        ("Welfare and Institutions Code sections 4620–4636?", ("WIC", "4620")),   # en dash
        ("Gov. Code sections 54950-54962", ("GOV", "54950")),                     # hyphen
        ("Sections 81000 to 91015, inclusive, of the Government Code", ("GOV", "81000")),
    ],
)
def test_ranges_record_the_first_section_only(text: str, first: tuple) -> None:
    """Storing every section of a range would drown the table."""
    got = codes(text)
    assert first in got
    assert len(got) == 1


# --- "commencing with", on either side of the code name ----------------------

def test_commencing_with_trailing_code() -> None:
    assert ("GOV", "87100") in codes(
        "Chapter 4 (commencing with Section 87100) of the Government Code"
    )


def test_commencing_with_leading_code_and_section_glyph() -> None:
    """From opinion 81-402: no chapter opener, a § rather than the word."""
    out = find_commencing("the Harbors and Navigation Code (commencing with § 500)")
    assert [(c.code, c.section) for c in out] == [("HNC", "500")]


# --- California Constitution -------------------------------------------------

def test_article_written_without_a_space() -> None:
    """'XIIIA' and 'XIII A' are the same article -- Prop 13."""
    assert ("CONS", "XIII A") in codes("article XIIIA of the Constitution")


def test_article_with_section() -> None:
    assert ("CONS", "XIII A-4") in codes("special taxes under article XIII A, section 4")


def test_prop_218_article() -> None:
    out = find_constitution("Cal. Const., art. XIII D, § 6")
    assert ("CONS", "XIII D-6") in {(c.code, c.section) for c in out}


# --- California Code of Regulations ------------------------------------------

@pytest.mark.parametrize(
    "text,expected",
    [
        ("regulations at 2 CCR § 18700", ("CCR-2", "18700")),
        ("Cal. Code Regs., tit. 14, § 15332", ("CCR-14", "15332")),
    ],
)
def test_ccr(text: str, expected: tuple) -> None:
    assert expected in codes(text)


def test_ccr_titles_6_and_24_are_flagged_unverifiable() -> None:
    """Title 6 is empty and Title 24 publishes separately, so neither can be
    checked against the official CCR. Store, but say so."""
    got = {c.section: c.verifiable for c in extract("Cal. Code Regs., tit. 24, § 1")}
    assert got == {"1": False}


# --- discipline --------------------------------------------------------------

def test_unknown_code_is_declined_not_guessed() -> None:
    """Precision beats recall: never invent a citation."""
    assert codes("sections 100 and 200 of the Imaginary Code") == set()


def test_federal_citations_are_out_of_scope() -> None:
    assert codes("pursuant to 18 United States Code section 5021") == set()


def test_deduplicated_on_code_and_section() -> None:
    """The citations table is keyed on (document, code, section); an opinion
    citing § 1090 six times is one citation."""
    text = "Section 1090 applies. Under Government Code section 1090, and again § 1090."
    assert len([c for c in extract(text) if c.section == "1090"]) == 1


def test_extract_accepts_multiple_fields_and_skips_none() -> None:
    got = codes("Government Code section 1090") | {
        (c.code, c.section) for c in extract("Gov. Code, § 1091.5", None, "")
    }
    assert ("GOV", "1090") in got and ("GOV", "1091.5") in got


def test_constitution_uses_the_scanner_code_not_a_second_spelling() -> None:
    """One authority, one code. An early draft emitted 'CONST' while
    the scanner emits 'CONS', so the same article landed under two
    codes and no single query could find it."""
    got = {c.code for c in extract("article XIII A, section 4 of the Constitution")}
    assert got == {"CONS"}


def test_bare_constitution_sections_are_dropped() -> None:
    """A scanner once reported 'article XI, section 7' as ('CONS','7') with no
    article. Every Constitution article restarts its numbering, so a
    bare section is ambiguous -- art. VII § 7 and art. XI § 7 are unrelated.
    Only the article-qualified form is stored."""
    got = codes("Under article XI, section 7 of the California Constitution, a city may")
    assert ("CONS", "XI-7") in got
    assert ("CONS", "7") not in got


def test_one_authority_one_identity() -> None:
    """No Constitution provision may appear under two representations."""
    for text in (
        "Cal. Const., art. XIII D, § 6",
        "article XIII A, section 4",
        "art. XI, section 7 of the Constitution",
    ):
        cons = [c for c in extract(text) if c.code == "CONS"]
        assert len(cons) == 1, f"{text!r} produced {cons}"


# --- AG reporter citations (the in-corpus graph) -----------------------------

def test_finds_ag_citations_including_every_typo_variant() -> None:
    from ca_citations.extra import find_ag_citations
    text = (
        "See 85 Ops.Cal.Atty.Gen. 60, 62 (2002); 73 Ops.Cal.Atty.Gen. 183 (1990); "
        "70 Cal.Ops.Atty.Gen. 250; 62 Ops.Cal.Att.Gen. 585; 90 Ops.CaI.Atty.Gen. 12; "
        "62 OpsCal.Atty.Gen. 504. Not a cite: Government Code section 1090."
    )
    assert {(c.volume, c.page) for c in find_ag_citations(text)} == {
        (85, 60), (73, 183), (70, 250), (62, 585), (90, 12), (62, 504)
    }


def test_a_rejected_near_match_does_not_swallow_the_next_citation() -> None:
    """re.finditer does not back up, so a loose pattern validated after the
    fact consumes the text it rejected. This cost a real citation before the
    reporter name was made specific in the regex itself."""
    from ca_citations.extra import find_ag_citations
    text = "Government Code section 1090. Also 62 Ops.Cal.Atty.Gen. 822."
    assert (62, 822) in {(c.volume, c.page) for c in find_ag_citations(text)}


def test_page_break_furniture_is_stripped() -> None:
    """When a citation spans a page break, the running footer (footnote number
    plus the opinion's own file number) lands in the middle of it. Without
    stripping, '892' reads as the volume instead of 37."""
    from ca_citations.extra import find_ag_citations
    text = "a member of a city council (37 2. 90-892 Ops.Cal.Atty.Gen. 21, 22 (1961)"
    assert [(c.volume, c.page) for c in find_ag_citations(text)] == [(37, 21)]


# --- corpus default for bare sections (FPPC) ----------------------------------
#
# FPPC documents cite the Political Reform Act bare -- "Section 82044.",
# "section 85501 of the Act" -- so the strict scanner finds nothing in a clean,
# forty-mention opinion. The default is range-guarded to the Act's own
# sections, Gov. Code §§ 81000-91015, so it cannot reach.

PRA = dict(default_code="GOV", default_range=(81000, 91015))


def test_bare_section_is_declined_without_a_default() -> None:
    assert codes("A gift is defined in Section 82028.") == set()


def test_bare_section_inside_the_range_takes_the_default() -> None:
    cites = extract("A gift is defined in Section 82028.", **PRA)
    got = {(c.code, c.section, c.form) for c in cites}
    assert got == {("GOV", "82028", "section-bare")}


def test_bare_section_outside_the_range_is_still_declined() -> None:
    text = "Section 1090 forbids it, and Section 5.32 of the Municipal Code applies."
    assert {(c.code, c.section) for c in extract(text, **PRA)} == set()


def test_named_code_still_wins_over_the_default() -> None:
    text = "Elections Code section 82000 is not the Act."
    assert {(c.code, c.section) for c in extract(text, **PRA)} == {("ELEC", "82000")}


def test_of_the_act_phrasing() -> None:
    text = "Does section 85501 of the Political Reform Act bar the payment?"
    assert {(c.code, c.section) for c in extract(text, **PRA)} == {("GOV", "85501")}


def test_bare_plural_lists_and_ranges_take_the_default_within_range() -> None:
    text = "See Sections 84200 and 84211, and Sections 87100 through 87103."
    got = {(c.code, c.section) for c in extract(text, **PRA)}
    assert got == {("GOV", "84200"), ("GOV", "84211"), ("GOV", "87100")}


def test_default_requires_its_range() -> None:
    with pytest.raises(ValueError):
        extract("Section 82028.", default_code="GOV")


def test_ccr_spelled_out_title_and_section() -> None:
    text = "the Commission's regulation at California Code of Regulations, title 2, section 18420.1"
    assert ("CCR-2", "18420.1") in codes(text)
    assert ("CCR-2", "18420.1") in codes("under Code of Regulations, title 2, section 18420.1,")


# --- plain English words are not code names ------------------------------------
#
# The code resolver knows "family", "elections", "water" as code names.
# In prose those words precede a section marker constantly and mean nothing.

def test_plain_word_before_section_is_not_a_code() -> None:
    text = "gifts to a member of his or her immediate family. Section 82029 includes the spouse."
    assert codes(text) == set()
    # Under the FPPC default the section is the Act's, not the Family Code's.
    assert {(c.code, c.section) for c in extract(text, **PRA)} == {("GOV", "82029")}


def test_plain_word_elections_is_not_a_code() -> None:
    text = "active in both local and statewide special elections. (section 85305)"
    assert {(c.code, c.section) for c in extract(text, **PRA)} == {("GOV", "85305")}


def test_explicit_code_names_still_resolve() -> None:
    assert codes("as defined in Family Code section 297.5") == {("FAM", "297.5")}
    assert codes("Elections Code Sections 12400-12407 apply") == {("ELEC", "12400")}
    assert codes("Water Code section 79422(d) controls") == {("WAT", "79422")}
    assert codes("fees under CCP § 1021.5") == {("CCP", "1021.5")}


def test_plain_word_before_a_plural_list_is_not_a_code() -> None:
    text = "reported by the official's family. Sections 82030 and 82034 define income."
    assert codes(text) == set()
    got = {(c.code, c.section) for c in extract(text, **PRA)}
    assert got == {("GOV", "82030"), ("GOV", "82034")}


# --- precision rules against the shared scanner (added 2026-11-07) ----------
# The shared scanner infers codes from context and flags "former" sections.
# This index stores only what a document names, as the current section.

def test_former_section_is_not_indexed_as_the_current_section() -> None:
    assert codes("Former Government Code section 6254 exempted those records.") == set()


def test_former_plural_list_is_not_indexed_by_the_pattern_extractors_either() -> None:
    assert codes("former Government Code sections 6254 and 6255 exempted them.") == set()


def test_former_bare_cite_is_not_indexed_under_the_corpus_default() -> None:
    cites = extract("Under former section 82044, the rule differed.", **PRA)
    assert {(c.code, c.section) for c in cites} == set()


def test_current_cite_beside_a_former_one_is_kept() -> None:
    got = codes(
        "Former Government Code section 6254 is now Government Code section 7920.000."
    )
    assert got == {("GOV", "7920.000")}


def test_carried_forward_code_is_not_indexed() -> None:
    assert codes("The Government Code governs here. Section 54953 requires notice.") == set()


def test_id_short_form_is_not_indexed() -> None:
    got = codes("(Gov. Code, § 54953.) It must be posted. (Id., § 54954.2.)")
    assert got == {("GOV", "54953")}


def test_document_default_note_is_not_indexed() -> None:
    text = (
        "Section 1001.36 permits diversion.\n\n1 All further statutory "
        "references are to the Penal Code."
    )
    assert codes(text) == set()


@pytest.mark.parametrize(
    "text",
    [
        "Proposition 218 added Cal. Const., art. XIII D, § 6.",
        # The forward form is the one that exercises the scanner's CONS path:
        # find_constitution sees only "article XIII D" here.
        "Notice is required by section 6 of article XIII D of the California Constitution.",
    ],
)
def test_constitution_from_scanner_and_pattern_share_one_identity(text: str) -> None:
    """One authority, one row: never 'XIII D-6' beside an article-only 'XIII D'."""
    cites = [c for c in extract(text) if c.code == "CONS"]
    assert [(c.code, c.section, c.depth) for c in cites] == [("CONS", "XIII D-6", 1)]


def test_csm_abbreviations_now_reach_the_index() -> None:
    """These forms never resolved in the older copy of the parser."""
    assert codes("See Pub. Resources Code section 21080, subd. (b).") == {("PRC", "21080")}
    assert codes("Under Code of Civil Procedure section 473, relief.") == {("CCP", "473")}
    assert codes("Business & Professions Code section 17200 applies.") == {("BPC", "17200")}


def test_scanner_range_is_stored_as_form_range() -> None:
    (cite,) = extract("Gov. Code sections 54950-54962 apply.")
    assert (cite.code, cite.section, cite.form) == ("GOV", "54950", "range")


# --- found in review, 2026-11-07 ---------------------------------------------

@pytest.mark.parametrize(
    "text,expected",
    [
        ("Penal Code sections 187 and 82044 apply.", {("PEN", "187"), ("PEN", "82044")}),
        (
            "Elections Code sections 2150, 18000, and 85305",
            {("ELEC", "2150"), ("ELEC", "18000"), ("ELEC", "85305")},
        ),
    ],
)
def test_list_member_of_another_code_never_takes_the_corpus_default(
    text: str, expected: set
) -> None:
    """A list item's raw is just its number; the code name is on the first
    citation of the reference, and it is explicit."""
    cites = extract(text, **PRA)
    assert {(c.code, c.section) for c in cites} == expected


@pytest.mark.parametrize(
    "text",
    [
        "Gov. Code sections 54950, 54953, and 54954",
        "sections 54950, 54953, and 54954 of the Government Code",
    ],
)
def test_every_member_of_a_named_list_is_indexed(text: str) -> None:
    assert codes(text) == {("GOV", "54950"), ("GOV", "54953"), ("GOV", "54954")}


def test_list_member_after_a_nested_range_is_indexed() -> None:
    assert codes("Gov. Code sections 54950, 54952-54954, and 54960") == {
        ("GOV", "54950"), ("GOV", "54952"), ("GOV", "54960"),
    }


def test_id_pointing_at_another_code_is_not_a_bare_default_cite() -> None:
    cites = extract("Elections Code § 18000. Id., § 84308.", **PRA)
    assert {(c.code, c.section) for c in cites} == {("ELEC", "18000")}


def test_id_pointing_at_the_default_code_is_still_a_bare_default_cite() -> None:
    cites = extract("Gov. Code § 82000. Id., § 84308.", **PRA)
    assert ("GOV", "84308", "section-bare") in {(c.code, c.section, c.form) for c in cites}


def test_code_named_in_the_previous_sentence_is_not_indexed() -> None:
    assert codes("We look to the Government Code. (§ 54953.)") == set()


# --- other bodies of law that share a California code's name (2026-11-11) -----
# The index must hold none of these. Every sentence is invented.


@pytest.mark.parametrize(
    "text",
    [
        "The court applied Texas Penal Code section 19.02.",
        "See Texas Government Code section 311.021.",
        "Model Penal Code section 2.02 defines purpose.",
        "Uniform Commercial Code section 2-207 governs the forms.",
        "Uniform Probate Code section 2-503 excuses the defect.",
        "He was charged under Penal Code section 2,235.",
    ],
)
def test_cites_to_other_law_are_not_indexed(text: str) -> None:
    assert extract(text) == []


def test_californias_commercial_code_is_indexed_under_either_name() -> None:
    text = (
        "Uniform Commercial Code section 2207 governs; see also California "
        "Uniform Commercial Code section 9403 and Cal. U. Com. Code, § 2314."
    )
    assert sorted((c.code, c.section) for c in extract(text)) == [
        ("COM", "2207"), ("COM", "2314"), ("COM", "9403"),
    ]


def test_plural_lists_are_indexed_as_before() -> None:
    assert sorted((c.code, c.section) for c in extract("Penal Code sections 2, 235 and 240")) == [
        ("PEN", "2"), ("PEN", "235"), ("PEN", "240"),
    ]


# --- which constitution, and whose article (2026-11-11) -----------------------
# Every sentence is invented.


@pytest.mark.parametrize(
    "text",
    [
        "(U.S. Const., art. I, § 10.)",
        "article I, section 8 of the United States Constitution",
        "the supremacy clause of article VI of the United States Constitution",
        "the case and controversy language of article III of the federal Constitution",
        "By section 3 of article III of the constitution of the United States it is provided",
        "under the United States Constitution (art. IV), and that the judgment",
    ],
)
def test_federal_constitution_articles_are_not_indexed(text: str) -> None:
    assert extract(text) == []


@pytest.mark.parametrize(
    "text",
    [
        "By article VI of the city charter, a department was created.",
        "the county has, in article VII of its charter, provided for a board",
        "jurisdiction was retained in article XIV of the reorganization plan",
        "Medical Staff Bylaws (1971) art. III, § 2(a), p. 7.",
        "sections 82.04 and 82.05 of chapter 8, article II, and sections 86.11",
    ],
)
def test_an_article_of_some_other_document_is_not_indexed(text: str) -> None:
    assert extract(text) == []


def test_a_bare_numbered_article_is_not_indexed() -> None:
    """Nothing in the sentence says whose article IV this is. A lost cite, by
    design: precision beats recall for anything persisted."""
    assert extract("article IV, section 1, relating to the initiative power") == []


@pytest.mark.parametrize(
    "text,key",
    [
        ("(Cal. Const., art. XIII D, § 6, subd. (b).)", "XIII D-6"),
        ("article I, section 7 of the California Constitution", "I-7"),
        ("The California Constitution (art. I, § 8) forbids it.", "I-8"),
        ("section 6 of article XI of the Constitution", "XI-6"),
        ("(Const., art. XI, sec. 8)", "XI-8"),
        ("article XVIII, section 3, of the Constitution expressly declares", "XVIII-3"),
        ("article XI, section 7 of the state Constitution", "XI-7"),
        ("article XIII A, section 3, subdivision (b), of the Constitution", "XIII A-3"),
        # A lettered article needs no name beside it.
        ("special taxes under article XIII A, section 4", "XIII A-4"),
        ("the voter-approval requirements of article XIII C apply", "XIII C"),
        # Beside a federal cite, the California one is still indexed.
        ("(U.S. Const., 14th Amend., § 1; Cal. Const., art. I, § 7.)", "I-7"),
        ("(Cal. Const., art. I, § 19; U.S. Const., 4th Amend.)", "I-19"),
    ],
)
def test_california_constitution_cites_are_still_indexed(text: str, key: str) -> None:
    assert [(c.code, c.section) for c in extract(text)] == [("CONS", key)]


@pytest.mark.parametrize(
    "text",
    [
        "a miscarriage of justice. (Cal. Const., art. VI, § 4½.)",
        "under section 4 1/2 of article VI of the Constitution",
        "(Const., art. VI, sec. 41/2.)",
    ],
)
def test_a_fractional_section_is_indexed_at_the_article_only(text: str) -> None:
    """The article is certain; the whole-numbered section would be wrong."""
    assert [(c.code, c.section) for c in extract(text)] == [("CONS", "VI")]


def test_a_lettered_constitution_section_keeps_its_letter() -> None:
    """Section 1a is not section 1."""
    got = [(c.code, c.section) for c in extract("by article VI, section 1a, of the Constitution")]
    assert got == [("CONS", "VI-1a")]
