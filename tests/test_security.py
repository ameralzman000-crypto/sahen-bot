import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from security import (
    extract_relay_alias,
    format_duration,
    parse_moderation_command,
    parse_mute_duration,
    parse_power_command,
    redact_sensitive,
    scan_message,
)


MEMBERS = [
    {
        "user_id": 1,
        "real_name": "أحمد محمد",
        "alias": "الذئب",
        "status": "approved",
        "role": "member",
    },
    {
        "user_id": 2,
        "real_name": "سارة علي",
        "alias": "القمر",
        "status": "approved",
        "role": "member",
    },
    {
        "user_id": 3,
        "real_name": "خالد حسن",
        "alias": "الصقر",
        "status": "approved",
        "role": "member",
    },
]


def _sender(uid=3):
    return next(m for m in MEMBERS if m["user_id"] == uid)


def test_probe_questions_are_blocked():
    for text in (
        "مين أنت",
        "مين اللي عم يحكي",
        "مين صاحب الرسالة",
        "شو اسمك الحقيقي",
        "who are you",
        "عرف حالك",
    ):
        hit = scan_message(text, _sender(), MEMBERS)
        assert hit is not None, text
        assert hit.kind == "probe"


def test_linking_alias_to_real_name():
    hit = scan_message("الذئب هو أحمد محمد", _sender(), MEMBERS)
    assert hit is not None
    assert hit.kind == "link"
    assert "******" in hit.redacted


def test_reply_with_real_name_is_link():
    hit = scan_message("أحمد محمد", _sender(), MEMBERS, reply_to_user_id=1)
    assert hit is not None
    assert hit.kind == "link"


def test_outside_names_are_allowed():
    hit = scan_message("شاهدت فيلم أحمد زكي أمس", _sender(), MEMBERS)
    assert hit is None
    hit = scan_message("كلمت محمد في العمل اليوم", _sender(), MEMBERS)
    assert hit is None


def test_self_disclosure():
    hit = scan_message("أنا خالد حسن", _sender(3), MEMBERS)
    assert hit is not None
    assert hit.kind == "self"


def test_mute_duration_parser():
    assert parse_mute_duration("/كتم") == 60
    assert parse_mute_duration("/كتم 10دقائق") == 600
    assert parse_mute_duration("/كتم 1ساعة") == 3600
    assert parse_mute_duration("/كتم 2يوم") == 172800
    assert parse_mute_duration("mute 10min") == 600
    assert format_duration(60) == "دقيقة واحدة"
    assert format_duration(3600) == "1 ساعة"


def test_parse_moderation_command_arabic_and_english():
    assert parse_moderation_command("/كتم") == ("mute", 60)
    assert parse_moderation_command("كتم 10دقائق")[0] == "mute"
    assert parse_moderation_command("كتم 10دقائق")[1] == 600
    assert parse_moderation_command("/mute 1hour") == ("mute", 3600)
    assert parse_moderation_command("فك_الكتم") == ("unmute", 0)
    assert parse_moderation_command("/إلغاء_الكتم") == ("unmute", 0)
    assert parse_moderation_command("unmute") == ("unmute", 0)
    assert parse_moderation_command("مرحبا") is None


def test_parse_power_command():
    assert parse_power_command("/pause") == "pause"
    assert parse_power_command("pause") == "pause"
    assert parse_power_command("/resume") == "resume"
    assert parse_power_command("resume") == "resume"
    assert parse_power_command("stop") is None
    assert parse_power_command("كتم") is None


def test_extract_relay_alias_from_bot_message():
    assert extract_relay_alias("✦ الذئب\n────────\nمرحبا") == "الذئب"
    assert extract_relay_alias("✦ مشرف 1\n────────\nتم") == "مشرف 1"
    assert extract_relay_alias("رسالة عادية") is None


def test_redact_hides_real_names():
    text = redact_sensitive("الذئب هو أحمد محمد", MEMBERS)
    assert "أحمد" not in text
    assert "******" in text
