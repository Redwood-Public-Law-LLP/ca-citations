"""Tests for citation.scanner."""

from __future__ import annotations

import pytest

from ca_citations.scanner import scan


def test_single_citation_in_sentence() -> None:
    text = "The duty of ordinary care is set out in Cal. Civ. Code § 1714(a)."
    results = scan(text)
    assert len(results) == 1
    cite = results[0]
    assert cite.law_code == "CIV"
    assert cite.section_num == "1714"
    assert cite.subsection_path == ["a"]
    # Span should cover the citation, not random words around it.
    assert text[cite.span_start:cite.span_end].rstrip(".").strip() == "Cal. Civ. Code § 1714(a)"


def test_multiple_citations_in_paragraph() -> None:
    text = (
        "California recognizes a general duty of care under Cal. Civ. Code § 1714, "
        "and the anti-SLAPP statute appears at Cal. Civ. Proc. Code § 425.16. "
        "Murder is defined in Cal. Penal Code § 187."
    )
    results = scan(text)
    law_codes = [r.law_code for r in results]
    assert "CIV" in law_codes
    assert "CCP" in law_codes
    assert "PEN" in law_codes
    assert len(results) == 3


def test_csm_form_in_prose() -> None:
    text = "See Civ. Code, § 1714, subd. (a), for the rule."
    results = scan(text)
    assert len(results) == 1
    assert results[0].law_code == "CIV"
    assert results[0].subsection_path == ["a"]


def test_garbage_anchor_dropped() -> None:
    """A § marker without a resolvable code-name should NOT emit a citation."""
    text = "The conference room is at § 1234 in the building plan."
    # "conference room is at" is not a CA code name, so this should not parse.
    results = scan(text)
    assert results == []


def test_year_in_parens_not_treated_as_subsection() -> None:
    """`(1872)` after a section number should not be parsed as subsection 1872."""
    text = "Cal. Civ. Code § 1714 (1872)"
    results = scan(text)
    assert len(results) == 1
    assert results[0].subsection_path is None  # 4-digit excluded by label regex


def test_spans_are_byte_accurate() -> None:
    text = "Per Cal. Civ. Code § 1714(a), one is responsible."
    results = scan(text)
    assert len(results) == 1
    span_text = text[results[0].span_start:results[0].span_end]
    # Span should at least include the section number; trailing chars vary by
    # how aggressively the forward extension grabs.
    assert "Cal. Civ. Code" in span_text
    assert "1714" in span_text
    assert "(a)" in span_text


def test_empty_text_returns_empty_list() -> None:
    assert scan("") == []
    assert scan("Just some prose with no citations.") == []


def test_bare_section_dropped_without_default_code() -> None:
    """A bare 'Section X' with no nearby code-name stays dropped by default."""
    text = "a fire protection contract, as defined in subdivision (a) of Section 56134"
    assert scan(text) == []


def test_bare_section_attributed_to_default_code() -> None:
    """With default_law_code set, a bare 'Section X' resolves to that code."""
    text = "a fire protection contract, as defined in subdivision (a) of Section 56134"
    results = scan(text, default_law_code="GOV")
    assert len(results) == 1
    cite = results[0]
    assert cite.law_code == "GOV"
    assert cite.section_num == "56134"
    # The leading "(a)" modifies the reference but precedes the anchor, so it is
    # not captured as a subdivision of 56134.
    assert cite.subsection_path is None
    assert text[cite.span_start:cite.span_end] == "Section 56134"


def test_forward_of_the_code_cross_reference() -> None:
    """The dominant CA form 'Section X of the Y Code' (code AFTER the number)
    resolves to Y, even with no default and no code-name before the marker."""
    text = "a water corporation as defined in Section 241 of the Public Utilities Code"
    results = scan(text)
    assert len(results) == 1
    assert results[0].law_code == "PUC"
    assert results[0].section_num == "241"
    assert text[results[0].span_start:results[0].span_end] == (
        "Section 241 of the Public Utilities Code"
    )


def test_forward_code_beats_default_for_cross_code_ref() -> None:
    """An explicit 'of the <Code>' phrase wins over the default law code."""
    text = "see Section 187 of the Penal Code"
    results = scan(text, default_law_code="GOV")
    assert len(results) == 1
    assert results[0].law_code == "PEN"  # not GOV


