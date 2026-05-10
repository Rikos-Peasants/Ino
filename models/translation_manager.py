"""Auto-translation helpers for Discord messages."""

from __future__ import annotations

import html
import hashlib
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import unicodedata

import aiohttp

from config import Config
from models.gemini_utils import extract_gemini_stream_text
from models.translation_hints import ALL_HINTS as NON_ENGLISH_WORD_HINTS
from models import cipher_decoder

try:
    from google import genai
    from google.genai import types as genai_types
    HAS_GENAI = True
except Exception:
    genai = None
    genai_types = None
    HAS_GENAI = False

logger = logging.getLogger(__name__)

DISCORD_TOKEN_RE = re.compile(
    r"https?://\S+|"
    r"<a?:[A-Za-z0-9_]+:[0-9]+>|"
    r"<@!?[0-9]+>|"
    r"<@&[0-9]+>|"
    r"<#[0-9]+>|"
    r":[A-Za-z0-9_+-]+:"
)
LETTER_RE = re.compile(r"[^\W\d_]", re.UNICODE)
# Matches actual non-Latin writing systems so Google Translate (not Gemini) handles them.
# Deliberately excludes accented Latin (é ñ ü etc.) — those CAN go to Gemini fallback.
NON_LATIN_RE = re.compile(
    r"[\u0370-\u03FF"    # Greek / Coptic
    r"\u0400-\u04FF"    # Cyrillic
    r"\u0530-\u058F"    # Armenian
    r"\u0590-\u05FF"    # Hebrew
    r"\u0600-\u06FF"    # Arabic
    r"\u0750-\u077F"    # Arabic Supplement
    r"\u0900-\u097F"    # Devanagari
    r"\u0980-\u09FF"    # Bengali
    r"\u0A00-\u0A7F"    # Gurmukhi
    r"\u0A80-\u0AFF"    # Gujarati
    r"\u0B00-\u0B7F"    # Oriya
    r"\u0B80-\u0BFF"    # Tamil (native)
    r"\u0C00-\u0C7F"    # Telugu
    r"\u0C80-\u0CFF"    # Kannada
    r"\u0D00-\u0D7F"    # Malayalam
    r"\u0D80-\u0DFF"    # Sinhala (native)
    r"\u0E00-\u0E7F"    # Thai
    r"\u0F00-\u0FFF"    # Tibetan
    r"\u1000-\u109F"    # Myanmar
    r"\u10A0-\u10FF"    # Georgian
    r"\u1100-\u11FF"    # Hangul Jamo
    r"\u3000-\u30FF"    # CJK Symbols + Hiragana/Katakana
    r"\u3400-\u4DBF"    # CJK Extension A
    r"\u4E00-\u9FFF"    # CJK Unified Ideographs
    r"\uAC00-\uD7A3"    # Hangul Syllables
    r"]"
)

# Cyrillic / Greek characters that are visual homoglyphs of Latin letters.
# Only applied when text is a *mix* of Latin and these scripts (likely stylized).
_HOMOGLYPH_MAP: dict[str, str] = {
    "\u0430": "a",  # а (Cyrillic)
    "\u0435": "e",  # е
    "\u0456": "i",  # і
    "\u043e": "o",  # о
    "\u0440": "p",  # р
    "\u0441": "c",  # с
    "\u0443": "y",  # у
    "\u0445": "x",  # х
    "\u0455": "s",  # ѕ
    "\u0458": "j",  # ј
    "\u03b1": "a",  # α (Greek)
    "\u03bf": "o",  # ο
    "\u03c1": "p",  # ρ
    "\u03c2": "c",  # ς
    "\u03f2": "c",  # ϲ
    "\u03bd": "v",  # ν
}


def _normalize_unicode(text: str) -> str:
    """NFKC-normalize fullwidth chars and remap Cyrillic/Greek homoglyphs in mixed-script text."""
    normalized = unicodedata.normalize("NFKC", text)
    has_latin = any("a" <= c.lower() <= "z" for c in normalized)
    has_confusable = any(c in _HOMOGLYPH_MAP for c in normalized)
    if has_latin and has_confusable:
        normalized = "".join(_HOMOGLYPH_MAP.get(c, c) for c in normalized)
    return normalized

