"""The Ops.Cal.Atty.Gen. reporter: canonical form, known variants, normalization.

One home, because two very different callers need identical knowledge:

* `pipelines/caag/index.py` parses "Official Citation: 62 Ops.Cal.Atty.Gen. 822"
  out of the OAG index.
* `shared/citations/extra.py` finds AG citations inside opinion BODIES, to
  build the in-corpus citation graph.

Both must accept exactly the same set of spellings. Keeping two copies would
guarantee they drift, and a drift here is silent: the graph would simply miss
edges spelled a way the index parser knows about.

The variant list is empirical -- every entry was observed in the live corpus,
not imagined. `freelawproject/reporters-db` carries the canonical reporter
(cite_type "specialty"), but has no reason to carry OAG's own typos.
"""

from __future__ import annotations

import re

#: Canonical California Style Manual 4th ed. form (§ 1:23).
REPORTER = "Ops.Cal.Atty.Gen."

#: Accepted spellings, reduced to lowercase letters only. Each was observed:
KNOWN_REPORTERS = {
    "opscalattygen",   # canonical
    "opscalattgen",    # "Att" for "Atty"
    "calopsattygen",   # words transposed -- systematic across 1985-87
    "calopsattgen",    # transposed and "Att"
    "opscaiattygen",   # capital I for lowercase l in "Cal" -- all of 2007
}


#: Regex fragment matching the reporter name itself, in any observed spelling.
#:
#: This has to be SPECIFIC rather than a loose "letters and dots" run. A
#: permissive pattern that is validated only after matching still CONSUMES the
#: text it rejected, and `re.finditer` does not back up -- so a rejected
#: near-match swallows the real citation immediately after it. That cost us
#: "62 Ops.Cal.Atty.Gen. 822" in a test, because the preceding
#: "...section 1090. Also 62..." matched loosely first and was thrown away.
#:
#: Covers, in one alternation: either word order, "Att" or "Atty", optional
#: periods and spaces anywhere, and the capital-I-for-l spelling of "Cal".
REPORTER_RX = (
    r"(?:Ops\.?\s*Ca[lI]\.?|Ca[lI]\.?\s*Ops\.?)\s*Att(?:y)?\.?\s*Gen\.?"
)


def reporter_key(blob: str) -> str:
    """Reduce a reporter blob to comparable letters.

    'Ops.Cal. Atty.Gen.' -> 'opscalattygen'
    """
    return re.sub(r"[^a-z]", "", blob.lower())


def is_known(blob: str) -> bool:
    return reporter_key(blob) in KNOWN_REPORTERS
