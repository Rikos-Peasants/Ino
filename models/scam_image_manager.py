import hashlib
import io
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from PIL import Image, UnidentifiedImageError
from pymongo import ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError, PyMongoError

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


@dataclass(frozen=True)
class ScamImageSignature:
    sha256: str
    dhash: str
    label: str
    bytes: int
    width: int
    height: int


@dataclass(frozen=True)
class ScamImageMatch:
    kind: str
    label: str
    detail: str
    signature_sha256: Optional[str] = None
    distance: Optional[int] = None


class ScamImageManager:
    """Mongo-backed scam image signature and detection manager."""

    def __init__(self, db):
        self.db = db
        self.signatures_collection = self.db["scam_image_signatures"]
        self.detections_collection = self.db["scam_image_detections"]
        self._create_indexes()

    def _create_indexes(self):
        """Create additive indexes for scam image collections."""
        try:
            self.signatures_collection.create_index([("sha256", ASCENDING)], unique=True)
            self.signatures_collection.create_index([("active", ASCENDING), ("created_at", DESCENDING)])
            self.signatures_collection.create_index([("dhash", ASCENDING)])
            self.signatures_collection.create_index([("label", ASCENDING)])

            self.detections_collection.create_index([("message_id", ASCENDING), ("attachment_name", ASCENDING)])
            self.detections_collection.create_index([("guild_id", ASCENDING), ("created_at", DESCENDING)])
            self.detections_collection.create_index([("match_kind", ASCENDING)])
            logger.info("Scam image indexes created successfully")
        except PyMongoError as e:
            logger.warning(f"Could not create scam image indexes: {e}")

    @staticmethod
    def is_supported_image(filename: str) -> bool:
        return Path(filename).suffix.lower() in IMAGE_EXTENSIONS

    @staticmethod
    def dhash(image: Image.Image, hash_size: int = 8) -> int:
        grayscale = image.convert("L").resize((hash_size + 1, hash_size), Image.Resampling.LANCZOS)
        pixels = list(grayscale.getdata())
        bits = []
        for y in range(hash_size):
            row = pixels[y * (hash_size + 1) : (y + 1) * (hash_size + 1)]
            bits.extend("1" if row[x] > row[x + 1] else "0" for x in range(hash_size))
        return int("".join(bits), 2)

    @staticmethod
    def hamming_distance(left_hex: str, right_hex: str) -> int:
        return (int(left_hex, 16) ^ int(right_hex, 16)).bit_count()

    def build_signature(self, body: bytes, label: str) -> ScamImageSignature:
        image = Image.open(io.BytesIO(body))
        image.load()
        dhash_value = self.dhash(image)
        return ScamImageSignature(
            sha256=hashlib.sha256(body).hexdigest(),
            dhash=f"{dhash_value:016x}",
            label=label,
            bytes=len(body),
            width=image.width,
            height=image.height,
        )

    def add_signature(
        self,
        signature: ScamImageSignature,
        *,
        source: str,
        added_by_id: Optional[int] = None,
        added_by_name: Optional[str] = None,
    ) -> tuple[bool, str]:
        now = datetime.utcnow()
        doc = {
            "sha256": signature.sha256,
            "dhash": signature.dhash,
            "label": signature.label,
            "bytes": signature.bytes,
            "width": signature.width,
            "height": signature.height,
            "source": source,
            "active": True,
            "added_by_id": str(added_by_id) if added_by_id else None,
            "added_by_name": added_by_name,
            "created_at": now,
            "updated_at": now,
        }
        try:
            self.signatures_collection.insert_one(doc)
            return True, "created"
        except DuplicateKeyError:
            self.signatures_collection.update_one(
                {"sha256": signature.sha256},
                {
                    "$set": {
                        "label": signature.label,
                        "dhash": signature.dhash,
                        "bytes": signature.bytes,
                        "width": signature.width,
                        "height": signature.height,
                        "source": source,
                        "active": True,
                        "updated_at": now,
                    },
                    "$setOnInsert": {"created_at": now},
                },
                upsert=True,
            )
            return False, "updated"

    def seed_default_signatures(self, seed_path: Optional[Path] = None) -> dict:
        """Import bundled default scam signatures idempotently."""
        seed_path = seed_path or Path(__file__).with_name("scam_image_seed_data.json")
        data = json.loads(seed_path.read_text(encoding="utf-8"))
        created = 0
        updated = 0

        for item in data:
            signature = ScamImageSignature(
                sha256=item["sha256"].lower(),
                dhash=item["dhash"].lower(),
                label=item["label"],
                bytes=int(item["bytes"]),
                width=int(item["width"]),
                height=int(item["height"]),
            )
            was_created, _ = self.add_signature(
                signature,
                source=item.get("source", str(seed_path)),
            )
            if was_created:
                created += 1
            else:
                updated += 1

        return {"created": created, "updated": updated, "total": len(data)}

    def find_match(self, filename: str, body: bytes, dhash_distance: int = 8) -> Optional[ScamImageMatch]:
        if not self.is_supported_image(filename):
            return None

        sha256 = hashlib.sha256(body).hexdigest()
        exact = self.signatures_collection.find_one({"sha256": sha256, "active": True})
        if exact:
            return ScamImageMatch(
                kind="sha256",
                label=exact.get("label", "known scam image"),
                detail=sha256,
                signature_sha256=sha256,
            )

        try:
            image = Image.open(io.BytesIO(body))
            image.load()
        except (UnidentifiedImageError, OSError):
            return None

        candidate = f"{self.dhash(image):016x}"
        cursor = self.signatures_collection.find(
            {"active": True, "dhash": {"$exists": True, "$ne": ""}},
            {"sha256": 1, "dhash": 1, "label": 1},
        )
        for signature in cursor:
            distance = self.hamming_distance(candidate, signature["dhash"])
            if distance <= dhash_distance:
                return ScamImageMatch(
                    kind="dhash",
                    label=signature.get("label", "visually similar scam image"),
                    detail=f"{candidate} distance={distance}",
                    signature_sha256=signature.get("sha256"),
                    distance=distance,
                )
        return None

    def record_detection(self, message, attachment, match: ScamImageMatch, *, deleted=False, delete_error=None):
        doc = {
            "guild_id": str(message.guild.id) if message.guild else None,
            "guild_name": message.guild.name if message.guild else None,
            "channel_id": str(message.channel.id),
            "channel_name": getattr(message.channel, "name", str(message.channel)),
            "message_id": str(message.id),
            "user_id": str(message.author.id),
            "user_name": str(message.author),
            "attachment_name": attachment.filename,
            "attachment_size": attachment.size,
            "match_kind": match.kind,
            "match_label": match.label,
            "match_detail": match.detail,
            "signature_sha256": match.signature_sha256,
            "deleted": deleted,
            "delete_error": delete_error,
            "created_at": datetime.utcnow(),
        }
        result = self.detections_collection.insert_one(doc)
        return result.inserted_id

    def update_detection_delete_result(self, detection_id, *, deleted: bool, delete_error: Optional[str]):
        self.detections_collection.update_one(
            {"_id": detection_id},
            {
                "$set": {
                    "deleted": deleted,
                    "delete_error": delete_error,
                    "updated_at": datetime.utcnow(),
                }
            },
        )

    def list_signatures(self, query: Optional[str] = None, active_only: bool = True, limit: int = 10):
        filters = {}
        if active_only:
            filters["active"] = True
        if query:
            filters["$or"] = [
                {"label": {"$regex": query, "$options": "i"}},
                {"sha256": {"$regex": query, "$options": "i"}},
            ]
        return list(self.signatures_collection.find(filters).sort("created_at", DESCENDING).limit(limit))

    def set_signature_active(self, sha256_prefix: str, active: bool) -> tuple[bool, str]:
        matches = list(self.signatures_collection.find({"sha256": {"$regex": f"^{sha256_prefix.lower()}"}}))
        if len(matches) == 0:
            return False, "No signature matched that prefix."
        if len(matches) > 1:
            return False, f"That prefix matched {len(matches)} signatures. Use more hash characters."

        self.signatures_collection.update_one(
            {"_id": matches[0]["_id"]},
            {"$set": {"active": active, "updated_at": datetime.utcnow()}},
        )
        return True, "Signature enabled." if active else "Signature disabled."

    def recent_detections(self, limit: int = 5):
        return list(self.detections_collection.find({}).sort("created_at", DESCENDING).limit(limit))

    def counts(self) -> dict:
        total = self.signatures_collection.count_documents({})
        active = self.signatures_collection.count_documents({"active": True})
        detections = self.detections_collection.count_documents({})
        return {"total": total, "active": active, "detections": detections}