def test_default_code_captures_trailing_subdivision() -> None:
    text = "the limits in Section 56134(b) apply"
    results = scan(text, default_law_code="GOV")
    assert len(results) == 1
    assert results[0].law_code == "GOV"
    assert results[0].section_num == "56134"
    assert results[0].subsection_path == ["b"]


# --- Plural section references --------------------------------------------------
# Every case below returned [] before the fix: the anchor matched, the code
# resolved, and then the parser rejected the plural spelling so the whole
# reference was dropped without a warning.


def test_plural_list_expands_to_one_citation_per_section() -> None:
    results = scan("Penal Code sections 330a and 330.1 prohibit it.")
    assert [(r.law_code, r.section_num) for r in results] == [
        ("PEN", "330a"),
        ("PEN", "330.1"),
    ]


def test_plural_list_with_serial_comma() -> None:
    results = scan("Gov. Code sections 54950, 54953, and 54954 govern.")
    assert [r.section_num for r in results] == ["54950", "54953", "54954"]
    assert all(r.law_code == "GOV" for r in results)


def test_plural_list_with_forward_of_the_code_phrase() -> None:
    """Code named AFTER the list still attributes to every enumerated section."""
    results = scan("sections 9220.5 and 9221 of the Business and Professions Code")
    assert [(r.law_code, r.section_num) for r in results] == [
        ("BPC", "9220.5"),
        ("BPC", "9221"),
    ]


def test_range_cites_first_section_only_with_flag_and_warning() -> None:
    """Decided 2026-11-07: a range cites its first section, flagged with its
    end. The endpoint is not a citation of its own -- linking it would claim
    the document cited § 54962 specifically."""
    results = scan("Gov. Code sections 54950-54962 apply.")
    assert [(r.section_num, r.range_end) for r in results] == [("54950", "54962")]
    assert any("range" in w.lower() for w in results[0].warnings)


def test_range_with_en_dash() -> None:
    results = scan("Welfare and Institutions Code sections 4620–4636")
    assert [(r.law_code, r.section_num, r.range_end) for r in results] == [
        ("WIC", "4620", "4636"),
    ]


def test_range_with_forward_code_phrase() -> None:
    results = scan("sections 4620 to 4636 of the Welfare and Institutions Code")
    assert [(r.law_code, r.section_num, r.range_end) for r in results] == [
        ("WIC", "4620", "4636"),
    ]


def test_inclusive_range_reaches_the_code_named_after_it() -> None:
    """The Political Reform Act form; the scanner used to drop it entirely."""
    results = scan("Sections 81000 to 91015, inclusive, of the Government Code")
    assert [(r.law_code, r.section_num, r.range_end) for r in results] == [
        ("GOV", "81000", "91015"),
    ]


def test_range_inside_a_list_flags_only_its_own_first_section() -> None:
    results = scan("Gov. Code sections 54950, 54952-54954, and 54960 apply.")
    assert [(r.section_num, r.range_end) for r in results] == [
        ("54950", None),
        ("54952", "54954"),
        ("54960", None),
    ]
    assert not any("range" in w.lower() for w in results[0].warnings)
    assert not any("range" in w.lower() for w in results[2].warnings)


def test_single_section_has_no_range_end() -> None:
    (result,) = scan("Gov. Code, § 54953.")
    assert result.range_end is None


def test_doubled_section_symbol_list_is_not_a_range() -> None:
    """`§§ X, Y` is a list; it should expand and carry no range warning."""
    results = scan("Cal. Civ. Code §§ 1714, 1715 are cited.")
    assert [r.section_num for r in results] == ["1714", "1715"]
    assert all(not r.warnings for r in results)


def test_each_enumerated_section_keeps_its_own_subdivision() -> None:
    results = scan("Gov. Code sections 54950(a) and 54953(b) apply.")
    assert [(r.section_num, r.subsection_path) for r in results] == [
        ("54950", ["a"]),
        ("54953", ["b"]),
    ]


def test_singular_marker_does_not_swallow_a_following_number() -> None:
    """A comma-list is only honoured after a plural marker — otherwise a
    reporter cite or a year after a singular `section` becomes a phantom."""
    results = scan("Penal Code section 187, 25 Cal.App.4th 100 (1994)")
    assert [r.section_num for r in results] == ["187"]


