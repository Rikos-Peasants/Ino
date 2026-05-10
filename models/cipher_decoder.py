"""
Multi-format cipher / encoding decoder for Discord messages.

Supported encodings (tried in priority order):
  1. Braille Unicode   ⠓⠑⠇⠇⠕
  2. Homestuck/Alien   ⍑ᒷᓭᒷ ᓵ⍑ᔑ∷ᔑᓵℸᒷ∷ᓭ
  3. Morse code        .... . .-.. .-.. ---
  4. Binary ASCII      01001000 01100101 ...
  5. NATO phonetic     Hotel Echo Lima Lima Oscar
  6. Base64            aGVsbG8gd29ybGQ=
  7. Zalgo text        h̴̖̒ȅ̷̡l̵͍̐l̸̗̑o̷͈̅
  8. Upside-down text  oʃʃǝH
  9. Leet speak        h3ll0 w0rld
"""
from __future__ import annotations

import base64
import re
import unicodedata
from typing import Optional


# ---------------------------------------------------------------------------
# 1. BRAILLE
# ---------------------------------------------------------------------------
_BRAILLE_TO_CHAR: dict[str, str] = {
    "\u2801": "a", "\u2803": "b", "\u2809": "c", "\u2819": "d", "\u2811": "e",
    "\u280b": "f", "\u281b": "g", "\u2813": "h", "\u280a": "i", "\u281a": "j",
    "\u2805": "k", "\u2807": "l", "\u280d": "m", "\u281d": "n", "\u2815": "o",
    "\u280f": "p", "\u281f": "q", "\u2817": "r", "\u280e": "s", "\u281e": "t",
    "\u2825": "u", "\u2827": "v", "\u283a": "w", "\u282d": "x", "\u283d": "y",
    "\u2835": "z",
    # Numbers (after number indicator ⠼)
    "\u2801": "1", "\u2803": "2", "\u2809": "3", "\u2819": "4", "\u2811": "5",
    "\u280b": "6", "\u281b": "7", "\u2813": "8", "\u280a": "9", "\u281a": "0",
    "\u2800": " ",  # blank braille cell = space
}

def _decode_braille(text: str) -> Optional[str]:
    chars = [c for c in text if c != " "]
    braille_chars = [c for c in chars if "\u2800" <= c <= "\u28ff"]
    if len(braille_chars) < 3 or len(braille_chars) / max(len(chars), 1) < 0.5:
        return None
    result = []
    number_mode = False
    for ch in text:
        if ch == "\u283c":   # number indicator ⠼
            number_mode = True
            continue
        if ch == " ":
            number_mode = False
            result.append(" ")
            continue
        if "\u2800" <= ch <= "\u28ff":
            result.append(_BRAILLE_TO_CHAR.get(ch, "?"))
        else:
            result.append(ch)
    return "".join(result).strip() or None


# ---------------------------------------------------------------------------
# 2. HOMESTUCK / ALTERNIAN ALIEN ALPHABET
# ---------------------------------------------------------------------------
_ALIEN_DISTINCTIVE: frozenset = frozenset({
    "\u1491",    # ᔑ
    "\u0296",    # ʖ
    "\u14f5",    # ᓵ
    "\u21b8",    # ↸
    "\u14b7",    # ᒷ
    "\u2393",    # ⎓
    "\u22a3",    # ⊣
    "\u2351",    # ⍑
    "\u254e",    # ╎
    "\u2738",    # ✸
    "\ua58c",    # ꖌ
    "\ua58e",    # ꖎ
    "\u14b2",    # ᒲ
    "\U0001d479", # 𝙹
    "\u2307",    # ⌇
    "\u2237",    # ∷
    "\u14ed",    # ᓭ
    "\u2138",    # ℸ
    "\u234a",    # ⍊
    "\u2328",    # ⌨
    "\u028e",    # ʎ
    "\u01a8",    # ƨ
})

