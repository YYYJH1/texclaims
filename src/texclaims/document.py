"""Manuscript loading, masking, and the number-token grammar.

Masking replaces characters with spaces so every byte offset (and thus
every line number) in the masked text is identical to the raw file.  Two
masked views exist, because anchoring and scanning want opposite things:

* ``masked``      hides comments and the arguments of structural commands.
  Anchors match against it, so the prose an author anchors on is intact —
  including control words like ``\\pm`` that patterns rely on.
* ``scan_masked`` additionally blanks control words and typesetting
  dimensions.  Coverage scans it, so ``\\pm0.99`` yields a token (the
  control word no longer glues itself to the digits) while the length in
  ``\\hspace{12pt}`` does not.
"""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass
from pathlib import Path

from .errors import LedgerError

# --- number-token grammar ---------------------------------------------------
# Sign (incl. Unicode minus), thousands groups or plain digits, optional
# decimals (a leading-dot form covers APA-style ".05"), optional exponent,
# optional (escaped) percent.  The leading guard keeps identifiers (v2,
# seed42) and decimal continuations (1.2.3) out -- and is ASCII, because a
# Unicode \w would swallow every number touching CJK text, blinding the scan
# on a Chinese manuscript.  There is deliberately no
# trailing \w guard: "120ms" and "2.4x" must still yield a number, or the
# coverage scan goes blind exactly where results are quoted with units.
# A sign only counts when it is not itself preceded by a dash: "3--5" is a
# range, and reading the second dash as a minus both invents -5 and hides 5.
_SIGN = "(?<![-\u2212])[+\\-\u2212]"
# Thousands come in three forms: bare comma, LaTeX's 36{,}600 and 50\,000.
# Bare comma and \, forms are refused after another joined digit run, because
# "(6,36,600)" is a tuple of three numbers and reading "36,600" out of it
# fabricates a number the manuscript never printed.
_THOUSANDS = r"(?<!\d,)(?<!\d, )\d{1,3}(?:,\d{3})+|\d{1,3}(?:\{,\}\d{3})+|(?<!\d\\,)\d{1,3}(?:\\,\d{3})+"
_MAGNITUDE = rf"(?:{_THOUSANDS}|\d+)(?:\.\d+)?|\.\d+"
NUMBER_TOKEN = rf"(?:{_SIGN})?(?:{_MAGNITUDE})(?:[eE][+\-]?\d+)?"
NUMBER_GROUP = rf"({NUMBER_TOKEN})"
NUMBER_RE = re.compile(rf"(?<![0-9A-Za-z_.]){NUMBER_TOKEN}(?:\\?%)?(?!\.\d)")

_PCT_TAIL_RE = re.compile(r"\\?%$")


@dataclass(frozen=True)
class ParsedNumber:
    value: float
    decimals: int  # effective displayed decimal places (exponent-adjusted)
    token: str


def normalize_number(token: str) -> str:
    """Remove display-only syntax before either float or exact integer parsing."""
    s = _PCT_TAIL_RE.sub("", token.strip())
    return s.replace("\u2212", "-").replace("{,}", "").replace("\\,", "").replace(",", "")


def parse_number(token: str) -> ParsedNumber:
    """Parse a captured token into a value plus its display precision."""
    s = normalize_number(token)
    try:
        value = float(s)
    except ValueError as exc:  # regex should prevent this; belt and braces
        raise LedgerError(f"captured text {token!r} is not a number") from exc
    mantissa, exp = s, 0
    m = re.search(r"[eE]([+\-]?\d+)$", s)
    if m:
        exp = int(m.group(1))
        mantissa = s[: m.start()]
    decimals = len(mantissa.split(".")[1]) if "." in mantissa else 0
    return ParsedNumber(value=value, decimals=decimals - exp, token=token)


def percent_suffix(text: str) -> bool:
    """True when ``text`` is exactly a percent sign, escaped or not."""
    return text in ("", "%", "\\%")


# --- masking ----------------------------------------------------------------