def test_plural_spans_are_accurate() -> None:
    text = "Penal Code sections 330a and 330.1 prohibit it."
    results = scan(text)
    assert text[results[0].span_start:results[0].span_end] == "Penal Code sections 330a"
    assert text[results[1].span_start:results[1].span_end] == "330.1"


def test_letter_suffix_survives_the_scanner() -> None:
    """The anchor used to capture only the digits, so `330a` scanned as `330` —
    a different, real section."""
    results = scan("Penal Code section 330a prohibits it.")
    assert len(results) == 1
    assert results[0].section_num == "330a"


# --- California Constitution in prose (2026-10-30 review, item 4) ------------
# scan() used to return [] for every constitutional cite: the backward walk
# could not get past "art. XIII D". Prop. 218 and Prop. 13 opinions produced no
# links at all.


def _cites(text: str, **kwargs: object) -> list[tuple[str, str | None, str]]:
    return [(r.law_code, r.article, r.section_num) for r in scan(text, **kwargs)]  # type: ignore[arg-type]


def test_constitution_csm_form() -> None:
    text = "The fee violates Cal. Const., art. XIII D, § 6, subd. (b)."
    results = scan(text)
    assert len(results) == 1
    cite = results[0]
    assert (cite.law_code, cite.article, cite.section_num) == ("CONS", "XIII D", "6")
    assert cite.subsection_path == ["b"]
    assert cite.confidence == "high"
    assert text[cite.span_start:cite.span_end] == "Cal. Const., art. XIII D, § 6, subd. (b)"


def test_constitution_spelled_out_before() -> None:
    assert _cites("California Constitution, article XIII A, section 1 limits it.") == [
        ("CONS", "XIII A", "1")
    ]


def test_constitution_section_of_article_of_constitution() -> None:
    text = "section 6 of article XIII D of the California Constitution"
    results = scan(text)
    assert [(r.law_code, r.article, r.section_num) for r in results] == [
        ("CONS", "XIII D", "6")
    ]
    assert text[results[0].span_start:results[0].span_end] == text


def test_constitution_article_then_section_then_constitution() -> None:
    assert _cites("article XIII D, section 6 of the California Constitution") == [
        ("CONS", "XIII D", "6")
    ]


def test_constitution_short_form_after_earlier_mention() -> None:
    results = scan("Under the Constitution, fees are limited. (art. XIII D, § 6.)")
    assert [(r.law_code, r.article, r.section_num) for r in results] == [
        ("CONS", "XIII D", "6")
    ]
    assert results[0].confidence == "medium"
    assert results[0].warnings


def test_article_without_constitution_is_dropped_not_misread() -> None:
    """A city charter's article is not a constitutional cite, and it must not
    be carried forward to an earlier code either."""
    text = "Gov. Code, § 36934 applies. City Charter article IV, section 3 controls."
    assert _cites(text) == [("GOV", None, "36934")]


def test_constitution_plural_sections_share_article() -> None:
    assert _cites("Cal. Const., art. XIII C, §§ 1, 2") == [
        ("CONS", "XIII C", "1"),
        ("CONS", "XIII C", "2"),
    ]


def test_constitution_word_without_article_is_dropped() -> None:
    assert scan("California Constitution section 6") == []


# --- Short forms: Id. and carry-forward (item 5) ----------------------------


def test_id_takes_previous_citation_code() -> None:
    text = "(Gov. Code, § 54953.) ... (Id., § 54954.2.)"
    results = scan(text)
    assert [(r.law_code, r.section_num) for r in results] == [
        ("GOV", "54953"),
        ("GOV", "54954.2"),
    ]
    assert results[1].confidence == "medium"
    assert any("Id." in w for w in results[1].warnings)
    assert text[results[1].span_start:results[1].span_end] == "Id., § 54954.2"


def test_ibid_after_constitution_keeps_article() -> None:
    assert _cites("(Cal. Const., art. XIII D, § 6.) See also ibid., § 4.") == [
        ("CONS", "XIII D", "6"),
        ("CONS", "XIII D", "4"),
    ]