_ALIEN_MAP: dict[str, str] = {
    "\u1491":    "a",
    "\u0296":    "b",
    "\u14f5":    "c",
    "\u21b8":    "d",
    "\u14b7":    "e",
    "\u2393":    "f",
    "\u22a3":    "g",
    "\u2351":    "h",
    "\u254e":    "i",
    "\u2738":    "j",
    "\ua58c":    "k",
    "\ua58e":    "l",
    "\u14b2":    "m",
    "\u30ea":    "n",   # リ — only decoded in alien context
    "\U0001d479": "o",
    "\u03c1":    "p",   # ρ
    "\u2307":    "q",
    "\u2237":    "r",
    "\u14ed":    "s",
    "\u2138":    "t",
    "\u268d":    "u",
    "\u234a":    "v",
    "\u2234":    "w",   # ∴
    "\u2328":    "x",
    "\u028e":    "y",
    "\u01a8":    "z",
}

def _decode_alien(text: str) -> Optional[str]:
    if sum(1 for c in text if c in _ALIEN_DISTINCTIVE) < 2:
        return None
    clean = "".join(
        c for c in unicodedata.normalize("NFD", text)
        if unicodedata.category(c) != "Mn"
    )
    return "".join(_ALIEN_MAP.get(c, c) for c in clean).strip() or None


# ---------------------------------------------------------------------------
# 3. MORSE CODE
# ---------------------------------------------------------------------------
_MORSE_TO_CHAR: dict[str, str] = {
    ".-": "A",    "-...": "B",  "-.-.": "C",  "-..": "D",   ".": "E",
    "..-.": "F",  "--.": "G",   "....": "H",  "..": "I",    ".---": "J",
    "-.-": "K",   ".-..": "L",  "--": "M",    "-.": "N",    "---": "O",
    ".--.": "P",  "--.-": "Q",  ".-.": "R",   "...": "S",   "-": "T",
    "..-": "U",   "...-": "V",  ".--": "W",   "-..-": "X",  "-.--": "Y",
    "--..": "Z",
    "-----": "0", ".----": "1", "..---": "2", "...--": "3", "....-": "4",
    ".....": "5", "-....": "6", "--...": "7", "---..": "8", "----.": "9",
    "..--..": "?", "-.-.--": "!", ".-.-.-": ".", "--..--": ",",
    "---...": ":", "-.-.-.": ";", "-....-": "-", ".-..-.": '"',
    ".--.-.": "@",
}
_MORSE_PATTERN = re.compile(r"^[.\-\s/|]+$")

def _decode_morse(text: str) -> Optional[str]:
    stripped = text.strip()
    if not _MORSE_PATTERN.match(stripped):
        return None
    # Split into words by ' / ' or ' | ', letters by whitespace
    word_chunks = re.split(r"\s*/\s*|\s*\|\s*", stripped)
    decoded_words = []
    total, valid = 0, 0
    for chunk in word_chunks:
        letters = chunk.strip().split()
        word_chars = []
        for code in letters:
            total += 1
            ch = _MORSE_TO_CHAR.get(code)
            if ch:
                valid += 1
                word_chars.append(ch)
            else:
                word_chars.append("?")
        decoded_words.append("".join(word_chars))
    if total < 3 or valid / max(total, 1) < 0.7:
        return None
    return " ".join(decoded_words).strip() or None


# ---------------------------------------------------------------------------
# 4. BINARY ASCII
# ---------------------------------------------------------------------------
_BINARY_PATTERN = re.compile(r"^[01](?:[01 ]+[01])?$")

def _decode_binary(text: str) -> Optional[str]:
    stripped = text.strip()
    if not _BINARY_PATTERN.match(stripped):
        return None
    groups = stripped.split()
    if len(groups) < 3 or not all(len(g) == 8 for g in groups):
        return None
    try:
        decoded = "".join(chr(int(g, 2)) for g in groups)
    except ValueError:
        return None
    if not all(c.isprintable() or c in "\n\r\t" for c in decoded):
        return None
    return decoded or None


