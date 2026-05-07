import io
from pathlib import Path
import sys
from datetime import datetime, timedelta

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from models.scam_image_manager import ScamImageManager


class FakeInsertResult:
    def __init__(self, inserted_id):
        self.inserted_id = inserted_id


class FakeUpdateResult:
    def __init__(self, modified_count=1, upserted_id=None):
        self.modified_count = modified_count
        self.upserted_id = upserted_id


class FakeCursor:
    def __init__(self, docs):
        self.docs = list(docs)

    def sort(self, *args, **kwargs):
        return self

    def limit(self, limit):
        self.docs = self.docs[:limit]
        return self

    def __iter__(self):
        return iter(self.docs)


class FakeCollection:
    def __init__(self):
        self.docs = []
        self.indexes = []

    def create_index(self, *args, **kwargs):
        self.indexes.append((args, kwargs))

    def insert_one(self, doc):
        if "sha256" in doc:
            for existing in self.docs:
                if existing.get("sha256") == doc["sha256"]:
                    from pymongo.errors import DuplicateKeyError

                    raise DuplicateKeyError("duplicate sha256")
        if "cooldown_key" in doc:
            for existing in self.docs:
                if existing.get("cooldown_key") == doc["cooldown_key"]:
                    from pymongo.errors import DuplicateKeyError

                    raise DuplicateKeyError("duplicate cooldown_key")
        stored = dict(doc)
        stored["_id"] = len(self.docs) + 1
        self.docs.append(stored)
        return FakeInsertResult(stored["_id"])

    def update_one(self, query, update, upsert=False):
        for doc in self.docs:
            if self._matches(doc, query):
                doc.update(update.get("$set", {}))
                return FakeUpdateResult()
        if upsert:
            doc = dict(query)
            doc.update(update.get("$setOnInsert", {}))
            doc.update(update.get("$set", {}))
            result = self.insert_one(doc)
            return FakeUpdateResult(0, result.inserted_id)
        return FakeUpdateResult(0)

    def find_one_and_update(self, query, update, upsert=False, return_document=None):
        for doc in self.docs:
            if self._matches(doc, query):
                doc.update(update.get("$set", {}))
                return dict(doc)
        if upsert:
            doc = {key: value for key, value in query.items() if not key.startswith("$")}
            doc.update(update.get("$setOnInsert", {}))
            doc.update(update.get("$set", {}))
            self.insert_one(doc)
            return dict(self.docs[-1])
        return None

    def delete_one(self, query):
        for index, doc in enumerate(self.docs):
            if self._matches(doc, query):
                del self.docs[index]
                return FakeUpdateResult(1)
        return FakeUpdateResult(0)

    def find_one(self, query, projection=None):
        for doc in self.docs:
            if self._matches(doc, query):
                return dict(doc)
        return None

    def find(self, query=None, projection=None):
        query = query or {}
        return FakeCursor([dict(doc) for doc in self.docs if self._matches(doc, query)])

    def count_documents(self, query):
        return len([doc for doc in self.docs if self._matches(doc, query)])

    def _matches(self, doc, query):
        for key, expected in query.items():
            if key == "$or":
                if not any(self._matches(doc, item) for item in expected):
                    return False
                continue
            actual = doc.get(key)
            if isinstance(expected, dict):
                if "$exists" in expected and (key in doc) != expected["$exists"]:
                    return False
                if "$ne" in expected and actual == expected["$ne"]:
                    return False
                if "$in" in expected and actual not in expected["$in"]:
                    return False
                if "$gte" in expected and actual < expected["$gte"]:
                    return False
                if "$lte" in expected and actual > expected["$lte"]:
                    return False
                if "$gt" in expected and actual <= expected["$gt"]:
                    return False
                if "$regex" in expected:
                    import re

                    flags = re.I if expected.get("$options") == "i" else 0
                    if not re.search(expected["$regex"], str(actual or ""), flags):
                        return False
            elif actual != expected:
                return False
        return True


class FakeDb:
    def __init__(self):
        self.collections = {}

    def __getitem__(self, name):
        self.collections.setdefault(name, FakeCollection())
        return self.collections[name]