def test_bare_section_carries_forward_previous_citation() -> None:
    text = "(Pub. Resources Code, § 21000.) The lead agency must act. (§ 21080, subd. (b).)"
    results = scan(text)
    assert [(r.law_code, r.section_num, r.subsection_path) for r in results] == [
        ("PRC", "21000", None),
        ("PRC", "21080", ["b"]),
    ]
    assert results[1].confidence == "medium"
    assert any("PRC" in w for w in results[1].warnings)


def test_bare_section_carries_forward_code_named_without_section() -> None:
    text = "The Brown Act is in the Government Code. Section 54953 requires open meetings."
    results = scan(text)
    assert [(r.law_code, r.section_num) for r in results] == [("GOV", "54953")]
    # A sentence-final code name is a mention, not part of the citation.
    assert text[results[0].span_start:results[0].span_end] == "Section 54953"
    assert results[0].confidence == "medium"


def test_carry_forward_uses_the_most_recent_code() -> None:
    text = (
        "Penal Code section 187 defines murder. The Vehicle Code is separate. "
        "Section 23152 prohibits driving under the influence."
    )
    assert [(r.law_code, r.section_num) for r in scan(text)] == [
        ("PEN", "187"),
        ("VEH", "23152"),
    ]


def test_code_of_civil_procedure_mention_carries_forward() -> None:
    text = "This motion arises under the Code of Civil Procedure. (§ 425.16.)"
    assert [(r.law_code, r.section_num) for r in scan(text)] == [("CCP", "425.16")]


def test_default_law_code_beats_carry_forward() -> None:
    """Cross-reference callers pass the parent's code; inside a statute a bare
    'Section X' means the same code even after another code is named."""
    text = "as provided in the Penal Code. Section 56134 applies."
    results = scan(text, default_law_code="GOV")
    assert [(r.law_code, r.confidence) for r in results] == [("GOV", "high")]


# --- "former" sections (item 3) ----------------------------------------------


def test_former_before_code_name() -> None:
    results = scan("Under former Government Code section 6254, the record was exempt.")
    assert len(results) == 1
    assert results[0].former is True
    assert results[0].section_num == "6254"
    assert any("FORMER" in w for w in results[0].warnings)


def test_former_between_code_and_marker() -> None:
    results = scan("(Gov. Code, former § 6254, subd. (k).)")
    assert [(r.law_code, r.section_num, r.subsection_path, r.former) for r in results] == [
        ("GOV", "6254", ["k"], True)
    ]


def test_former_bare_section_after_code_named() -> None:
    results = scan("(Gov. Code, § 7920.000.) Former section 6254 said otherwise.")
    assert [(r.section_num, r.former) for r in results] == [
        ("7920.000", False),
        ("6254", True),
    ]


def test_former_plural_applies_to_every_listed_section() -> None:
    results = scan("former Gov. Code sections 6254 and 6255")
    assert [(r.section_num, r.former) for r in results] == [("6254", True), ("6255", True)]


def test_current_citation_is_not_former() -> None:
    results = scan("The former rule was replaced; see Gov. Code, § 7920.000.")
    assert [r.former for r in results] == [False]


# --- False positives (item 6) ------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "the lab section 5 of the report",
        "see the com section 3 below",
        "the fin section 12 of the budget",
        "his civil section 4 notes",
        "results from the pen section 2",
    ],
)
def test_lowercase_one_word_code_names_are_ordinary_prose(text: str) -> None:
    assert scan(text) == []


def test_section_of_lowercase_word_is_not_a_forward_code() -> None:
    assert scan("Read section 5 of lab notes.") == []


def test_uppercase_acronym_still_resolves() -> None:
    results = scan("See CCP § 425.16 and PC § 187.")
    assert [(r.law_code, r.section_num) for r in results] == [
        ("CCP", "425.16"),
        ("PEN", "187"),
    ]
    # "PC" is ambiguous and keeps its warning.
    assert results[1].confidence == "medium"


def test_code_and_section_of_another_code() -> None:
    """A trailing 'and' must not glue the earlier code name onto the anchor."""
    results = scan("the Civil Code and section 1714 of the Penal Code")
    assert [(r.law_code, r.section_num) for r in results] == [("PEN", "1714")]


# --- Length and performance (item 2) -----------------------------------------