# ---------------------------------------------------------------------------
# 5. NATO PHONETIC ALPHABET
# ---------------------------------------------------------------------------
_NATO: dict[str, str] = {
    "alpha": "a", "bravo": "b", "charlie": "c", "delta": "d", "echo": "e",
    "foxtrot": "f", "golf": "g", "hotel": "h", "india": "i", "juliet": "j",
    "kilo": "k", "lima": "l", "mike": "m", "november": "n", "oscar": "o",
    "papa": "p", "quebec": "q", "romeo": "r", "sierra": "s", "tango": "t",
    "uniform": "u", "victor": "v", "whiskey": "w", "xray": "x", "x-ray": "x",
    "yankee": "y", "zulu": "z",
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
    "niner": "9",
}

def _decode_nato(text: str) -> Optional[str]:
    words = text.lower().split()
    if len(words) < 3:
        return None
    nato_hits = sum(1 for w in words if w in _NATO)
    if nato_hits < 3 or nato_hits / len(words) < 0.75:
        return None
    return "".join(_NATO.get(w.lower(), w + " ") for w in words).strip() or None


# ---------------------------------------------------------------------------
# 6. BASE64
# ---------------------------------------------------------------------------
_BASE64_PATTERN = re.compile(r"^[A-Za-z0-9+/]+=*$")

def _decode_base64(text: str) -> Optional[str]:
    stripped = text.strip()
    if not _BASE64_PATTERN.match(stripped):
        return None
    if len(stripped) < 8 or len(stripped) % 4 != 0:
        return None
    try:
        decoded = base64.b64decode(stripped).decode("utf-8")
    except Exception:
        return None
    if len(decoded) < 3 or not all(c.isprintable() or c in "\n\r\t" for c in decoded):
        return None
    return decoded


# ---------------------------------------------------------------------------
# 7. ZALGO TEXT  (excessive combining diacritics)
# ---------------------------------------------------------------------------
def _decode_zalgo(text: str) -> Optional[str]:
    combining = sum(1 for c in text if unicodedata.category(c) == "Mn")
    total = max(len(text), 1)
    if combining < 5 or combining / total < 0.30:
        return None
    normalized = unicodedata.normalize("NFD", text)
    cleaned = "".join(c for c in normalized if unicodedata.category(c) != "Mn").strip()
    return cleaned if len(cleaned) >= 2 else None


# ---------------------------------------------------------------------------
# 8. UPSIDE-DOWN / FLIPPED TEXT
# ---------------------------------------------------------------------------
_FLIP_TO_NORMAL: dict[str, str] = {
    # lowercase flipped → original
    "\u0250": "a",  # ɐ
    "q":      "b",
    "\u0254": "c",  # ɔ
    "p":      "d",
    "\u01dd": "e",  # ǝ
    "\u0279": "r",  # ɹ (used as flipped r, but also flipped a sometimes)
    "\u0283": "s",  # ʃ → l (some generators use this)
    "\u0259": "e",  # ə
    "\u0287": "t",  # ʇ
    "\u028c": "v",  # ʌ
    "\u028d": "w",  # ʍ
    "\u028e": "y",  # ʎ
    "\u0265": "h",  # ɥ
    "\u0254": "c",  # ɔ
    "\u025f": "j",  # ɟ
    "\u0183": "g",  # ƃ
    "\u026f": "m",  # ɯ
    "\u0279": "r",  # ɹ
    "\u1d09": "i",  # ᴉ
    "\u027e": "j",  # ɾ
    "\u029e": "k",  # ʞ
    # uppercase flipped → original
    "\u2200": "A",  # ∀
    "\u0186": "C",  # Ɔ
    "\u018e": "E",  # Ǝ
    "\u2132": "F",  # Ⅎ
    "\u2141": "G",  # ⅁
    "\u017f": "J",  # ſ
    "\u2142": "L",  # ⅂
    "\u1438": "L",  # ᐸ (used in some generators)
    "\u0500": "D",  # Ԁ
    "\u22a5": "T",  # ⊥
    "\u2229": "U",  # ∩ (cap)
    "\u039b": "V",  # Λ
    "\u2132": "F",  # Ⅎ
    "\u2144": "Y",  # ⅄
    # Punctuation
    "\u00bf": "?",  # ¿
    "\u00a1": "!",  # ¡
    "\u02d9": ".",  # ˙
}