_STRUCT_RE = re.compile(
    r"\\(?:cite[a-zA-Z]*|ref|eqref|pageref|autoref|[cC]ref|label|includegraphics"
    r"|bibliographystyle|bibliography|input|include|url|begin|end)\*?"
    r"(?:\[[^\]\n]*\]){0,2}\{[^{}\n]*\}"
)
_HREF_RE = re.compile(r"\\href\{[^{}\n]*\}")  # mask the URL argument only
_CONTROL_WORD_RE = re.compile(r"\\[a-zA-Z]+")  # \pm, \approx, \times, \section
# A brace alone does not identify a dimension: \textbf{9.9mm} is a reported
# measurement. Only recognised length-taking commands may hide such values;
# an unfamiliar command leaves its numbers for the author to account for.
_DIM_RE = re.compile(r"(?<![A-Za-z])(?:width|height|scale|depth)=-?[\d.]+")
_LENGTH = r"[+\-]?(?:\d+(?:\.\d*)?|\.\d+)\s*(?:pt|em|ex|cm|mm|in|bp)\b"
_GLUE = rf"{_LENGTH}(?:\s+(?:plus|minus)\s+{_LENGTH})*"
_BRACED_LENGTH = rf"\{{\s*{_LENGTH}\s*\}}"
_UNIT_RE = re.compile(
    rf"\\(?:hspace|vspace)\*?\s*\{{\s*{_GLUE}\s*\}}"
    rf"|\\(?:setlength|addtolength)\s*\{{\s*\\[A-Za-z]+\s*\}}"
    rf"\s*\{{\s*{_GLUE}\s*\}}"
    rf"|\\rule(?:\s*\[\s*{_LENGTH}\s*\])?\s*{_BRACED_LENGTH}\s*{_BRACED_LENGTH}"
    rf"|\\fontsize\s*{_BRACED_LENGTH}\s*{_BRACED_LENGTH}"
    rf"|\\(?:hskip|vskip|kern)(?![A-Za-z])\s*{_GLUE}")
# A fraction of a length command is unambiguously typesetting: no measurement
# in prose is written as "0.45\textwidth".  Recognised before control words
# are blanked, or only the bare fraction would be left behind.
_RELATIVE_LEN_RE = re.compile(
    r"-?[\d.]+\s*\\(?:text|line|column|paper)(?:width|height)\b"
    r"|-?[\d.]+\s*\\(?:baselineskip|hsize|vsize|tabcolsep|arrayrulewidth)\b")

_TEX_SUFFIXES = {".tex", ".sty", ".cls"}


def _blank(match: re.Match[str]) -> str:
    return " " * (match.end() - match.start())


# Constructions where a percent sign is literal.  These must be blanked before
# comment masking runs, or the rest of the line disappears from the scan --
# a URL with %20 in it once hid every number that followed.
_VERB_RE = re.compile(r"\\verb\*?(.)(?:(?!\1).)*\1")
_LSTINLINE_RE = re.compile(
    r"\\lstinline(?:\[[^\]\n]*\])?(?:\{[^{}\n]*\}|(.)(?:(?!\1).)*\1)")
_URLLIKE_RE = re.compile(r"(?<!\\)\\(?:url|path)\s*\{[^{}\n]*\}")
_HREF_URL_RE = re.compile(r"(?<!\\)\\href(?:\[[^\]\n]*\])?\{[^{}\n]*\}")
_VERBATIM_ENV_RE = re.compile(
    r"\\begin\{(verbatim\*?|lstlisting|minted|Verbatim|comment)\}.*?\\end\{\1\}", re.S)
_TEX_COMMAND_RE = re.compile(r"\\(?:[a-zA-Z]+|.)")
_IF_COMMANDS = {
    "\\if", "\\ifcat", "\\ifnum", "\\ifdim", "\\ifodd", "\\ifvmode",
    "\\ifhmode", "\\ifmmode", "\\ifinner", "\\ifvoid", "\\ifhbox", "\\ifvbox",
    "\\ifx", "\\ifeof", "\\iftrue", "\\iffalse", "\\ifcase", "\\ifdefined",
    "\\ifcsname", "\\iffontchar",
}


def _blank_keep_newlines(match: re.Match[str]) -> str:
    """Blank a span but keep its line structure, for multi-line environments."""
    return "".join(c if c == "\n" else " " for c in match.group(0))


