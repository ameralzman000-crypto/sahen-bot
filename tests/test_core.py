import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import config
import database as db
from utils import (
    build_caption,
    build_text,
    can_reveal_identity,
    display_name,
    format_identity,
    is_admin,
    is_staff,
    validate_alias,
    validate_real_name,
)


def setup_module(module):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    config.DB_PATH = path
    db.init_db()
    db.ensure_admin(config.ADMIN_ID)
    module.DB_PATH = path


def teardown_module(module):
    try:
        os.remove(module.DB_PATH)
    except OSError:
        pass


def test_validate_real_name():
    assert validate_real_name("أحمد محمد") == "أحمد محمد"
    assert validate_real_name("  A  B  ") == "A B"
    assert validate_real_name("a") is None
    assert validate_real_name("name<script>") is None


def test_validate_alias_reserved():
    assert validate_alias("الذئب") == "الذئب"
    assert validate_alias("المدير") is None
    assert validate_alias("مشرف 2") is None
    assert validate_alias("admin") is None
    assert validate_alias("*سري") is None
    assert validate_alias("x") is None


def test_display_names():
    admin = {"role": "admin", "alias": "x"}
    mod = {"role": "moderator", "moderator_number": 3, "alias": "y"}
    member = {"role": "member", "alias": "الذئب"}
    assert display_name(admin) == "المدير"
    assert display_name(mod) == "مشرف 3"
    assert display_name(member) == "الذئب"


def test_reveal_permissions():
    admin = {"role": "admin", "status": "approved", "can_reveal": True}
    mod_ok = {"role": "moderator", "status": "approved", "can_reveal": True}
    mod_no = {"role": "moderator", "status": "approved", "can_reveal": False}
    member = {"role": "member", "status": "approved", "can_reveal": True}
    pending = {"role": "moderator", "status": "pending", "can_reveal": True}
    assert can_reveal_identity(admin) is True
    assert can_reveal_identity(mod_ok) is True
    assert can_reveal_identity(mod_no) is False
    assert can_reveal_identity(member) is False
    assert can_reveal_identity(pending) is False
    assert can_reveal_identity(None) is False


def test_staff_helpers():
    admin = {"role": "admin", "status": "approved"}
    mod = {"role": "moderator", "status": "approved"}
    member = {"role": "member", "status": "approved"}
    assert is_admin(admin, config.ADMIN_ID, config.ADMIN_ID)
    assert is_admin(None, config.ADMIN_ID, config.ADMIN_ID)
    assert not is_admin(member, config.ADMIN_ID, 99)
    assert is_staff(mod, config.ADMIN_ID, 5)
    assert not is_staff(member, config.ADMIN_ID, 5)


def test_admin_seeded():
    user = db.get_user(config.ADMIN_ID)
    assert user is not None
    assert user["role"] == "admin"
    assert user["status"] == "approved"
    assert user["can_reveal"] is True


def test_registration_flow():
    rec = db.upsert_registration(1001, "علي حسن", "الصقر", "ali")
    assert rec["status"] == "pending"
    assert rec["alias"] == "الصقر"
    assert db.alias_taken("الصقر")
    assert db.alias_taken("الصقر", exclude_user_id=1001) is False
    approved = db.set_status(1001, "approved")
    assert approved["status"] == "approved"
    db.set_status(1001, "rejected")
    again = db.upsert_registration(1001, "علي حسن", "الصقر2", "ali")
    assert again["status"] == "pending"


def test_moderator_and_reveal_flag():
    db.upsert_registration(2002, "سارة", "القمر", None)
    db.set_status(2002, "approved")
    n = db.next_moderator_number()
    mod = db.set_role(2002, "moderator", moderator_number=n, can_reveal=0)
    assert mod["role"] == "moderator"
    assert can_reveal_identity(mod) is False
    enabled = db.set_can_reveal(2002, True)
    assert can_reveal_identity(enabled) is True
    db.set_role(2002, "member", moderator_number=None, can_reveal=0)
    member = db.get_user(2002)
    assert member["role"] == "member"
    assert can_reveal_identity(member) is False


def test_message_map():
    db.save_message(-100, 11, 22, 1001)
    by_rel = db.get_by_relayed(-100, 22)
    by_orig = db.get_by_original(-100, 11)
    assert by_rel["sender_id"] == 1001
    assert by_orig["relayed_id"] == 22


def test_identity_format_hides_nothing_from_authorized_copy():
    user = {
        "user_id": 9,
        "real_name": "خالد",
        "alias": "الظلال",
        "username": "khaled",
        "role": "member",
        "status": "approved",
    }
    text = format_identity(user, 9)
    assert "خالد" in text
    assert "الظلال" in text
    assert "9" in text
    unknown = format_identity(None, 77)
    assert "غير مسجل" in unknown
    assert "77" in unknown


def test_build_text_and_caption():
    t = build_text("الذئب", "مرحبا")
    assert t.startswith("✦ الذئب")
    assert "مرحبا" in t
    c = build_caption("الذئب", "صورة")
    assert "الذئب" in c
    assert "صورة" in c
    empty = build_caption("الذئب", None)
    assert empty.startswith("✦ الذئب")


def test_stats_and_settings():
    data = db.stats()
    assert data["total"] >= 1
    db.set_group_chat_id(-999)
    assert db.get_group_chat_id() == -999
    db.set_bound_chat(-888, "channel")
    assert db.get_group_chat_id() == -888
    assert db.get_bound_chat_type() == "channel"
    assert db.is_channel_bound() is True
    db.set_bound_chat(-777, "supergroup")
    assert db.is_channel_bound() is False


def test_direct_write_flag():
    rec = db.upsert_registration(6060, "عضو", "النمر", None)
    db.set_status(6060, "approved")
    assert rec.get("direct_write") is False
    assert db.allows_direct_write(6060) is False
    db.set_direct_write(6060, True)
    assert db.allows_direct_write(6060) is True
    db.set_direct_write(6060, False)
    assert db.allows_direct_write(6060) is False


def test_default_and_custom_rules():
    text = db.get_rules()
    assert "قوانين مجموعة عين الشاهين" in text
    assert "كشف الهوية" in text
    db.set_rules("قانون تجريبي")
    assert db.get_rules() == "قانون تجريبي"


def test_pause_setting():
    assert db.is_paused() is False
    db.set_paused(True)
    assert db.is_paused() is True
    db.set_paused(False)
    assert db.is_paused() is False


def test_clear_message_map():
    db.set_group_chat_id(-70)
    db.save_message(-70, 11, 22, 1001)
    db.save_message(-71, 12, 23, 1001)
    assert db.list_message_ids(-70)
    removed = db.clear_message_map(-70)
    assert removed >= 1
    assert db.get_by_relayed(-70, 22) is None
    assert db.get_by_relayed(-71, 23) is not None


def test_reset_all_data_keeps_admin_only():
    db.upsert_registration(8888, "عضو", "البرق", None)
    db.set_status(8888, "approved")
    db.save_message(-50, 1, 2, 8888)
    db.set_group_chat_id(-50)
    db.reset_all_data(config.ADMIN_ID)
    assert db.get_user(8888) is None
    assert db.get_by_relayed(-50, 2) is None
    assert db.get_group_chat_id() is None
    admin = db.get_user(config.ADMIN_ID)
    assert admin is not None
    assert admin["role"] == "admin"
    assert admin["status"] == "approved"