def test_scan_is_linear_in_document_length() -> None:
    """The backward walk used to re-tokenize the whole prefix before every
    anchor: 160 KB took ~1.1 s and the cost grew quadratically. 640 KB would
    have taken ~17 s; bounded windows keep it well under the limit here."""
    import time

    para = (
        "The agency relied on Gov. Code, § 54953, subd. (b), and on section "
        "21080 of the Public Resources Code. (Id., § 21080.5.) Later, the court "
        "considered Cal. Const., art. XIII D, § 6 and former section 6254. "
    )
    text = para * (640_000 // len(para))
    start = time.perf_counter()
    results = scan(text)
    elapsed = time.perf_counter() - start
    assert len(results) == 5 * (640_000 // len(para))
    assert elapsed < 5.0, f"scan of {len(text)} chars took {elapsed:.2f}s"


def test_code_name_beyond_window_is_carried_forward() -> None:
    """A code name beyond the backward window is not part of the citation; it
    is still picked up as a carried-forward mention, at medium confidence."""
    text = "Civil Code " + ("x" * 200) + " section 5"
    assert [(r.law_code, r.confidence) for r in scan(text)] == [("CIV", "medium")]


# --- Found by a recall measurement on 258 published opinions (2026-10-30) ----
# Each case is the shape of a real failure. Carry-forward attached bare cites to
# the last code named, which in opinions was the wrong code about half the time.


def _codes(text: str) -> list[tuple[str, str]]:
    return [(c.law_code, c.section_num) for c in scan(text)]


def test_document_default_footnote_governs_bare_cites() -> None:
    # The footnote sits at the end of the text, after the cites it governs —
    # where CourtListener puts it.
    text = (
        "Claims must be presented first. (§ 911.2, subd. (a).) Code of Civil "
        "Procedure section 473 does not help. (§ 945.4.)\n\n"
        "1 All further statutory references are to the Government Code unless "
        "otherwise indicated."
    )
    assert _codes(text) == [("GOV", "911.2"), ("CCP", "473"), ("GOV", "945.4")]
    first = scan(text)[0]
    assert first.confidence == "high"
    assert "document's own note" in first.warnings[0]


@pytest.mark.parametrize(
    "note",
    [
        "Undesignated statutory references are to the Government\nCode.",
        "Subsequent undesignated statutory citations are to the Government Code.",
        "Unless indicated otherwise, subsequent statutory citations refer to the "
        "Government Code.",
        "Unless otherwise indicated, unspecified references to statutes are to "
        "the Government Code.",
    ],
)
def test_document_default_phrasings(note: str) -> None:
    assert _codes(f"See section 54953. 1 {note}") == [("GOV", "54953")]


def test_document_default_to_a_local_code_drops_bare_cites() -> None:
    text = (
        "Penal Code section 187 is not at issue. The permit was denied under "
        "section 12.22.\n\n3 Undesignated section references are to the Los "
        "Angeles Administrative Code."
    )
    assert _codes(text) == [("PEN", "187")]


@pytest.mark.parametrize(
    "text",
    [
        "(Stats. 2023, ch. 286, § 2.) See Penal Code § 187. (§ 189.)",
        "Penal Code § 187; 42 U.S.C. § 1983.",
        "Penal Code § 187. (Cal. Code Regs., tit. 5, § 4685.)",
        "Penal Code § 187. (Oakland Muni. Code, §§ 4.58.050, 4.58.070.)",
        "Penal Code § 187. (2 Corbin on Contracts (2024) § 78.03.)",
        "Pub. Resources Code § 21000. (Guidelines, §§ 15124, 15126.)",
    ],
)
def test_bare_marker_after_another_source_is_not_carried_forward(text: str) -> None:
    foreign = {"2", "1983", "4685", "4.58.050", "4.58.070", "78.03", "15124", "15126"}
    assert not [num for _, num in _codes(text) if num in foreign], _codes(text)


def test_sentence_starting_section_still_carries_forward() -> None:
    assert _codes("It is in the Government Code. Section 54953 requires it.") == [
        ("GOV", "54953")
    ]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Penal Code § 187; 42 U.S.C. § 1983.", [("PEN", "187")]),
        ("Review is under § 911.2. Code of Civil Procedure section 473 applies.",
         [("CCP", "473")]),
        ("(Oakland Muni. Code, § 4.58.050.) Gov. Code § 1.", [("GOV", "1")]),
        ("section 241, Penal Code; sections 1 and 2 of the Civil Code",
         [("PEN", "241"), ("CIV", "1"), ("CIV", "2")]),
    ],
)
def test_code_name_does_not_reach_across_a_citation_boundary(
    text: str, expected: list[tuple[str, str]]
) -> None:
    assert _codes(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("governed by [Civil Code] section 2924g,", [("CIV", "2924g")]),
        ("see Gov. Code,2 § 945.4.)", [("GOV", "945.4")]),
        ("(POBRA; Gov. Code 1, § 3300 et seq.)", [("GOV", "3300")]),
        ("Elections Code 7 sections 9051, subdivision (e) and 13119",
         [("ELEC", "9051"), ("ELEC", "13119")]),
        ("Division 4 (commencing with Section 1400) of the Probate Code",
         [("PROB", "1400")]),
    ],
)
def test_opinion_formatting_around_explicit_cites(
    text: str, expected: list[tuple[str, str]]
) -> None:
    assert _codes(text) == expected