def main():
    manager = ScamImageManager(FakeDb())
    sample_name = "sample.jpeg"
    buf = io.BytesIO()
    Image.new("RGB", (32, 32), "white").save(buf, format="JPEG")
    body = buf.getvalue()

    signature = manager.build_signature(body, "fake neobox bonus page")
    created, action = manager.add_signature(signature, source=sample_name, added_by_id=1, added_by_name="tester")
    assert created is True
    assert action == "created"

    match = manager.find_match(sample_name, body)
    assert match is not None
    assert match.kind == "sha256"
    assert match.label == "fake neobox bonus page"

    rows = manager.list_signatures()
    assert len(rows) == 1
    assert rows[0]["sha256"] == signature.sha256

    counts = manager.counts()
    assert counts["total"] == 1
    assert counts["active"] == 1

    class FakeGuild:
        id = 10
        name = "Guild"

    class FakeChannel:
        id = 20
        name = "general"

        def __str__(self):
            return self.name

    class FakeAuthor:
        id = 30

        def __str__(self):
            return "poster"

    class FakeMessage:
        guild = FakeGuild()
        channel = FakeChannel()
        author = FakeAuthor()
        id = 40

    class FakeAttachment:
        filename = sample_name
        size = len(body)

    detection_id = manager.record_detection(FakeMessage(), FakeAttachment(), match)
    manager.update_detection_delete_result(detection_id, deleted=True, delete_error=None)
    recent = manager.recent_user_channel_detections("10", "30", datetime.utcnow() + timedelta(seconds=1))
    assert recent == []
    recent = manager.recent_user_channel_detections("10", "30", datetime.min)
    assert len(recent) == 1

    manager.record_detection(FakeMessage(), FakeAttachment(), match, burst_eligible=False)
    recent = manager.recent_user_channel_detections("10", "30", datetime.min)
    assert len(recent) == 1

    manager.alerts_collection.insert_one({
        "cooldown_key": "10:31",
        "guild_id": "10",
        "user_id": "31",
        "cooldown_until": datetime.utcnow() + timedelta(minutes=5),
        "status": "sent",
    })
    legacy_cooldown_reservation = manager.reserve_cross_channel_alert(
        guild_id="10",
        user_id="31",
        user_name="poster",
        channel_ids=["20", "21", "22"],
        message_ids=["40"],
        threshold=3,
        window_seconds=15,
        cooldown_minutes=10,
    )
    assert legacy_cooldown_reservation is None

    reservation = manager.reserve_cross_channel_alert(
        guild_id="10",
        user_id="30",
        user_name="poster",
        channel_ids=["20", "21", "22"],
        message_ids=["40"],
        threshold=3,
        window_seconds=15,
        cooldown_minutes=10,
    )
    assert reservation
    duplicate_reservation = manager.reserve_cross_channel_alert(
        guild_id="10",
        user_id="30",
        user_name="poster",
        channel_ids=["20", "21", "22"],
        message_ids=["40"],
        threshold=3,
        window_seconds=15,
        cooldown_minutes=10,
    )
    assert duplicate_reservation is None
    other_kind_reservation = manager.reserve_cross_channel_alert(
        guild_id="10",
        user_id="30",
        user_name="poster",
        channel_ids=["20", "21", "22"],
        message_ids=["40"],
        threshold=3,
        window_seconds=15,
        cooldown_minutes=10,
        alert_kind="repeated_image_burst",
    )
    assert other_kind_reservation
    other_alert = next(
        doc for doc in manager.alerts_collection.docs
        if doc.get("reservation_token") == other_kind_reservation
    )
    manager.mark_cross_channel_alert_sent("bad-guild", "30", other_kind_reservation, alert_kind="repeated_image_burst")
    assert other_alert["status"] == "pending"
    manager.mark_cross_channel_alert_sent("10", "30", other_kind_reservation, alert_kind="repeated_image_burst")
    assert other_alert["status"] == "sent"
    manager.mark_cross_channel_alert_sent("10", "30", reservation)
    manager.release_cross_channel_alert_reservation("10", "30", reservation)
    assert len(manager.alerts_collection.docs) == 3

    ok, message = manager.set_signature_active(signature.sha256[:12], False)
    assert ok is True
    assert "disabled" in message
    assert manager.find_match(sample_name, body) is None

    ok, message = manager.set_signature_active("not-regex.*", True)
    assert ok is False
    assert "hexadecimal" in message

    seeded = manager.seed_default_signatures()
    assert seeded["total"] == 3
    assert seeded["created"] >= 2

    seeded_again = manager.seed_default_signatures()
    assert seeded_again["total"] == 3
    assert seeded_again["created"] == 0

    print("scam image manager smoke test passed")


if __name__ == "__main__":
    main()
