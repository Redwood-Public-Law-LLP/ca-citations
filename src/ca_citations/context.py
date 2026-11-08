"""What sits immediately AFTER a citation: a quotation, or a parenthetical.

Both are mechanical. Nothing here decides whether a citation is approving or
critical, and nothing is inferred from tone; treatment labels are deliberately
left out until someone decides, in writing, to add them. Free Law Project
shipped `depth` and left `treatment` commented out in their own model; what
they built instead was parenthetical extraction, which
surfaces the citing document's OWN words about the authority and lets the
reader judge. This module is that, plus the quotation flag their model also
leaves commented out (`quoted`).

Two design rules, both from the precision-first rule (precision beats recall):

* **Verbatim or nothing.** A captured quotation or parenthetical is a substring
  of the source text, never a paraphrase and never truncated. If it cannot be
  captured whole, it is not captured.
* **Decline rather than guess.** Every gap rule below is tuned to drop the
  ambiguous case. Missing a real quotation costs a search hit; attaching the
  wrong one to a citation puts words in a document's mouth.
"""

from __future__ import annotations

import re

# --- quotations -------------------------------------------------------------

# Quote glyphs that occur in this corpus. Older OAG PDFs use straight quotes,
# newer ones curly; both appear inside a single document after a re-OCR.
_OPENERS = {'"': '"', "“": "”", "„": "“"}

# How far after the citation a quotation may begin. Measured against the
# corpus: the introducing clause is usually short ("provides:", "states as
# follows:"), and the longest real one observed carries a session-law cite --
# "(Stats. 1982, ch. 257, § 1), effective January 1, 1983, to read as follows:"
# -- at just under 80 characters.
MAX_GAP = 120

# A quotation shorter than this is a term of art, not statutory text: AG
# opinions quote "Act", "person", "public official" constantly as defined
# terms. A quotation verifier cannot do anything useful with those,
# and counting them would make `quoted` true almost everywhere.
MIN_QUOTE_CHARS = 20

# ...and it must be mostly words. Older opinions reproduce statutory tables
# whose dot leaders sit inside the quotation marks, so ". . . . . . . . . ."
# clears the length bar while carrying no text to verify. Observed in the live
# corpus (opinion 04-808, Health & Saf. Code § 13890).
MIN_QUOTE_LETTERS = 15

# Runaway guard. An unmatched opening quote -- common where OCR dropped the
# closer -- would otherwise swallow the rest of the document.
MAX_QUOTE_CHARS = 1500

# A sentence ended between the citation and the quotation, so the quotation
# belongs to whatever came next, not to this citation. A period followed by a
# capital or a digit IS a sentence end here; a period followed by a lowercase
# letter is an abbreviation ("subd. (a)") and is allowed through. That also,
# usefully, rejects a case name -- "v. Jones" reads as a sentence break, and a
# quotation after one is the case's words, not the statute's -- and the running
# page furniture that pymupdf interleaves between a footnote and the text it
# annotates ("Lab. Code, § 1773. 11 25-601 statutory scheme ..." in opinion
# 25-601, where the quotation that follows is the court's, not the statute's).
_SENTENCE_END = re.compile(r"[.?!][\"'”)\]]?\s+(?=[A-Z0-9“\"])")

# A citation can swallow the period that ends its own sentence -- the scanner
# reports "Section 17.1 of the Welfare and Institutions Code." span and all --
# so the sentence-break test above cannot see it. When that happens AND nothing
# is said between the citation and the quotation, the quotation is a fresh
# block quote whose subject is whatever the finished sentence was about, not
# the citation that ended it. Opinion 84-702 is the case: a sentence about
# Education Code section 48201 ends by cross-referencing Welf. & Inst. Code
# section 17.1, and the block quote that follows is section 48201's text.
#
# A quotation INTRODUCED after such a citation ("... Institutions Code." That
# section provides as follows: "...") is kept -- the introducing clause is what
# ties it to the citation.
_CITE_ENDS_SENTENCE = re.compile(r"""[.?!]["'”)\]]?$""")

# An opening quotation mark is preceded by a space or an opening bracket. A
# straight `"` is the same glyph opening and closing, so without this a CLOSING
# quote reads as an opener and the PROSE AFTER IT is captured as a quotation --
# which is worse than capturing nothing, since it attributes the opinion's own
# words to the statute. Observed in opinion 83-608: `... Government Code."2
# While it is thus clear that ...`.
_OPENER_PRECEDERS = " \t\r\n([{"

# A semicolon separates citation items, and a section symbol -- or the word
# "section" followed by a number -- starts ANOTHER citation. Either means the
# quotation that follows probably belongs to a different authority, and if it
# does, that authority's own row picks it up. Opinion 07-312 is the case in
# point: "Government Code section 6103 did not apply where Government Code
# section 25283 'specifically provides otherwise: ...'" quotes § 25283, not
# § 6103.
_GAP_STOP = re.compile(r"[;§]|\bsections?\s+\d", re.IGNORECASE)


