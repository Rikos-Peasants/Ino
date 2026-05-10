"""Compatibility shim — functionality moved to models.cipher_decoder."""
from models.cipher_decoder import _decode_alien as _decode_alien, _ALIEN_DISTINCTIVE as ALIEN_DISTINCTIVE  # noqa: F401

def detect(text: str) -> bool:
    return sum(1 for c in text if c in ALIEN_DISTINCTIVE) >= 2

def decode(text: str):
    return _decode_alien(text)
