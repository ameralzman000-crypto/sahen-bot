import os
import tempfile
import unittest

import config
import database as db


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original = config.DB_PATH
        config.DB_PATH = os.path.join(self.tmp.name, "test.db")
        db.init_db()
        db.ensure_admin(config.ADMIN_ID)

    def tearDown(self):
        config.DB_PATH = self.original
        self.tmp.cleanup()

    def test_user_insert_and_status(self):
        user = db.upsert_registration(123, "Test User", "الذئب", "tester")
        self.assertEqual(user["status"], "pending")
        db.set_status(123, "approved")
        self.assertEqual(db.get_user(123)["status"], "approved")

    def test_counts(self):
        stats = db.stats()
        self.assertGreaterEqual(stats["total"], 1)
        self.assertEqual(stats["pending"], 0)

    def test_mute_and_settings(self):
        db.upsert_registration(55, "User", "اسم", None)
        db.set_mute(55, 4102444800, "test")
        self.assertTrue(db.is_muted(55))
        db.clear_mute(55)
        self.assertFalse(db.is_muted(55))
        db.set_bound_chat(-1001, "supergroup")
        self.assertEqual(db.get_group_chat_id(), -1001)

    def test_set_alias_and_delete_user(self):
        db.upsert_registration(77, "User", "الذئب", None)
        updated = db.set_alias(77, "النسر")
        self.assertEqual(updated["alias"], "النسر")
        self.assertTrue(db.delete_user(77))
        self.assertIsNone(db.get_user(77))
        self.assertFalse(db.delete_user(config.ADMIN_ID))
        self.assertIsNotNone(db.get_user(config.ADMIN_ID))


if __name__ == "__main__":
    unittest.main()