# --- attribution: how the code was found (added 2026-11-07) -----------------

@pytest.mark.parametrize(
    "text,default,expected",
    [
        ("Gov. Code, § 54953.", None, "named"),
        ("Section 241 of the Public Utilities Code", None, "named"),
        ("Cal. Const., art. XIII D, § 6", None, "named"),
        ("(Gov. Code, § 54953.) It must be posted. (Id., § 54954.2.)", None, "id"),
        ("as defined in subdivision (a) of Section 56134", "EDC", "caller_default"),
        (
            "Section 1001.36 permits diversion.\n\n1 All further statutory "
            "references are to the Penal Code.",
            None,
            "document_default",
        ),
        ("The Government Code governs here. Section 54953 requires notice.", None, "carried"),
    ],
)
def test_attribution_says_where_the_code_came_from(
    text: str, default: str | None, expected: str
) -> None:
    results = scan(text, default_law_code=default)
    assert results, text
    assert results[-1].attribution == expected


def test_constitution_inferred_from_an_earlier_mention_is_carried() -> None:
    text = "The Constitution limits this. Under art. XIII D, § 6, notice is required."
    (result,) = scan(text)
    assert (result.law_code, result.article) == ("CONS", "XIII D")
    assert result.attribution == "carried"


def test_list_members_share_the_anchor_attribution() -> None:
    results = scan("The Penal Code applies. Sections 330a and 330.1 prohibit it.")
    assert [r.attribution for r in results] == ["carried", "carried"]


# --- found in review, 2026-11-07 ---------------------------------------------

@pytest.mark.parametrize(
    "text",
    [
        "We look to the Government Code. (§ 54953.)",
        "We apply the Code of Civil Procedure. Section 425.16 applies.",
    ],
)
def test_code_that_ends_the_previous_sentence_is_carried_not_named(text: str) -> None:
    (result,) = scan(text)
    assert result.attribution == "carried"


@pytest.mark.parametrize(
    "text",
    ["Code Civ. Proc. § 425.16 applies.", "Gov. Code, § 54953.", "Gov. Code § 54953."],
)
def test_abbreviated_code_name_before_the_marker_is_still_named(text: str) -> None:
    (result,) = scan(text)
    assert result.attribution == "named"


@pytest.mark.parametrize(
    "text,section",
    [
        ("Penal Code section 187 through 2023", "187"),
        ("Gov. Code section 5 to 10 days", "5"),
        ("Gov. Code section 900 to 15 percent", "900"),
        ("Gov. Code sections 54962-54950", "54962"),
    ],
)
def test_a_count_year_or_backward_number_is_not_a_range_end(text: str, section: str) -> None:
    (result,) = scan(text)
    assert (result.section_num, result.range_end) == (section, None)


def test_four_digit_range_ending_in_a_year_shape_is_still_a_range() -> None:
    (result,) = scan("Gov. Code §§ 1990 through 2010 apply.")
    assert (result.section_num, result.range_end) == ("1990", "2010")


def test_reference_start_points_list_members_at_the_first_citation() -> None:
    results = scan("See Penal Code sections 330a and 330.1 here.")
    first, second = results
    assert first.reference_start == first.span_start
    assert second.reference_start == first.span_start
    assert "Penal Code" in first.raw and "Penal" not in second.raw
