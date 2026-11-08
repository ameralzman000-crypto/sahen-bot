import os
from dotenv import load_dotenv

load_dotenv()


def resolve_db_path(raw: str | None = None) -> str:
    value = (raw or "").strip()
    if not value:
        value = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "alias_group.db")
    parent = os.path.dirname(os.path.abspath(value))
    if parent:
        os.makedirs(parent, exist_ok=True)
    return value


BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
_admin_raw = (os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID") or "1441524960").split(",")[0].strip()
ADMIN_ID = int(_admin_raw) if _admin_raw.lstrip("-").isdigit() else 1441524960
DB_PATH = resolve_db_path(os.getenv("DB_PATH"))

WEB_HOST = os.getenv("WEB_HOST", "0.0.0.0").strip() or "0.0.0.0"
WEB_PORT = int(os.getenv("PORT") or os.getenv("WEB_PORT", "8080") or 8080)
WEB_PASSWORD = os.getenv("WEB_PASSWORD", "").strip()
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
AUTO_PURGE_HOURS = int(os.getenv("AUTO_PURGE_HOURS", "24") or 24)
AUTO_PURGE_ENABLED = os.getenv("AUTO_PURGE_ENABLED", "true").lower() in ("1", "true", "yes", "on")

STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_BANNED = "banned"

ROLE_ADMIN = "admin"
ROLE_MODERATOR = "moderator"
ROLE_MEMBER = "member"

ADMIN_DISPLAY = "المدير"
MOD_DISPLAY_PREFIX = "مشرف"

RESERVED_ALIASES = {
    ADMIN_DISPLAY,
    "مدير",
    "المشرف",
    "مشرف",
    "admin",
    "administrator",
    "mod",
    "moderator",
}

MAX_REAL_NAME = 64
MIN_REAL_NAME = 2
MAX_ALIAS = 32
MIN_ALIAS = 2
MAX_RULES = 3500

DEFAULT_RULES = (
    "قوانين مجموعة عين الشاهين\n"
    "────────\n"
    "1. التسجيل إلزامي عبر البوت في الخاص بالاسم الحقيقي ثم المستعار، ولا يُسمح بالكتابة قبل موافقة المدير.\n"
    "2. يُمنع السؤال عن هويات الأعضاء أو كشفها أو ربط الاسم المستعار بالاسم الحقيقي.\n"
    "3. الأحاديث العامة وذكر أشخاص خارج المجموعة مسموحة ما دامت لا تمس أعضاء المجموعة.\n"
    "4. تظهر الرسائل بالاسم المستعار فقط. المدير يظهر باسم «المدير» والمشرفون «مشرف 1» وهكذا.\n"
    "5. يُمنع انتحال اسم المدير أو المشرفين أو استخدام أسماء مستعارة مسيئة.\n"
    "6. الإفصاح الطوعي عن هويتك يُحذف في المرة الأولى مع تنبيه علني، وفي المرة الثانية تتحمل المسؤولية كاملة.\n"
    "7. مخالفة كشف الهوية: حذف فوري، كتم دقيقة، وتحذير علني أول وأخير قبل الطرد.\n"
    "8. كشف الهوية حق للمدير أو المشرف المصرح له عبر زر الكشف في الخاص فقط.\n"
    "9. قرارات المدير نهائية في قبول الأعضاء وإدارة الأسماء المستعارة."
)


def reload_from_env():
    global BOT_TOKEN, ADMIN_ID, DB_PATH, WEB_HOST, WEB_PORT, WEB_PASSWORD, LOG_LEVEL
    global AUTO_PURGE_HOURS, AUTO_PURGE_ENABLED
    load_dotenv(override=True)
    BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
    admin_raw = (os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID") or str(ADMIN_ID)).split(",")[0].strip()
    if admin_raw.lstrip("-").isdigit():
        ADMIN_ID = int(admin_raw)
    DB_PATH = resolve_db_path(os.getenv("DB_PATH", DB_PATH))
    WEB_HOST = os.getenv("WEB_HOST", WEB_HOST).strip() or "0.0.0.0"
    WEB_PORT = int(os.getenv("PORT") or os.getenv("WEB_PORT", str(WEB_PORT)) or WEB_PORT)
    WEB_PASSWORD = os.getenv("WEB_PASSWORD", WEB_PASSWORD).strip()
    LOG_LEVEL = os.getenv("LOG_LEVEL", LOG_LEVEL)
    try:
        AUTO_PURGE_HOURS = int(os.getenv("AUTO_PURGE_HOURS", str(AUTO_PURGE_HOURS)) or 24)
    except ValueError:
        AUTO_PURGE_HOURS = 24
    AUTO_PURGE_ENABLED = os.getenv("AUTO_PURGE_ENABLED", "true" if AUTO_PURGE_ENABLED else "false").lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
