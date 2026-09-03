"""Normalization shared by the policy/ДС folder- and file-name matchers.

Real client folders come from Windows shares filled in by hand, so names
carry things that look identical on screen but differ byte-wise. The worst
offender is Latin/Cyrillic homoglyphs: «ДC» typed with a Latin "C" (U+0043)
renders exactly like «ДС» with a Cyrillic "С" (U+0421), and an exact-match
lookup silently finds nothing. Non-breaking spaces and stray casing do the
same. Everything that matches names against a convention normalizes here
first, so those never turn into a silent "not found".
"""

# Latin -> Cyrillic for characters that render identically.
_HOMOGLYPHS = str.maketrans({
    "A": "А", "B": "В", "C": "С", "E": "Е", "H": "Н", "K": "К", "M": "М",
    "O": "О", "P": "Р", "T": "Т", "X": "Х",
    "a": "а", "c": "с", "e": "е", "o": "о", "p": "р", "x": "х", "y": "у",
    " ": " ",   # non-breaking space
    " ": " ",
    " ": " ",
})


def fold(text: str) -> str:
    """Case-folded, homoglyph-folded, whitespace-collapsed form for matching."""
    return " ".join(text.translate(_HOMOGLYPHS).lower().split())
