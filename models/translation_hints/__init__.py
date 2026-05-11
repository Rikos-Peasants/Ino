from models.translation_hints.ja import JA_HINTS
from models.translation_hints.fr import FR_HINTS
from models.translation_hints.es import ES_HINTS
from models.translation_hints.pt import PT_HINTS
from models.translation_hints.it import IT_HINTS
from models.translation_hints.de import DE_HINTS
from models.translation_hints.nl import NL_HINTS
from models.translation_hints.ko import KO_HINTS
from models.translation_hints.hi import HI_HINTS
from models.translation_hints.ar import AR_HINTS
from models.translation_hints.tr import TR_HINTS
from models.translation_hints.ta import TA_HINTS
from models.translation_hints.si import SI_HINTS
from models.translation_hints.ru import RU_HINTS

ALL_HINTS: frozenset = (
    JA_HINTS | FR_HINTS | ES_HINTS | PT_HINTS | IT_HINTS
    | DE_HINTS | NL_HINTS | KO_HINTS | HI_HINTS | AR_HINTS | TR_HINTS
    | TA_HINTS | SI_HINTS | RU_HINTS
)