EXPRESSIVE_ENGLISH_WORDS = frozenset({
    "no", "yes", "why", "stop", "wait", "oh", "ah", "aw", "ew", "ow",
    "wow", "go", "hey", "yo", "hi", "bye", "please", "help",
    "what", "how", "same", "true", "real", "nice",
    "cool", "good", "bad", "great", "damn", "dang", "bro",
    "yay", "nay", "ugh", "oof", "ow", "oi", "mhm",
})
INTERNET_SLANG_WORDS = frozenset({
    "lol", "lmao", "lmfao", "rofl", "roflmao",
    "xd", "omg", "omfg", "wtf", "wth",
    "ikr", "idk", "idc", "imo", "imho", "ngl", "tbh", "fyi",
    "brb", "afk", "gg", "ggg", "ff", "rip",
    "owo", "uwu", "smh", "bruh", "bruv",
    "ok", "okay", "k", "kk",
    "nah", "yep", "yup", "nope", "yikes",
    "hm", "hmm", "hmmm",
    "fr", "lowkey", "highkey", "bet", "cap", "nocap",
    "poggers", "pog", "copium", "based", "cringe",
    "ayo", "ayoo", "npc",
    # Common abbreviations that Google Translate falsely detects as foreign languages
    "wdym", "wym", "wyd", "wbu", "hbu", "wdyt", "wyt", "wdyg",
    "imo", "imho", "tbh", "ngl", "istg", "iirc", "afaik",
    "icymi", "fwiw", "tfw", "smh", "imo", "irl", "rn", "ig",
    "dm", "dms", "lmk", "hmu", "sup", "wb", "ty", "yw",
    "gl", "hf", "ez", "gg", "wp", "omw", "eta",
})
LAUGH_RE = re.compile(
    r"^(?:"
    r"l+o+l+s?|"          # lol, loool, lols
    r"lm+f?a+o+|"         # lmao, lmfao, lmaooo
    r"(?:ha){2,}h?|"      # haha, hahaha
    r"ha+h+a*|"           # haah, haaah
    r"(?:he){2,}h?|"      # hehe, hehehe
    r"(?:hi){2,}h?|"      # hihi
    r"ro+fl+(?:ma+o+)?|" # rofl, roflmao
    r"x+d+|"              # xd, xdd
    r"(?:ah)+a?|"         # aha, ahaha
    r"(?:eh)+e?"          # ehe
    r")$",
    re.IGNORECASE,
)


@dataclass
class TranslationResult:
    source_language: str
    translated_text: str
    provider: str = "google"


