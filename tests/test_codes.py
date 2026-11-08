"""Every California code, in every form a California writer uses, resolves.

Before the 2026-10-30 fix, 22 common forms failed: six of the 29 CSM
abbreviations (including "Pub. Resources Code", the CEQA code), "Code of Civil
Procedure", and every long form written with "&". The lookup was an exact match
on keys that disagreed with the normalizer about "&", "and", and "of".
"""

from __future__ import annotations

import pytest

from ca_citations.codes import resolve_code
from ca_citations.parser import parse
from ca_citations.scanner import scan

# (law_code, official long name, California Style Manual 4th ed. abbreviation)
ALL_CODES: list[tuple[str, str, str]] = [
    ("BPC", "Business and Professions Code", "Bus. & Prof. Code"),
    ("CIV", "Civil Code", "Civ. Code"),
    ("CCP", "Code of Civil Procedure", "Code Civ. Proc."),
    ("COM", "Commercial Code", "Com. Code"),
    ("CORP", "Corporations Code", "Corp. Code"),
    ("EDC", "Education Code", "Ed. Code"),
    ("ELEC", "Elections Code", "Elec. Code"),
    ("EVID", "Evidence Code", "Evid. Code"),
    ("FAM", "Family Code", "Fam. Code"),
    ("FIN", "Financial Code", "Fin. Code"),
    ("FGC", "Fish and Game Code", "Fish & G. Code"),
    ("FAC", "Food and Agricultural Code", "Food & Agr. Code"),
    ("GOV", "Government Code", "Gov. Code"),
    ("HNC", "Harbors and Navigation Code", "Harb. & Nav. Code"),
    ("HSC", "Health and Safety Code", "Health & Saf. Code"),
    ("INS", "Insurance Code", "Ins. Code"),
    ("LAB", "Labor Code", "Lab. Code"),
    ("MVC", "Military and Veterans Code", "Mil. & Vet. Code"),
    ("PEN", "Penal Code", "Pen. Code"),
    ("PROB", "Probate Code", "Prob. Code"),
    ("PCC", "Public Contract Code", "Pub. Contract Code"),
    ("PRC", "Public Resources Code", "Pub. Resources Code"),
    ("PUC", "Public Utilities Code", "Pub. Util. Code"),
    ("RTC", "Revenue and Taxation Code", "Rev. & Tax. Code"),
    ("SHC", "Streets and Highways Code", "Sts. & Hy. Code"),
    ("UIC", "Unemployment Insurance Code", "Unemp. Ins. Code"),
    ("VEH", "Vehicle Code", "Veh. Code"),
    ("WAT", "Water Code", "Wat. Code"),
    ("WIC", "Welfare and Institutions Code", "Welf. & Inst. Code"),
]


def _forms(long_name: str, csm: str) -> list[str]:
    """CSM abbreviation, long name, and the long name / CSM with '&' and 'and'
    swapped — writers use both."""
    forms = [csm, long_name]
    forms.append(long_name.replace(" and ", " & "))
    forms.append(csm.replace(" & ", " and "))
    return list(dict.fromkeys(forms))


CASES = [
    pytest.param(law_code, form, id=f"{law_code}:{form}")
    for law_code, long_name, csm in ALL_CODES
    for form in _forms(long_name, csm)
]


def test_table_covers_all_29_codes() -> None:
    assert len(ALL_CODES) == 29
    assert len({c for c, _, _ in ALL_CODES}) == 29


@pytest.mark.parametrize(("law_code", "form"), CASES)
def test_code_name_resolves(law_code: str, form: str) -> None:
    entry = resolve_code(form)
    assert entry is not None, form
    assert entry.law_code == law_code


@pytest.mark.parametrize(("law_code", "form"), CASES)
def test_parser_section_form(law_code: str, form: str) -> None:
    parsed = parse(f"{form} section 100")
    assert (parsed.law_code, parsed.section_num) == (law_code, "100")


@pytest.mark.parametrize(("law_code", "form"), CASES)
def test_scanner_in_prose(law_code: str, form: str) -> None:
    results = scan(f"The court relied on {form} section 100 in reaching that result.")
    assert [(r.law_code, r.section_num) for r in results] == [(law_code, "100")]


@pytest.mark.parametrize(("law_code", "form"), CASES)
def test_scanner_csm_parenthetical(law_code: str, form: str) -> None:
    results = scan(f"The agency must act. ({form}, § 100, subd. (b).)")
    assert len(results) == 1
    cite = results[0]
    assert (cite.law_code, cite.section_num, cite.subsection_path) == (
        law_code,
        "100",
        ["b"],
    )
    assert cite.confidence == "high"


@pytest.mark.parametrize(
    ("form", "law_code"),
    [
        # Bluebook forms
        ("Cal. Pub. Res. Code", "PRC"),
        ("Cal. Sts. & High. Code", "SHC"),
        ("Cal. Gov't Code", "GOV"),
        ("Cal. Health & Safety Code", "HSC"),
        ("Cal. Food & Agric. Code", "FAC"),
        # Variants found in the 2026-10-30 review
        ("Pub. Utilities Code", "PUC"),
        ("Pub. Utils. Code", "PUC"),
        ("Pub. Resource Code", "PRC"),
        ("Food and Agriculture Code", "FAC"),
        ("Harb. and Nav. Code", "HNC"),
        ("Welf. and Inst. Code", "WIC"),
    ],
)
def test_other_common_forms(form: str, law_code: str) -> None:
    entry = resolve_code(form)
    assert entry is not None and entry.law_code == law_code


@pytest.mark.parametrize("raw", ["Civil Code and", "and Penal Code", "Civil and"])
def test_leading_or_trailing_and_does_not_resolve(raw: str) -> None:
    """Only an interior 'and' is a conjunction inside a code name. A dangling
    one means the run crossed into the surrounding sentence."""
    assert resolve_code(raw) is None