def find_quote(text: str, end: int) -> str | None:
    """Return the quoted passage following the citation ending at `end`.

    Returns the quotation's INNER text, verbatim and whole -- suitable for
    handing to a statute quotation verifier, which is the entire point of
    recording it. Whitespace is normalized (extracted PDF text wraps mid-
    sentence), because a line break inside a quotation is an artifact of the
    PDF, not of the source. Nothing else is altered.
    """
    window = text[end : end + MAX_GAP + MAX_QUOTE_CHARS]
    for offset, char in enumerate(window[:MAX_GAP]):
        closer = _OPENERS.get(char)
        if closer is None:
            continue
        prev = window[offset - 1] if offset else (text[end - 1] if end else " ")
        if prev not in _OPENER_PRECEDERS:
            return None  # a closing quote, not an opening one
        gap = window[:offset]
        if not gap.strip() and _CITE_ENDS_SENTENCE.search(text[max(0, end - 2) : end]):
            return None  # a new sentence's block quote, not this citation's
        # The quote glyph itself is part of the sentence-end test: a period,
        # a space and then the opening quotation mark is a new sentence, and
        # what follows it is the opinion's own argument or a case's words
        # rather than the section's text (opinion 94-604, Gov. Code § 65852.3).
        if _GAP_STOP.search(gap) or _SENTENCE_END.search(gap + char):
            return None  # the quotation belongs to something else
        body = window[offset + 1 : offset + 1 + MAX_QUOTE_CHARS]
        close_at = body.find(closer)
        if close_at < 0:
            return None  # unbalanced: OCR dropped the closer
        quote = " ".join(body[:close_at].split())
        if len(quote) < MIN_QUOTE_CHARS or " " not in quote:
            return None  # a defined term, not a passage of statutory text
        if sum(ch.isalpha() for ch in quote) < MIN_QUOTE_LETTERS:
            return None  # a dot leader or a table rule, not prose
        return quote
    return None


# --- explanatory parentheticals ---------------------------------------------

# The signal words that make a parenthetical EXPLANATORY rather than
# bibliographic. Requiring one is what keeps "(2002)", "(a)", "(emphasis
# added)" and "(Stats. 1981, ch. 1171, § 6)" out of the column.
#
# The cost is real and is accepted: California Style Manual form also allows a
# bracketed explanation with no signal verb -- "(Gov. Code, § 40100
# [legislative body may by ordinance 'appropriate a sum for a city publicity
# fund'])" -- and that form is NOT captured. A missed parenthetical is a lost
# search hit; a wrongly captured one reads as the document's characterization
# of an authority when it is not.
_SIGNALS = (
    # what a court or the AG does with an authority
    "holding", "concluding", "finding", "stating", "noting", "quoting",
    "citing", "explaining", "observing", "reasoning", "construing",
    "interpreting", "declaring", "determining", "emphasizing", "applying",
    "distinguishing", "disapproving", "overruling", "affirming", "reversing",
    "upholding", "rejecting", "recognizing", "discussing", "summarizing",
    "adopting", "codifying", "confirming", "acknowledging", "assuming",
    # what a statute or regulation does -- the dominant form on statutory cites
    "providing", "requiring", "prohibiting", "authorizing", "permitting",
    "allowing", "defining", "describing", "establishing", "imposing",
    "granting", "directing", "mandating", "governing", "limiting",
    "excluding", "exempting", "extending", "specifying", "listing",
    "setting forth", "referring to", "relating to",
)
_SIGNAL_RX = re.compile(
    r"(?:" + "|".join(re.escape(s) for s in _SIGNALS) + r")\b", re.IGNORECASE
)

_OPEN_TO_CLOSE = {"(": ")", "[": "]"}

# Characters that may sit between the citation and its parenthetical: a pin
# page ("85 Ops.Cal.Atty.Gen. 60, 62"), commas, whitespace.
_SKIPPABLE = re.compile(r"[\s,]*\d{0,4}(?:\s*[-‐-―]\s*\d{1,4})?[\s,]*")

# How many non-explanatory parentheticals may be stepped over on the way -- a
# year, a subdivision, a session-law cite. Three is generous; more than that
# and whatever follows is no longer attached to this citation.
MAX_SKIPS = 3
MAX_PARENTHETICAL_CHARS = 600


def _balanced_span(text: str, start: int) -> int | None:
    """Index just past the bracket opened at `start`, or None if unbalanced."""
    opener = text[start]
    closer = _OPEN_TO_CLOSE[opener]
    depth = 0
    for i in range(start, min(len(text), start + MAX_PARENTHETICAL_CHARS + 2)):
        if text[i] == opener:
            depth += 1
        elif text[i] == closer:
            depth -= 1
            if depth == 0:
                return i + 1
    return None


def find_parenthetical(text: str, end: int) -> str | None:
    """Return the explanatory parenthetical following the citation at `end`.

    Verbatim, including its own brackets, whitespace-normalized for PDF line
    wrapping. Bibliographic parentheticals (a year, a subdivision, a session
    law) are stepped over, not returned. Returns None -- the common case --
    when the citation carries no explanatory parenthetical.
    """
    pos = end
    for _ in range(MAX_SKIPS + 1):
        skip = _SKIPPABLE.match(text, pos)
        pos = skip.end() if skip else pos
        if pos >= len(text) or text[pos] not in _OPEN_TO_CLOSE:
            return None
        close = _balanced_span(text, pos)
        if close is None:
            return None  # unbalanced, or longer than a parenthetical ever is
        inner = text[pos + 1 : close - 1]
        if _SIGNAL_RX.match(inner.lstrip()):
            return " ".join(text[pos:close].split())
        pos = close  # bibliographic; step over it and look at the next one
    return None