def _mask_false_branches(text: str) -> str:
    # A regex ending at \fi also erases the live \else branch. Track nested
    # conditionals so an inner \else or \fi cannot end the outer false branch.
    # Only \iffalse is evaluated; both arms of other conditions stay visible.
    branches: list[bool | None] = []
    chars = list(text)
    hidden_start = 0
    for m in _TEX_COMMAND_RE.finditer(text):
        command = m.group(0)
        was_hidden = False in branches
        if command == "\\iffalse":
            branches.append(False)
        elif branches and command.startswith("\\if"):
            if command not in _IF_COMMANDS:
                # A custom conditional's nesting is unknown; guessing could
                # hide the live prose after the outer \else.
                raise LedgerError(f"cannot safely mask {command!r} inside \\iffalse")
            branches.append(None)
        elif branches and command == "\\else":
            if branches[-1] is False:
                branches[-1] = True
        elif branches and command == "\\fi":
            branches.pop()
        hidden = False in branches
        if hidden and not was_hidden:
            hidden_start = m.start()
        elif was_hidden and not hidden:
            chars[hidden_start:m.end()] = [
                c if c == "\n" else " " for c in text[hidden_start:m.end()]]
    if branches:
        raise LedgerError("unterminated \\iffalse conditional")
    return "".join(chars)


def mask_comments(text: str) -> str:
    # Blank every construction where a percent is literal before looking for
    # comments; otherwise one % inside a URL or a listing silently eats the
    # remainder of its line, taking real results with it.
    text = _VERBATIM_ENV_RE.sub(_blank_keep_newlines, text)
    text = _VERB_RE.sub(_blank, text)
    text = _LSTINLINE_RE.sub(_blank, text)
    text = _URLLIKE_RE.sub(_blank, text)
    text = _HREF_URL_RE.sub(_blank, text)
    lines = []
    for line in text.split("\n"):
        i = 0
        while (j := line.find("%", i)) != -1:
            backslashes = 0
            k = j - 1
            while k >= 0 and line[k] == "\\":
                backslashes += 1
                k -= 1
            if backslashes % 2 == 0:  # unescaped % starts a comment
                line = line[:j] + " " * (len(line) - j)
                break
            i = j + 1
        lines.append(line)
    # Comments and verbatim text must not supply conditional delimiters.
    return _mask_false_branches("\n".join(lines))


class Document:
    """A manuscript file with offset-preserving masked views."""

    def __init__(self, root: Path, rel_name: str) -> None:
        self.rel_name = rel_name
        self.path = root / rel_name
        try:
            self.raw = self.path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise LedgerError(f"cannot read document: {exc}", path=rel_name) from exc
        is_tex = self.path.suffix.lower() in _TEX_SUFFIXES
        if is_tex:
            masked = mask_comments(self.raw)
            masked = _STRUCT_RE.sub(_blank, masked)
            masked = _HREF_RE.sub(_blank, masked)
        else:  # .md and friends: no comment grammar, mask nothing
            masked = self.raw
        self.masked = masked
        if is_tex:
            # Dimensions are recognised while their control words are still
            # intact, then the remaining control words are blanked so a number
            # glued to one (\pm0.99) is not hidden behind it.
            scan_masked = _RELATIVE_LEN_RE.sub(_blank, masked)
            scan_masked = _DIM_RE.sub(_blank, scan_masked)
            scan_masked = _UNIT_RE.sub(_blank_keep_newlines, scan_masked)
            scan_masked = _CONTROL_WORD_RE.sub(_blank, scan_masked)
        else:
            scan_masked = masked
        self.scan_masked = scan_masked
        self._newlines = [m.start() for m in re.finditer("\n", self.raw)]

    def line_of(self, pos: int) -> int:
        return bisect.bisect_right(self._newlines, pos - 1) + 1

    def snippet(self, start: int, end: int, radius: int = 40) -> str:
        lo, hi = max(0, start - radius), min(len(self.raw), end + radius)
        return " ".join(self.raw[lo:hi].split())

    def token_at(self, start: int) -> re.Match[str] | None:
        """The complete number token covering ``start``, if any.

        Used to reject a capture group that grabbed only part of a number:
        a group matching "88" out of "88.9", or one that left the minus
        sign behind, must not be accepted as that number.

        Scanned on ``scan_masked`` so that a number glued to a control word
        (``\\pm0.51``) is still recognised as a whole token; on ``masked`` the
        preceding letters would suppress it and the guard would pass anything.
        """
        window = max(0, start - 32)
        # scan_masked first, so a number glued to a control word is seen whole.
        # If that view blanked the position (a dimension, say), fall back to
        # `masked` rather than returning None: an unguarded capture there would
        # be free to take half a number.
        for view in (self.scan_masked, self.masked):
            for m in NUMBER_RE.finditer(view, window):
                if m.start() <= start < m.end():
                    return m
                if m.start() > start:
                    break
        return None