_FLIP_CHARS = set(_FLIP_TO_NORMAL.keys())

def _decode_upside_down(text: str) -> Optional[str]:
    flip_count = sum(1 for c in text if c in _FLIP_CHARS)
    non_space = text.replace(" ", "")
    if flip_count < 3 or flip_count / max(len(non_space), 1) < 0.35:
        return None
    # Upside-down text is written reversed; decode by unflipping then reversing
    unflipped = "".join(_FLIP_TO_NORMAL.get(c, c) for c in text)
    reversed_version = unflipped[::-1]
    # Return whichever looks more like natural text (more common letters)
    _common = set("etaoinshrdlucmfwypvbgkjqxz ETAOINSHRDLUCMFWYPVBGKJQXZ")
    score_fwd = sum(1 for c in unflipped if c in _common)
    score_rev = sum(1 for c in reversed_version if c in _common)
    return (reversed_version if score_rev >= score_fwd else unflipped).strip() or None


# ---------------------------------------------------------------------------
# 9. LEET SPEAK  (1337 / h4x0r)
# ---------------------------------------------------------------------------
_LEET_MAP: dict[str, str] = {
    "4": "a", "@": "a", "8": "b", "3": "e", "6": "g",
    "9": "g", "1": "l", "!": "i", "0": "o", "5": "s",
    "$": "s", "7": "t", "+": "t", "2": "z",
}
_LEET_CHARS = set(_LEET_MAP.keys())

def _decode_leet(text: str) -> Optional[str]:
    alpha_and_leet = [c for c in text if c.isalpha() or c in _LEET_CHARS]
    leet_count = sum(1 for c in alpha_and_leet if c in _LEET_CHARS)
    if leet_count < 2 or leet_count / max(len(alpha_and_leet), 1) < 0.20:
        return None
    return "".join(_LEET_MAP.get(c, c) for c in text.lower()).strip() or None


# ---------------------------------------------------------------------------
# PUBLIC API
# ---------------------------------------------------------------------------
_DECODERS = [
    (_decode_braille,     "BRAILLE"),
    (_decode_alien,       "ALIEN"),
    (_decode_morse,       "MORSE"),
    (_decode_binary,      "BINARY"),
    (_decode_nato,        "NATO"),
    (_decode_base64,      "BASE64"),
    (_decode_zalgo,       "ZALGO"),
    (_decode_upside_down, "FLIPPED"),
    (_decode_leet,        "LEET"),
]


def decode_any(text: str) -> tuple[Optional[str], Optional[str]]:
    """
    Try every known cipher/encoding on *text*.
    Returns ``(decoded_text, encoding_name)`` or ``(None, None)`` if nothing matched.
    """
    for decoder, name in _DECODERS:
        result = decoder(text)
        if result is not None:
            return result, name
    return None, None


def has_cipher(text: str) -> bool:
    """Quick check: does *text* look like it contains any supported cipher?"""
    # Braille range
    if any("\u2800" <= c <= "\u28ff" for c in text):
        return True
    # Alien alphabet distinctive chars
    if sum(1 for c in text if c in _ALIEN_DISTINCTIVE) >= 2:
        return True
    # Morse-like
    if _MORSE_PATTERN.match(text.strip()) and len(text.strip()) > 4:
        return True
    # Binary
    if _BINARY_PATTERN.match(text.strip()) and len(text.strip().split()) >= 3:
        return True
    # Flip chars
    if sum(1 for c in text if c in _FLIP_CHARS) >= 3:
        return True
    # Zalgo
    if sum(1 for c in text if unicodedata.category(c) == "Mn") >= 5:
        return True
    return False