class TranslationManager:
    """Detect non-English messages and translate them to English."""

    def __init__(self, db=None):
        self.api_key = Config.GOOGLE_TRANSLATE_API_KEY
        self.detect_endpoint = "https://translation.googleapis.com/language/translate/v2/detect"
        self.translate_endpoint = "https://translation.googleapis.com/language/translate/v2"
        self.db = db
        self.approved_collection = None
        self.preference_collection = None
        self._approved_cache: dict[str, TranslationResult] = {}
        self._preference_cache: dict[tuple[int, int], bool] = {}
        self.gemini_api_key = Config.GEMINI_API_KEY
        self.gemini_client = None
        self.gemini_permission_denied = False
        if self.db is not None:
            try:
                self.approved_collection = self.db["approved_translations"]
                self.approved_collection.create_index("translation_key", unique=True)
                self.approved_collection.create_index([("approved_at", -1)])
            except Exception as e:
                logger.warning(f"Could not initialize approved translation collection: {e}")
                self.approved_collection = None
            try:
                self.preference_collection = self.db["translation_preferences"]
                self.preference_collection.create_index([("guild_id", 1), ("user_id", 1)], unique=True)
                self.preference_collection.create_index([("updated_at", -1)])
            except Exception as e:
                logger.warning(f"Could not initialize translation preference collection: {e}")
                self.preference_collection = None
        if Config.AUTO_TRANSLATE_ROMANIZED_ENABLED and self.gemini_api_key and HAS_GENAI:
            try:
                self.gemini_client = genai.Client(api_key=self.gemini_api_key)
            except Exception as e:
                logger.warning(f"Could not initialize Gemini romanized translation fallback: {e}")

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key or self.gemini_client)

    async def get_user_preference(self, user_id: int, guild_id: int) -> Optional[bool]:
        """Return True for opt-in, False for opt-out, or None when the user has not chosen."""
        cache_key = (int(guild_id), int(user_id))
        if cache_key in self._preference_cache:
            return self._preference_cache[cache_key]

        if self.preference_collection is None:
            return None

        try:
            doc = self.preference_collection.find_one({
                "guild_id": str(guild_id),
                "user_id": str(user_id),
            })
            if not doc:
                return None

            opted_in = bool(doc.get("opted_in"))
            self._preference_cache[cache_key] = opted_in
            return opted_in
        except Exception as e:
            logger.error(f"Error reading translation preference: {e}")
            return None

    async def set_user_preference(
        self,
        user_id: int,
        guild_id: int,
        opted_in: bool,
        user_name: str = "",
    ) -> bool:
        """Persist a user's translation-program choice."""
        cache_key = (int(guild_id), int(user_id))
        self._preference_cache[cache_key] = bool(opted_in)

        if self.preference_collection is None:
            return True

        try:
            self.preference_collection.update_one(
                {
                    "guild_id": str(guild_id),
                    "user_id": str(user_id),
                },
                {
                    "$set": {
                        "guild_id": str(guild_id),
                        "user_id": str(user_id),
                        "user_name": user_name,
                        "opted_in": bool(opted_in),
                        "updated_at": datetime.utcnow(),
                    }
                },
                upsert=True,
            )
            return True
        except Exception as e:
            logger.error(f"Error saving translation preference: {e}")
            return False

    def _is_internet_expression(self, text: str) -> bool:
        """Return True if the text is entirely internet slang/laughter that should never be translated."""
        words = re.findall(r"[A-Za-z]+", text)
        if not words:
            return False
        for w in words:
            lw = w.lower()
            if lw in INTERNET_SLANG_WORDS:
                continue
            if LAUGH_RE.match(lw):
                continue
            collapsed = re.sub(r"(.)\1+", r"\1", lw)
            if collapsed in EXPRESSIVE_ENGLISH_WORDS:
                continue
            return False
        return True

    def looks_translation_candidate(self, content: str) -> bool:
        """Local pre-check used before consent, so no provider sees data before opt-in."""
        detection_text = self._content_for_detection(content)
        letter_chars = LETTER_RE.findall(detection_text)
        has_non_ascii = any(ord(c) > 127 for c in letter_chars)
        if len(letter_chars) < (1 if has_non_ascii else 3):
            return False

        if self._is_internet_expression(detection_text):
            return False

        if cipher_decoder.has_cipher(detection_text):
            return True

        if any(char.isalpha() and ord(char) > 127 for char in detection_text):
            return True

        # Normalize fullwidth/homoglyph chars before word-hint matching
        norm_text = _normalize_unicode(detection_text)
        words = [word.casefold().strip("'") for word in re.findall(r"[A-Za-z']+", norm_text)]
        if not words:
            return False

        return bool(set(words) & NON_ENGLISH_WORD_HINTS)

    async def translate_to_english(self, content: str) -> Optional[TranslationResult]:
        """Return an English translation for non-English content, otherwise None."""
        if not self.is_configured:
            return None

        detection_text = self._content_for_detection(content)
        letter_chars = LETTER_RE.findall(detection_text)
        has_non_ascii = any(ord(c) > 127 for c in letter_chars)
        if len(letter_chars) < (1 if has_non_ascii else 3):
            return None

        if self._is_internet_expression(detection_text):
            return None

        decoded, encoding = cipher_decoder.decode_any(content)
        # Also try with normalized text in case ciphers embedded homoglyphs
        if decoded is None:
            norm_content = _normalize_unicode(content)
            if norm_content != content:
                decoded, encoding = cipher_decoder.decode_any(norm_content)
        if decoded is not None:
            detected = await self._detect_language(decoded) if self.api_key else None
            if not detected or detected.lower() == "en":
                return TranslationResult(
                    source_language=encoding,
                    translated_text=decoded,
                    provider="cipher",
                )
            protected, tokens = self._protect_discord_tokens(decoded)
            translated = await self._translate(protected, detected)
            translated = self._restore_discord_tokens(translated, tokens).strip()
            if translated:
                return TranslationResult(
                    source_language=f"{encoding}/{detected.upper()}",
                    translated_text=translated,
                    provider="cipher",
                )
            return None

        approved = await self.get_approved_translation(content)
        if approved:
            return approved

        # Normalize fullwidth / Cyrillic-homoglyph text before hitting the API
        api_text = _normalize_unicode(detection_text)
        detected_language = await self._detect_language(api_text) if self.api_key else None
        if not detected_language or detected_language.lower() == "en":
            return await self._translate_romanized_if_needed(content, detection_text)

        # Google Translate cannot translate romanized/Latin-script variants (e.g. ja-Latn, zh-Latn).
        # It identifies them correctly but just echoes the text back unchanged.
        # Route to Gemini which actually understands romanized content.
        if "-latn" in detected_language.lower():
            return await self._translate_romanized_if_needed(content, detection_text)

        # Translate normalized form so API isn't confused by homoglyphs / fullwidth chars
        translate_source = _normalize_unicode(content) if api_text != detection_text else content
        protected_content, tokens = self._protect_discord_tokens(translate_source)
        translated = await self._translate(protected_content, detected_language)
        translated = self._restore_discord_tokens(translated, tokens).strip()
        if not translated:
            return None

        return TranslationResult(
            source_language=detected_language.upper(),
            translated_text=translated,
            provider="google",
        )

    async def get_approved_translation(self, content: str) -> Optional[TranslationResult]:
        translation_key = self._translation_key(content)
        cached = self._approved_cache.get(translation_key)
        if cached:
            return cached

        if self.approved_collection is None:
            return None

        try:
            doc = self.approved_collection.find_one({"translation_key": translation_key})
            if not doc:
                return None

            result = TranslationResult(
                source_language=doc.get("source_language", "AUTO"),
                translated_text=doc.get("translated_text", ""),
                provider="approved",
            )
            if result.translated_text:
                self._approved_cache[translation_key] = result
                return result
        except Exception as e:
            logger.error(f"Error reading approved translation: {e}")

        return None

    async def save_approved_translation(
        self,
        original_content: str,
        source_language: str,
        translated_text: str,
        moderator_id: int,
        moderator_name: str,
        guild_id: int,
    ) -> bool:
        translation_key = self._translation_key(original_content)
        result = TranslationResult(
            source_language=source_language.upper(),
            translated_text=translated_text,
            provider="approved",
        )
        self._approved_cache[translation_key] = result

        if self.approved_collection is None:
            return True

        try:
            self.approved_collection.update_one(
                {"translation_key": translation_key},
                {
                    "$set": {
                        "translation_key": translation_key,
                        "normalized_original": self._normalize_for_key(original_content),
                        "original_content": original_content[:1000],
                        "source_language": source_language.upper(),
                        "translated_text": translated_text,
                        "moderator_id": str(moderator_id),
                        "moderator_name": moderator_name,
                        "guild_id": str(guild_id),
                        "approved_at": datetime.utcnow(),
                    }
                },
                upsert=True,
            )
            return True
        except Exception as e:
            logger.error(f"Error saving approved translation: {e}")
            return False

    async def retry_with_gemini(self, content: str, source_language: Optional[str] = None) -> Optional[TranslationResult]:
        if not self.gemini_client:
            return None

        protected_content, tokens = self._protect_discord_tokens(content)
        result = await self._ask_gemini_for_direct_translation(protected_content, source_language)
        if not result:
            return None

        translated = self._restore_discord_tokens(result.translated_text, tokens).strip()
        if not translated:
            return None

        return TranslationResult(
            source_language=result.source_language.upper(),
            translated_text=translated,
            provider="gemini_retry",
        )

    async def _detect_language(self, content: str) -> Optional[str]:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.detect_endpoint,
                    params={"key": self.api_key},
                    json={"q": content},
                    timeout=aiohttp.ClientTimeout(total=8),
                ) as response:
                    if response.status != 200:
                        logger.warning(
                            "Google Translate detect API error: %s - %s",
                            response.status,
                            await response.text(),
                        )
                        return None

                    data = await response.json()
                    detections = data.get("data", {}).get("detections", [])
                    if not detections or not detections[0]:
                        return None

                    detection = detections[0][0]
                    confidence = detection.get("confidence")
                    min_confidence = Config.AUTO_TRANSLATE_MIN_CONFIDENCE
                    if confidence is not None and confidence < min_confidence:
                        return None

                    return detection.get("language")
        except Exception as e:
            logger.error(f"Error detecting message language: {e}")
            return None

    async def _translate(self, content: str, source_language: str) -> str:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.translate_endpoint,
                    params={"key": self.api_key},
                    json={
                        "q": content,
                        "source": source_language,
                        "target": "en",
                        "format": "text",
                    },
                    timeout=aiohttp.ClientTimeout(total=8),
                ) as response:
                    if response.status != 200:
                        logger.warning(
                            "Google Translate API error: %s - %s",
                            response.status,
                            await response.text(),
                        )
                        return ""

                    data = await response.json()
                    translations = data.get("data", {}).get("translations", [])
                    if not translations:
                        return ""

                    return html.unescape(translations[0].get("translatedText", ""))
        except Exception as e:
            logger.error(f"Error translating message: {e}")
            return ""

    def _content_for_detection(self, content: str) -> str:
        return DISCORD_TOKEN_RE.sub(" ", content).strip()

    def _protect_discord_tokens(self, content: str) -> tuple[str, list[str]]:
        tokens: list[str] = []

        def replace(match: re.Match[str]) -> str:
            tokens.append(match.group(0))
            return f"XQZ{len(tokens) - 1}QZX"

        return DISCORD_TOKEN_RE.sub(replace, content), tokens

    def _restore_discord_tokens(self, content: str, tokens: list[str]) -> str:
        for index, token in enumerate(tokens):
            content = content.replace(f"XQZ{index}QZX", token)
        return content

    async def _translate_romanized_if_needed(self, content: str, detection_text: str) -> Optional[TranslationResult]:
        if not self._should_check_romanized(detection_text):
            return None

        protected_content, tokens = self._protect_discord_tokens(content)
        result = await self._ask_gemini_for_romanized_translation(protected_content)
        if not result:
            return None

        translated = self._restore_discord_tokens(result.translated_text, tokens).strip()
        if not translated:
            return None

        return TranslationResult(
            source_language=result.source_language.upper(),
            translated_text=translated,
            provider="gemini",
        )

    def _should_check_romanized(self, content: str) -> bool:
        if not Config.AUTO_TRANSLATE_ROMANIZED_ENABLED or not self.gemini_client:
            return False

        stripped = content.strip()
        if len(stripped) < Config.AUTO_TRANSLATE_ROMANIZED_MIN_CHARS:
            return False

        # Romanized text is latin-script. Native scripts are handled by Google Translate detection.
        if NON_LATIN_RE.search(stripped):
            return False

        words = re.findall(r"[A-Za-z']+", stripped)
        return len(words) >= 2

    async def _ask_gemini_for_romanized_translation(self, content: str) -> Optional[TranslationResult]:
        try:
            prompt = f"""Analyze this Discord message and determine if it is written in a non-English language.

MESSAGE:
{content}

Non-English includes ALL of the following:
- European Latin-script languages: French ("salut comment tu vas"), Spanish ("hola como estas"), Portuguese, Italian, German, Dutch, etc.
- Romanized/transliterated languages: Hindi/Hinglish ("namaste kaise ho"), Japanese romaji ("konnichiwa genki desu"), Arabic transliteration ("salam habibi"), Turkish, Tamil romanized ("vanakkam eppadi irukkeenga"), Sinhala romanized ("ayubowan kohomada"), Korean romanized, etc.
- Stylized / homoglyph text: messages using fullwidth characters (ｈｅｌｌｏ), Cyrillic-lookalike letters, or mixed scripts that represent a Latin-script language.
- Any other clearly non-English language written in Latin letters.

If the message is:
- Clearly English
- Mostly English with just 1-2 foreign words
- Only names, usernames, or short tags
- Too ambiguous to determine
Return: {{"translate": false}}

Otherwise, translate the full message to natural English and return:
{{"translate": true, "source_language": "FR", "translated_text": "Hello, how are you?"}}

Rules:
- Use ISO 639-1 uppercase codes: FR, ES, PT, IT, DE, NL, HI, JA, KO, AR, TR, etc.
- If the message mixes non-English and English (e.g. "lol c'est ouf", "maji yabai lol", "Lost in the hollows, unmei maware", "Zero modori mata saisei"), translate the non-English parts and keep any English parts unchanged.
- Preserve Discord placeholders like XQZ0QZX exactly — do not translate them.
- Do not translate URLs, mentions, custom emoji, or placeholder tokens.
- Do not guess — if genuinely unsure, return {{"translate": false}}."""

            contents = [
                genai_types.Content(
                    role="user",
                    parts=[genai_types.Part.from_text(text=prompt)],
                )
            ]
            generate_content_config = genai_types.GenerateContentConfig(
                temperature=0,
                response_mime_type="application/json",
            )

            response_text = extract_gemini_stream_text(self.gemini_client.models.generate_content_stream(
                model="gemini-flash-latest",
                contents=contents,
                config=generate_content_config,
            )).strip()
            if not response_text:
                logger.debug("Empty Gemini romanized translation streaming response")
                return None

            data = json.loads(response_text.replace("```json", "").replace("```", "").strip())
            if not data.get("translate"):
                return None

            source_language = str(data.get("source_language", "")).strip()
            translated_text = str(data.get("translated_text", "")).strip()
            if not source_language or source_language.upper() == "EN" or not translated_text:
                return None

            return TranslationResult(source_language=source_language, translated_text=translated_text)
        except Exception as e:
            error_text = str(e)
            if "403" in error_text or "PERMISSION_DENIED" in error_text.upper():
                self.gemini_permission_denied = True
                self.gemini_client = None
                logger.error(
                    "Gemini permission denied for romanized translation fallback. "
                    "Disabling that fallback for this process. Check GEMINI_API_KEY, "
                    "the enabled Generative Language API, and model access. Error: %s",
                    e,
                )
            else:
                logger.error(f"Error translating romanized message with Gemini: {e}")
            return None

    async def _ask_gemini_for_direct_translation(
        self,
        content: str,
        source_language: Optional[str] = None,
    ) -> Optional[TranslationResult]:
        try:
            source_hint = source_language or "auto-detect"
            prompt = f"""Translate this Discord message to natural English.

SOURCE LANGUAGE HINT: {source_hint}
MESSAGE:
{content}

Return only valid JSON:
{{"translate": true, "source_language": "FR", "translated_text": "Hello, how are you?"}}

Rules:
- If the message is already English, return {{"translate": false}}.
- Handle ALL non-English languages: French, Spanish, Portuguese, Italian, German, Dutch, Arabic, Hindi/Hinglish, Japanese romaji, Korean, Turkish, Tamil (TA), Sinhala (SI), and any other language.
- Use ISO 639-1 uppercase codes: FR, ES, PT, IT, DE, NL, AR, HI, JA, KO, TR, TA, SI, etc.
- Preserve Discord placeholders like XQZ0QZX exactly — do not translate them.
- Do not translate URLs, mentions, custom emoji, names, or placeholder tokens."""

            data = await self._ask_gemini_json(prompt)
            if not data or not data.get("translate"):
                return None

            source_language = str(data.get("source_language", "")).strip()
            translated_text = str(data.get("translated_text", "")).strip()
            if not source_language or source_language.upper() == "EN" or not translated_text:
                return None

            return TranslationResult(source_language=source_language, translated_text=translated_text)
        except Exception as e:
            logger.error(f"Error retrying translation with Gemini: {e}")
            return None

    async def _ask_gemini_json(self, prompt: str) -> Optional[dict]:
        if not self.gemini_client:
            return None

        try:
            contents = [
                genai_types.Content(
                    role="user",
                    parts=[genai_types.Part.from_text(text=prompt)],
                )
            ]
            generate_content_config = genai_types.GenerateContentConfig(
                temperature=0,
                response_mime_type="application/json",
            )

            response_text = extract_gemini_stream_text(self.gemini_client.models.generate_content_stream(
                model="gemini-flash-latest",
                contents=contents,
                config=generate_content_config,
            )).strip()
            if not response_text:
                logger.debug("Empty Gemini translation streaming response")
                return None

            return json.loads(response_text.replace("```json", "").replace("```", "").strip())
        except Exception as e:
            error_text = str(e)
            if "403" in error_text or "PERMISSION_DENIED" in error_text.upper():
                self.gemini_permission_denied = True
                self.gemini_client = None
                logger.error(
                    "Gemini permission denied for translation. Disabling Gemini translation for this process. "
                    "Check GEMINI_API_KEY, the enabled Generative Language API, and model access. Error: %s",
                    e,
                )
            else:
                logger.error(f"Error calling Gemini translation: {e}")
            return None

    def _normalize_for_key(self, content: str) -> str:
        normalized = self._content_for_detection(content).casefold()
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized

    def _translation_key(self, content: str) -> str:
        normalized = self._normalize_for_key(content)
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
