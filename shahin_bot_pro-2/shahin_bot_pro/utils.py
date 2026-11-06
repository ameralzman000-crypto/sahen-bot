import re

from config import (
    ADMIN_DISPLAY,
    MAX_ALIAS,
    MAX_REAL_NAME,
    MIN_ALIAS,
    MIN_REAL_NAME,
    MOD_DISPLAY_PREFIX,
    RESERVED_ALIASES,
    ROLE_ADMIN,
    ROLE_MODERATOR,
)


ALIAS_RE = re.compile(r"^[\w\u0600-\u06FF \u0750-\u077F.-]+$", re.UNICODE)
NAME_RE = re.compile(r"^[\w\u0600-\u06FF \u0750-\u077F.-]+$", re.UNICODE)


def normalize_space(text: str) -> str:
    return " ".join((text or "").split()).strip()


def is_reserved_alias(alias: str) -> bool:
    value = normalize_space(alias)
    lowered = value.casefold()
    if lowered in {item.casefold() for item in RESERVED_ALIASES}:
        return True
    if value.startswith(MOD_DISPLAY_PREFIX):
        return True
    return False


def validate_real_name(name: str) -> str | None:
    value = normalize_space(name)
    if len(value) < MIN_REAL_NAME or len(value) > MAX_REAL_NAME:
        return None
    if not NAME_RE.match(value):
        return None
    return value


def validate_alias(alias: str) -> str | None:
    value = normalize_space(alias)
    if len(value) < MIN_ALIAS or len(value) > MAX_ALIAS:
        return None
    if not ALIAS_RE.match(value):
        return None
    if is_reserved_alias(value):
        return None
    if value.startswith("*"):
        return None
    return value


def display_name(user: dict | None) -> str:
    if not user:
        return "عضو"
    role = user.get("role")
    if role == ROLE_ADMIN:
        return ADMIN_DISPLAY
    if role == ROLE_MODERATOR:
        number = user.get("moderator_number") or 1
        return f"{MOD_DISPLAY_PREFIX} {number}"
    return user.get("alias") or "عضو"


def can_reveal_identity(user: dict | None) -> bool:
    if not user:
        return False
    if user.get("status") != "approved":
        return False
    if user.get("role") == ROLE_ADMIN:
        return True
    if user.get("role") == ROLE_MODERATOR and user.get("can_reveal"):
        return True
    return False


def is_admin(user: dict | None, admin_id: int, user_id: int | None = None) -> bool:
    if user_id is not None and user_id == admin_id:
        return True
    return bool(user and user.get("role") == ROLE_ADMIN)


def is_staff(user: dict | None, admin_id: int, user_id: int | None = None) -> bool:
    if is_admin(user, admin_id, user_id):
        return True
    return bool(user and user.get("role") == ROLE_MODERATOR and user.get("status") == "approved")


def build_text(alias: str, text: str) -> str:
    body = text or ""
    full = f"✦ {alias}\n────────\n{body}"
    return full[:4096]


def build_caption(alias: str, caption: str | None) -> str:
    header = f"✦ {alias}"
    if caption:
        full = f"{header}\n{caption}"
        return full[:1024]
    return header[:1024]


def format_identity(user: dict, sender_id: int) -> str:
    if not user:
        return (
            "هوية صاحب الرسالة\n"
            "────────\n"
            f"المعرف: `{sender_id}`\n"
            "الحالة: غير مسجل"
        )
    username = user.get("username")
    username_line = f"@{username}" if username else "غير متوفر"
    return (
        "هوية صاحب الرسالة\n"
        "────────\n"
        f"الاسم الحقيقي: {user.get('real_name') or 'غير مسجل'}\n"
        f"الاسم المستعار: {display_name(user)}\n"
        f"المعرف: `{user.get('user_id') or sender_id}`\n"
        f"المستخدم: {username_line}\n"
        f"الدور: {user.get('role') or 'member'}\n"
        f"الحالة: {user.get('status') or 'unknown'}"
    )
