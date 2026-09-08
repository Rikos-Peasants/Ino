"""Tests for per-user DM notification preferences.

The important properties are the fail-open ones: a missing or broken store must
never silence a notification, and the locked moderation/safety categories must
stay on no matter what is written to the database.
"""

import asyncio
import unittest

from models.notification_preferences import (
    CATEGORIES,
    CATEGORIES_BY_KEY,
    OPTIONAL_CATEGORIES,
    NotificationPreferences,
    should_dm,
)


def run(coro):
    return asyncio.run(coro)


class FakeCollection:
    """Just enough pymongo to exercise the manager."""

    def __init__(self):
        self.docs: dict[int, dict] = {}
        self.fail = False

    def create_index(self, *args, **kwargs):
        pass

    def find_one(self, query, projection=None):
        if self.fail:
            raise RuntimeError("mongo down")
        return self.docs.get(query["user_id"])

    def update_one(self, query, update, upsert=False):
        if self.fail:
            raise RuntimeError("mongo down")
        doc = self.docs.setdefault(query["user_id"], {"user_id": query["user_id"]})
        for dotted, value in update.get("$set", {}).items():
            if dotted.startswith("categories."):
                doc.setdefault("categories", {})[dotted.split(".", 1)[1]] = value

    def delete_one(self, query):
        if self.fail:
            raise RuntimeError("mongo down")
        self.docs.pop(query["user_id"], None)


class FakeDB(dict):
    def __getitem__(self, name):
        return self.setdefault(name, FakeCollection())


def make_prefs():
    db = FakeDB()
    prefs = NotificationPreferences(db)
    return prefs, prefs.collection


class CategoryDefinitionTests(unittest.TestCase):
    def test_keys_are_unique(self):
        keys = [c.key for c in CATEGORIES]
        self.assertEqual(len(keys), len(set(keys)))

    def test_moderation_and_safety_are_locked(self):
        self.assertFalse(CATEGORIES_BY_KEY["moderation"].optional)
        self.assertFalse(CATEGORIES_BY_KEY["safety"].optional)

    def test_optional_set_fits_one_select_menu(self):
        # Discord caps a select at 25 options; going over would silently break
        # the /notifications panel rather than fail loudly.
        self.assertLessEqual(len(OPTIONAL_CATEGORIES), 25)

    def test_descriptions_fit_select_option_limit(self):
        for category in CATEGORIES:
            with self.subTest(key=category.key):
                self.assertLessEqual(len(category.description), 100)


class DefaultsTests(unittest.TestCase):
    def test_everything_on_before_any_choice(self):
        prefs, _ = make_prefs()
        states = run(prefs.get_all(1))
        self.assertTrue(all(states.values()))

    def test_unknown_category_is_delivered(self):
        prefs, _ = make_prefs()
        self.assertTrue(run(prefs.is_enabled(1, "not_a_real_category")))


class ToggleTests(unittest.TestCase):
    def test_disabling_one_category_leaves_others_alone(self):
        prefs, _ = make_prefs()
        run(prefs.set(7, "quests", False))

        self.assertFalse(run(prefs.is_enabled(7, "quests")))
        self.assertTrue(run(prefs.is_enabled(7, "achievements")))

    def test_toggle_survives_a_cold_cache(self):
        prefs, collection = make_prefs()
        run(prefs.set(7, "bookmarks", False))

        fresh = NotificationPreferences(None)
        fresh.collection = collection
        self.assertFalse(run(fresh.is_enabled(7, "bookmarks")))

    def test_set_many_applies_every_optional_key(self):
        prefs, _ = make_prefs()
        run(prefs.set_many(9, {c.key: False for c in OPTIONAL_CATEGORIES}))

        states = run(prefs.get_all(9))
        for category in OPTIONAL_CATEGORIES:
            with self.subTest(key=category.key):
                self.assertFalse(states[category.key])

    def test_reset_restores_defaults(self):
        prefs, _ = make_prefs()
        run(prefs.set(3, "quests", False))
        run(prefs.reset(3))

        self.assertTrue(run(prefs.is_enabled(3, "quests")))


class LockedCategoryTests(unittest.TestCase):
    def test_cannot_be_turned_off_through_the_api(self):
        prefs, _ = make_prefs()
        run(prefs.set(5, "moderation", False))
        self.assertTrue(run(prefs.is_enabled(5, "moderation")))

    def test_stays_on_even_if_the_database_says_otherwise(self):
        prefs, collection = make_prefs()
        collection.docs[5] = {"user_id": 5, "categories": {"safety": False}}
        self.assertTrue(run(prefs.is_enabled(5, "safety")))
        self.assertTrue(run(prefs.get_all(5))["safety"])

    def test_a_mixed_write_still_applies_the_optional_half(self):
        prefs, _ = make_prefs()
        self.assertTrue(run(prefs.set_many(5, {"moderation": False, "quests": False})))

        self.assertTrue(run(prefs.is_enabled(5, "moderation")))
        self.assertFalse(run(prefs.is_enabled(5, "quests")))


class FailOpenTests(unittest.TestCase):
    def test_no_database_delivers_everything(self):
        prefs = NotificationPreferences(None)
        self.assertFalse(prefs.is_configured)
        self.assertTrue(run(prefs.is_enabled(1, "quests")))

    def test_no_database_reports_a_failed_write(self):
        prefs = NotificationPreferences(None)
        self.assertFalse(run(prefs.set(1, "quests", False)))

    def test_read_failure_delivers_and_does_not_poison_the_cache(self):
        prefs, collection = make_prefs()
        run(prefs.set(2, "quests", False))
        prefs._cache.clear()

        collection.fail = True
        self.assertTrue(run(prefs.is_enabled(2, "quests")))

        collection.fail = False
        self.assertFalse(run(prefs.is_enabled(2, "quests")))

    def test_write_failure_is_reported(self):
        prefs, collection = make_prefs()
        collection.fail = True
        self.assertFalse(run(prefs.set(2, "quests", False)))


class ShouldDmTests(unittest.TestCase):
    class Bot:
        def __init__(self, prefs=None):
            self.notification_preferences = prefs

    def test_missing_manager_delivers(self):
        self.assertTrue(run(should_dm(self.Bot(), 1, "quests")))

    def test_honours_a_real_preference(self):
        prefs, _ = make_prefs()
        run(prefs.set(1, "quests", False))
        self.assertFalse(run(should_dm(self.Bot(prefs), 1, "quests")))

    def test_raising_manager_delivers(self):
        class Boom:
            async def is_enabled(self, *_):
                raise RuntimeError("nope")

        self.assertTrue(run(should_dm(self.Bot(Boom()), 1, "quests")))


if __name__ == "__main__":
    unittest.main()
