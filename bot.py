#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import html
import logging
import os
import re
import secrets
import sys
import traceback
from datetime import datetime, timedelta, timezone
from typing import Any

from telegram import (
    BotCommand,
    BotCommandScopeChat,
    ChatPermissions,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    Update,
)
from telegram.constants import ChatMemberStatus, ChatType, ParseMode
from telegram.error import BadRequest, Forbidden, RetryAfter, TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ChatJoinRequestHandler,
    ChatMemberHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

import config
import database as db
from config import (
    ADMIN_DISPLAY,
    ADMIN_ID,
    BOT_TOKEN,
    DEFAULT_RULES,
    MAX_RULES,
    ROLE_ADMIN,
    ROLE_MEMBER,
    ROLE_MODERATOR,
    STATUS_APPROVED,
    STATUS_BANNED,
    STATUS_PENDING,
    STATUS_REJECTED,
)
from security import (
    extract_relay_alias,
    format_duration,
    parse_moderation_command,
    parse_power_command,
    scan_message,
)
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

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("aliasbot")

WAITING_REAL_NAME, WAITING_ALIAS = range(2)

HELP_TEXT = (
    "بوت الأسماء المستعارة للمجموعات والقنوات\n"
    "────────\n"
    "الأعضاء:\n"
    "/start — بدء التسجيل\n"
    "/help — هذه الرسالة\n"
    "/myinfo — بياناتك\n"
    "/rules — القوانين\n"
    "/cancel — إلغاء التسجيل\n"
    "/ingroup — السماح بالكتابة داخل المجموعة على مسؤوليتك\n"
    "/outgroup — إلغاء الكتابة داخل المجموعة والعودة للخاص فقط\n"
    "الكتابة الافتراضية: أرسل رسالتك للبوت في الخاص لتظهر بالاسم المستعار.\n"
    "في المجموعة: الكتابة داخلها اختيارية عبر /ingroup، لكنها تكشف اسمك في إشعار «يكتب».\n"
    "في القناة: البوت وحده ينشر، ولا يوجد إشعار كتابة.\n"
    "\n"
    "الإدارة والمشرفون:\n"
    "/pending — طلبات الانتظار\n"
    "/approve <id> — قبول عضو\n"
    "/reject <id> — رفض عضو\n"
    "/members — قائمة الأعضاء\n"
    "/stats — الإحصاءات\n"
    "/whois <id> — عرض هوية عضو\n"
    "/mute [10min] — كتم بالرد على رسالة معاد نشرها\n"
    "/unmute — فك الكتم بالرد على رسالة معاد نشرها\n"
    "\n"
    "المدير فقط:\n"
    "/ban <id> — حظر عضو\n"
    "/unban <id> — إلغاء الحظر\n"
    "/unregister <id> — إلغاء تسجيل عضو ليعيد /start\n"
    "/setalias <id> <اسم> — تعديل الاسم المستعار\n"
    "/setname <id> <اسم> — تعديل الاسم الحقيقي\n"
    "/setmod <id> — تعيين مشرف\n"
    "/unsetmod <id> — إلغاء الإشراف\n"
    "/allowreveal <id> — السماح بالكشف\n"
    "/denyreveal <id> — منع الكشف\n"
    "/setgroup — ربط هذه المجموعة (من داخل المجموعة)\n"
    "/setchannel — ربط قناة من الخاص: تحويل منشور أو معرّف أو رمز ربط\n"
    "/invite <id> — إعادة إرسال رابط الدخول لعضو مقبول\n"
    "/purge — مسح المحادثات الحديثة\n"
    "/lockgroup — قفل الدخول إلا عبر رابط البوت أو المدير\n"
    "/setrules — تعديل القوانين\n"
    "/announce <text> — إعلان في المجموعة أو القناة\n"
    "/wipe — مسح كل البيانات وإعادة التهيئة\n"
    "/pause — إيقاف إعادة النشر مؤقتاً\n"
    "/resume — استئناف إعادة النشر\n"
    "/control — لوحة التحكم\n"
    "/restart — إعادة تشغيل عملية البوت\n"
    "/stop — إيقاف عملية البوت\n"
    "\n"
    "لكشف هوية صاحب رسالة:\n"
    "- اضغط زر ⚡ بجانب الرسالة\n"
    "- أو ردّ عليها ثم أرسل *\n"
    "تصل التفاصيل في الخاص فقط. راسل البوت /start في الخاص أولاً."
)

MEMBER_COMMANDS = [
    BotCommand("start", "بدء التسجيل"),
    BotCommand("help", "عرض المساعدة"),
    BotCommand("myinfo", "بياناتك"),
    BotCommand("rules", "عرض القوانين"),
    BotCommand("cancel", "إلغاء التسجيل"),
    BotCommand("ingroup", "كتابة داخل المجموعة على مسؤوليتك"),
    BotCommand("outgroup", "إلغاء الكتابة داخل المجموعة"),
]

ADMIN_COMMANDS = MEMBER_COMMANDS + [
    BotCommand("pending", "طلبات الانتظار"),
    BotCommand("approve", "قبول عضو"),
    BotCommand("reject", "رفض عضو"),
    BotCommand("members", "قائمة الأعضاء"),
    BotCommand("stats", "الإحصاءات"),
    BotCommand("whois", "عرض هوية عضو"),
    BotCommand("mute", "كتم عضو"),
    BotCommand("unmute", "فك كتم عضو"),
    BotCommand("ban", "حظر عضو"),
    BotCommand("unban", "إلغاء الحظر"),
    BotCommand("unregister", "إلغاء تسجيل عضو"),
    BotCommand("setalias", "تعديل الاسم المستعار"),
    BotCommand("setname", "تعديل الاسم الحقيقي"),
    BotCommand("setmod", "تعيين مشرف"),
    BotCommand("unsetmod", "إلغاء الإشراف"),
    BotCommand("allowreveal", "السماح بكشف الهوية"),
    BotCommand("denyreveal", "منع كشف الهوية"),
    BotCommand("setgroup", "ربط هذه المجموعة"),
    BotCommand("setchannel", "ربط قناة من الخاص"),
    BotCommand("invite", "إعادة إرسال رابط الدخول"),
    BotCommand("purge", "مسح المحادثات"),
    BotCommand("lockgroup", "قفل الدخول إلا بالرابط"),
    BotCommand("setrules", "تعديل القوانين"),
    BotCommand("announce", "إعلان في المجموعة أو القناة"),
    BotCommand("wipe", "مسح كل البيانات"),
    BotCommand("pause", "إيقاف إعادة النشر مؤقتاً"),
    BotCommand("resume", "استئناف إعادة النشر"),
    BotCommand("control", "لوحة التحكم"),
    BotCommand("restart", "إعادة تشغيل البوت"),
    BotCommand("stop", "إيقاف البوت"),
]

_SHUTDOWN_ACTION: str | None = None
CHANNEL_BIND_TOKEN_RE = re.compile(r"(?:^|\s)BIND[-_]?([A-Z0-9]{6,16})(?:\s|$)", re.I)
CHANNEL_ID_RE = re.compile(r"^-100\d{6,}$")


def _safe_username(update: Update) -> str | None:
    user = update.effective_user
    return user.username if user else None


def _target_id(args: list[str] | None) -> int | None:
    if not args:
        return None
    try:
        return int(args[0])
    except (TypeError, ValueError):
        return None


async def safe_reply(message: Message | None, text: str, **kwargs: Any) -> Message | None:
    if message is None:
        return None
    try:
        return await message.reply_text(text, **kwargs)
    except TelegramError as exc:
        logger.warning("reply failed: %s", exc)
        return None


async def safe_send_private(context: ContextTypes.DEFAULT_TYPE, user_id: int, text: str, **kwargs: Any) -> bool:
    try:
        await context.bot.send_message(chat_id=user_id, text=text, **kwargs)
        return True
    except Forbidden:
        logger.info("cannot send private message to %s", user_id)
        return False
    except TelegramError as exc:
        logger.warning("private send failed for %s: %s", user_id, exc)
        return False


async def notify_admin(context: ContextTypes.DEFAULT_TYPE, text: str, reply_markup: InlineKeyboardMarkup | None = None) -> None:
    await safe_send_private(context, ADMIN_ID, text, reply_markup=reply_markup)


def staff_guard(update: Update) -> tuple[bool, dict | None]:
    user = update.effective_user
    if not user:
        return False, None
    record = db.get_user(user.id)
    return is_staff(record, ADMIN_ID, user.id), record


def admin_guard(update: Update) -> tuple[bool, dict | None]:
    user = update.effective_user
    if not user:
        return False, None
    record = db.get_user(user.id)
    return is_admin(record, ADMIN_ID, user.id), record


async def deny_if_not_staff(update: Update) -> bool:
    ok, _ = staff_guard(update)
    if ok:
        return False
    await safe_reply(update.effective_message, "هذا الأمر للمدير والمشرفين فقط.")
    return True


async def deny_if_not_admin(update: Update) -> bool:
    ok, _ = admin_guard(update)
    if ok:
        return False
    await safe_reply(update.effective_message, "هذا الأمر للمدير فقط.")
    return True


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    chat = update.effective_chat
    if not user or not update.message:
        return ConversationHandler.END
    if chat and chat.type != ChatType.PRIVATE:
        await update.message.reply_text("للتسجيل راسل البوت في الخاص ثم أرسل /start")
        return ConversationHandler.END
    db.ensure_admin(ADMIN_ID)
    record = db.get_user(user.id)
    if record:
        db.update_username(user.id, user.username)

    if user.id == ADMIN_ID:
        await update.message.reply_text(
            f"مرحباً {ADMIN_DISPLAY}.\n"
            "أنت المدير ويمكنك إدارة الأعضاء من هنا أو من المجموعة/القناة.\n\n"
            + HELP_TEXT
        )
        return ConversationHandler.END

    if record and record["status"] == STATUS_APPROVED:
        await update.message.reply_text(
            f"أنت مسجّل مسبقاً.\n"
            f"الاسم المستعار: {display_name(record)}\n"
            f"أرسل رسالتك هنا في الخاص لتظهر في {bound_kind_label()} باسمك المستعار.\n"
            "للكتابة داخل المجموعة على مسؤوليتك أرسل /ingroup. إلغاء ذلك عبر /outgroup."
        )
        return ConversationHandler.END

    if record and record["status"] == STATUS_BANNED:
        await update.message.reply_text("حسابك محظور. تواصل مع المدير.")
        return ConversationHandler.END

    if record and record["status"] == STATUS_PENDING:
        await update.message.reply_text(
            "طلبك قيد المراجعة من المدير. انتظر الموافقة."
        )
        return ConversationHandler.END

    context.user_data.clear()
    await update.message.reply_text(
        "مرحباً. للانضمام أرسل اسمك الحقيقي أولاً.\n"
        "مثال: أحمد محمد\n\n"
        "لا تحتاج رابط المجموعة أو القناة. بعد موافقة المدير يصلك رابط الدخول هنا في الخاص."
    )
    return WAITING_REAL_NAME


async def recv_real_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message or not update.message.text:
        await safe_reply(update.effective_message, "أرسل اسمك الحقيقي كنص.")
        return WAITING_REAL_NAME
    name = validate_real_name(update.message.text)
    if not name:
        await update.message.reply_text(
            "الاسم غير صالح. استخدم حروفاً فقط، بين حرفين و64 حرفاً."
        )
        return WAITING_REAL_NAME
    context.user_data["real_name"] = name
    await update.message.reply_text(
        "تم حفظ الاسم الحقيقي.\nالآن أرسل الاسم المستعار الذي سيظهر عند النشر."
    )
    return WAITING_ALIAS


async def recv_alias(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    if not user or not update.message or not update.message.text:
        await safe_reply(update.effective_message, "أرسل الاسم المستعار كنص.")
        return WAITING_ALIAS
    alias = validate_alias(update.message.text)
    if not alias:
        await update.message.reply_text(
            "الاسم المستعار غير صالح أو محجوز (مثل المدير/مشرف).\n"
            "استخدم حروفاً فقط، بين حرفين و32 حرفاً."
        )
        return WAITING_ALIAS
    if db.alias_taken(alias, exclude_user_id=user.id):
        await update.message.reply_text("هذا الاسم المستعار مستخدم. اختر اسماً آخر.")
        return WAITING_ALIAS

    real_name = context.user_data.get("real_name")
    if not real_name:
        await update.message.reply_text("ابدأ من جديد عبر /start")
        return ConversationHandler.END

    record = db.upsert_registration(user.id, real_name, alias, user.username)
    context.user_data.clear()

    if record and record["role"] == ROLE_ADMIN:
        await update.message.reply_text("تم تحديث بياناتك كمدير.")
        return ConversationHandler.END

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("قبول", callback_data=f"approve:{user.id}"),
                InlineKeyboardButton("رفض", callback_data=f"reject:{user.id}"),
            ]
        ]
    )
    username_line = f"@{user.username}" if user.username else "غير متوفر"
    await notify_admin(
        context,
        (
            "طلب انضمام جديد\n"
            "────────\n"
            f"الاسم الحقيقي: {real_name}\n"
            f"الاسم المستعار: {alias}\n"
            f"المعرف: `{user.id}`\n"
            f"المستخدم: {username_line}"
        ),
        reply_markup=keyboard,
    )
    await update.message.reply_text(
        "تم إرسال طلبك للمدير.\n"
        "انتظر الموافقة. رابط الدخول يصلك هنا في الخاص بعد القبول فقط."
    )
    return ConversationHandler.END


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await safe_reply(update.effective_message, "تم إلغاء التسجيل.")
    return ConversationHandler.END


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await safe_reply(update.effective_message, HELP_TEXT)


def current_rules() -> str:
    try:
        return db.get_rules()
    except Exception:
        logger.exception("failed to load rules")
        return DEFAULT_RULES


async def cmd_rules(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await safe_reply(update.effective_message, current_rules()[:4096])


def pause_keyboard() -> InlineKeyboardMarkup:
    paused = db.is_paused()
    toggle = (
        [InlineKeyboardButton("استئناف إعادة النشر", callback_data="bot:resume")]
        if paused
        else [InlineKeyboardButton("إيقاف مؤقت", callback_data="bot:pause")]
    )
    return InlineKeyboardMarkup(
        [
            toggle,
            [
                InlineKeyboardButton("مسح المحادثات", callback_data="bot:purge"),
                InlineKeyboardButton("قفل الدخول", callback_data="bot:lock"),
            ],
            [
                InlineKeyboardButton("إعادة تشغيل البوت", callback_data="bot:restart"),
                InlineKeyboardButton("إيقاف البوت", callback_data="bot:stop"),
            ],
            [InlineKeyboardButton("تحديث الحالة", callback_data="bot:status")],
        ]
    )


def bot_status_text() -> str:
    if db.is_paused():
        return (
            "حالة البوت: متوقف مؤقتاً\n"
            "لا يُعاد نشر الرسائل بالأسماء المستعارة ولا تُطبَّق الفلترة.\n"
            "أوامر المدير ما زالت تعمل."
        )
    return (
        "حالة البوت: يعمل\n"
        "إعادة النشر بالأسماء المستعارة والفلترة الأمنية مفعّلتان."
    )


def bound_kind_label() -> str:
    return "القناة" if db.is_channel_bound() else "المجموعة"


def bound_chat_types() -> tuple[str, ...]:
    return (ChatType.GROUP, ChatType.SUPERGROUP, ChatType.CHANNEL)


def is_bound_chat(chat) -> bool:
    return bool(chat) and chat.type in bound_chat_types()


def normalize_bound_type(chat_type: str | None) -> str:
    value = (chat_type or "").lower()
    if value == ChatType.CHANNEL or value == "channel":
        return "channel"
    if value in (ChatType.GROUP, ChatType.SUPERGROUP, "group", "supergroup"):
        return "supergroup"
    return "supergroup"


async def bind_chat(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    chat_type: str,
) -> str:
    kind = normalize_bound_type(chat_type)
    db.set_bound_chat(chat_id, kind)
    lock_text = await lock_group_access(context, chat_id)
    if kind != "channel":
        await notify_existing_members(context, chat_id)
    label = "القناة" if kind == "channel" else "المجموعة"
    return f"تم ربط {label}. المعرف: {chat_id}\n{lock_text}"


def _new_channel_bind_token() -> str:
    return secrets.token_hex(4).upper()


def _channel_bind_instructions(token: str | None = None) -> str:
    lines = [
        "أوامر التيليجرام داخل القناة لا تصل للبوت. اربطها من الخاص فقط:",
        "1) أضف البوت مشرفاً في القناة مع النشر وحذف الرسائل ودعوة الأعضاء.",
        "2) حوّل أي منشور من القناة إلى الخاص مع البوت.",
        "أو أرسل /setchannel -100xxxxxxxxxx",
        "أو أرسل /setchannel @username إن كان للقناة يوزر.",
    ]
    if token:
        lines.append(f"أو انسخ هذا الرمز وانشره مرة واحدة في القناة: BIND-{token}")
        lines.append("بعد النشر احذفه. البوت يلتقطه ويربط القناة ثم يمكنك مسحه.")
    return "\n".join(lines)


def extract_channel_bind_token(text: str | None) -> str | None:
    if not text:
        return None
    match = CHANNEL_BIND_TOKEN_RE.search(text.strip())
    return match.group(1).upper() if match else None


def parse_channel_ref(raw: str | None) -> str | int | None:
    value = (raw or "").strip()
    if not value:
        return None
    if value.startswith("https://t.me/") or value.startswith("http://t.me/") or value.startswith("t.me/"):
        slug = value.split("t.me/", 1)[-1].split("?", 1)[0].strip("/")
        if slug.startswith("+") or "/" in slug or not slug:
            return None
        return f"@{slug}"
    if value.startswith("@"):
        return value
    if CHANNEL_ID_RE.match(value) or (value.lstrip("-").isdigit() and value.startswith("-100")):
        try:
            return int(value)
        except ValueError:
            return None
    if value.lstrip("-").isdigit():
        try:
            return int(value)
        except ValueError:
            return None
    return None


async def resolve_and_bind_channel(
    context: ContextTypes.DEFAULT_TYPE,
    target: str | int,
) -> str:
    try:
        info = await context.bot.get_chat(target)
    except TelegramError as exc:
        return f"تعذر الوصول للقناة: {exc}\nأضف البوت مشرفاً أولاً ثم أعد المحاولة."
    if info.type != ChatType.CHANNEL:
        return "المعرّف ليس قناة. للمجموعة استخدم /setgroup داخلها."
    me = await context.bot.get_me()
    try:
        member = await context.bot.get_chat_member(info.id, me.id)
        if member.status not in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER):
            return "البوت موجود في القناة لكنه ليس مشرفاً. اجعله مشرفاً ثم أعد /setchannel."
    except TelegramError as exc:
        return f"تعذر التحقق من صلاحية البوت في القناة: {exc}"
    return await bind_chat(context, info.id, ChatType.CHANNEL)


async def announce_group(context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    chat_id = db.get_group_chat_id()
    if not chat_id:
        return
    try:
        await context.bot.send_message(chat_id=chat_id, text=text)
    except TelegramError as exc:
        logger.warning("bound chat announce failed: %s", exc)


def existing_members_notice_text(bot_username: str | None = None) -> str:
    start_line = (
        f"افتحوا الخاص مع @{bot_username} ثم أرسلوا /start"
        if bot_username
        else "افتحوا الخاص مع البوت ثم أرسلوا /start"
    )
    return (
        "تنبيه للأعضاء الموجودين قبل دخول البوت\n"
        "────────\n"
        "أنتم باقون في المجموعة ولن تُطردوا.\n"
        "للكتابة بالاسم المستعار:\n"
        f"1. {start_line}\n"
        "2. سجّلوا الاسم الحقيقي ثم الاسم المستعار.\n"
        "3. انتظروا موافقة المدير.\n\n"
        "لا تكتبوا داخل المجموعة قبل القبول حتى لا يظهر اسمكم الحقيقي."
    )


async def notify_existing_members(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int | None = None,
) -> bool:
    target = chat_id or db.get_group_chat_id()
    if not target or db.is_channel_bound():
        return False
    if db.get_setting("existing_members_notice_sent") == str(target):
        return False
    username = None
    try:
        me = await context.bot.get_me()
        username = getattr(me, "username", None)
    except TelegramError:
        pass
    text = existing_members_notice_text(username)
    try:
        sent = await context.bot.send_message(chat_id=target, text=text)
    except TelegramError as exc:
        logger.warning("existing members notice failed: %s", exc)
        return False
    db.set_setting("existing_members_notice_sent", str(target))
    if sent:
        try:
            await context.bot.pin_chat_message(
                chat_id=target,
                message_id=sent.message_id,
                disable_notification=False,
            )
        except TelegramError as exc:
            logger.warning("pin existing members notice failed: %s", exc)
    return True


MEMBER_CHAT_PERMISSIONS = ChatPermissions(
    can_send_messages=True,
    can_send_audios=True,
    can_send_documents=True,
    can_send_photos=True,
    can_send_videos=True,
    can_send_video_notes=True,
    can_send_voice_notes=True,
    can_send_polls=True,
    can_send_other_messages=True,
    can_add_web_page_previews=True,
    can_invite_users=False,
    can_pin_messages=False,
    can_change_info=False,
)


async def lock_group_access(context: ContextTypes.DEFAULT_TYPE, chat_id: int | None = None) -> str:
    target = chat_id or db.get_group_chat_id()
    if not target:
        return "اربط المجموعة أو القناة أولاً عبر /setgroup أو /setchannel."
    channel = db.is_channel_bound()
    label = "القناة" if channel else "المجموعة"
    notes = []
    try:
        await context.bot.export_chat_invite_link(chat_id=target)
        notes.append("تم إلغاء روابط الدعوة القديمة.")
    except TelegramError as exc:
        logger.warning("rotate primary invite failed: %s", exc)
        notes.append(f"تعذر إلغاء الرابط العام. اجعل {label} خاصة من إعدادات تيليجرام.")
    db.set_setting("group_invite_link", "")
    if not channel:
        try:
            await context.bot.set_chat_permissions(chat_id=target, permissions=MEMBER_CHAT_PERMISSIONS)
            notes.append("من لم يختر /ingroup يبقى مكتوماً. من يفعّله يُسمح له بالكتابة داخل المجموعة على مسؤوليته.")
        except TelegramError as exc:
            logger.warning("set chat permissions failed: %s", exc)
        restricted = await sync_member_write_permissions(context, target)
        if restricted:
            notes.append(f"تم كتم {restricted} عضواً لم يفعّلوا الكتابة داخل المجموعة.")
        notes.append("اجعل المجموعة خاصة وبدون يوزر عام حتى لا يدخل أحد من البحث.")
    else:
        notes.append("القناة لا تظهر إشعار «يكتب». البوت وحده ينشر بالاسم المستعار.")
        notes.append("عطّل التعليقات حتى لا تُربط مجموعة نقاش تكشف الهوية.")
        notes.append("اجعل القناة خاصة وبدون يوزر عام.")
    return (
        f"{label} مقفلة. الدخول فقط عبر رابط يرسله البوت بعد الموافقة، أو عبر /invite من المدير.\n"
        "الأعضاء يرسلون رسائلهم للبوت في الخاص فتظهر بالاسم المستعار.\n"
        + "\n".join(notes)
    )


async def create_member_invite(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> str | None:
    chat_id = db.get_group_chat_id()
    if not chat_id:
        return None
    try:
        invite = await context.bot.create_chat_invite_link(
            chat_id=chat_id,
            name=f"approved-{user_id}",
            member_limit=1,
        )
        return invite.invite_link
    except TelegramError as exc:
        logger.warning("create member invite failed for %s: %s", user_id, exc)
        return None


async def _delete_message_batch(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    message_ids: list[int],
) -> tuple[int, int]:
    if not message_ids:
        return 0, 0
    try:
        await context.bot.delete_messages(chat_id=chat_id, message_ids=message_ids)
        return len(message_ids), 0
    except RetryAfter as exc:
        await asyncio.sleep(float(getattr(exc, "retry_after", 1)) + 0.2)
        try:
            await context.bot.delete_messages(chat_id=chat_id, message_ids=message_ids)
            return len(message_ids), 0
        except TelegramError:
            pass
    except TelegramError:
        pass
    deleted = 0
    failed = 0
    for mid in message_ids:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=mid)
            deleted += 1
        except RetryAfter as exc:
            await asyncio.sleep(float(getattr(exc, "retry_after", 1)) + 0.2)
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=mid)
                deleted += 1
            except TelegramError:
                failed += 1
        except TelegramError:
            failed += 1
    return deleted, failed


async def purge_group_messages(context: ContextTypes.DEFAULT_TYPE) -> tuple[int, int]:
    chat_id = db.get_group_chat_id()
    if not chat_id:
        return 0, 0
    last_id = 0
    try:
        marker = await context.bot.send_message(chat_id=chat_id, text=".")
        last_id = int(marker.message_id)
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=last_id)
        except TelegramError:
            pass
    except TelegramError as exc:
        logger.warning("purge marker failed: %s", exc)
    known: set[int] = set()
    for row in db.list_message_ids(chat_id):
        for mid in (row.get("relayed_id"), row.get("original_id")):
            if mid:
                known.add(int(mid))
    if not last_id and known:
        last_id = max(known)
    if not last_id:
        db.clear_message_map(chat_id)
        return 0, 0
    window = min(last_id, 20000)
    start_id = max(1, last_id - window + 1)
    ids = set(range(start_id, last_id + 1))
    ids.update(known)
    ordered = sorted(ids, reverse=True)
    deleted = 0
    failed = 0
    for index in range(0, len(ordered), 100):
        batch = ordered[index:index + 100]
        batch_deleted, batch_failed = await _delete_message_batch(context, chat_id, batch)
        deleted += batch_deleted
        failed += batch_failed
        await asyncio.sleep(0.05)
    db.clear_message_map(chat_id)
    return deleted, failed


def approval_message(invite: str | None) -> str:
    rules = current_rules()[:3200]
    label = bound_kind_label()
    if db.is_channel_bound():
        writing = (
            f"أرسل رسائلك هنا في الخاص لتظهر في {label} بالاسم المستعار.\n"
            "القناة لا تظهر إشعار كتابة باسمك."
        )
    else:
        writing = (
            f"بعد الدخول: أرسل رسائلك هنا في الخاص لتظهر بالاسم المستعار دون كشف هويتك في الإشعارات.\n"
            "إذا أردت الكتابة داخل المجموعة رغم كشف اسمك في إشعار «يكتب»، أرسل /ingroup على مسؤوليتك."
        )
    if invite:
        return (
            "تم قبول طلبك.\n"
            f"هذا رابط دخولك ل{label} (لمرة واحدة، لا تشاركه):\n"
            f"{invite}\n\n"
            f"{writing}\n\n"
            f"{rules}"
        )
    return (
        "تم قبول طلبك.\n"
        f"{writing}\n"
        f"لم يتم توليد رابط الدخول تلقائياً. تأكد أن البوت مشرف وله صلاحية دعوة الأعضاء، ثم أعد /setgroup أو /setchannel.\n\n"
        f"{rules}"
    )


async def notify_approval(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> None:
    invite = await create_member_invite(context, user_id)
    await safe_send_private(context, user_id, approval_message(invite))


async def apply_pause(context: ContextTypes.DEFAULT_TYPE, paused: bool) -> str:
    db.set_paused(paused)
    if paused:
        text = "تم إيقاف البوت مؤقتاً. الرسائل تظهر بهوية تيليجرام العادية حتى الاستئناف."
    else:
        text = "تم استئناف البوت. الرسائل تُحذف وتُعاد نشرها بالأسماء المستعارة."
    await announce_group(context, text)
    return text


def confirm_process_keyboard(action: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("تأكيد", callback_data=f"bot:{action}:confirm"),
                InlineKeyboardButton("إلغاء", callback_data="bot:status"),
            ]
        ]
    )


async def request_process_action(update: Update, action: str) -> None:
    if action == "restart":
        text = "هل تريد إعادة تشغيل البوت؟ سيتوقف ثم يعمل من جديد."
    else:
        text = "هل تريد إيقاف البوت؟ لن يعمل حتى تشغّله من الخادم مجدداً."
    await safe_reply(
        update.effective_message,
        text,
        reply_markup=confirm_process_keyboard(action),
    )


def schedule_shutdown(application: Application, action: str) -> None:
    global _SHUTDOWN_ACTION
    _SHUTDOWN_ACTION = action
    application.stop_running()


async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await deny_if_not_admin(update):
        return
    text = await apply_pause(context, True)
    await safe_reply(update.effective_message, text, reply_markup=pause_keyboard())


async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await deny_if_not_admin(update):
        return
    text = await apply_pause(context, False)
    await safe_reply(update.effective_message, text, reply_markup=pause_keyboard())


async def cmd_control(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await deny_if_not_admin(update):
        return
    await safe_reply(update.effective_message, bot_status_text(), reply_markup=pause_keyboard())


async def cmd_restart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await deny_if_not_admin(update):
        return
    await request_process_action(update, "restart")


async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await deny_if_not_admin(update):
        return
    await request_process_action(update, "stop")


async def cmd_whois(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await deny_if_not_staff(update):
        return
    target = _target_id(context.args)
    if not target:
        await safe_reply(update.effective_message, "حدد المعرف الرقمي: /whois 123456")
        return
    record = db.get_user(target)
    await safe_reply(update.effective_message, format_identity(record, target), parse_mode=ParseMode.MARKDOWN)


async def cmd_announce(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await deny_if_not_admin(update):
        return
    message = update.effective_message
    if not message:
        return
    raw = " ".join(context.args).strip() if context.args else ""
    if not raw and message.reply_to_message:
        raw = (message.reply_to_message.text or message.reply_to_message.caption or "").strip()
    if not raw:
        await safe_reply(message, "أرسل النص بعد الأمر، أو رد على رسالة ثم استخدم /announce")
        return
    chat_id = db.get_group_chat_id()
    if not chat_id:
        await safe_reply(message, "اربط المجموعة أو القناة أولاً عبر /setgroup أو /setchannel")
        return
    try:
        await context.bot.send_message(chat_id=chat_id, text=f"إعلان\n────────\n{raw[:4000]}")
    except TelegramError as exc:
        await safe_reply(message, f"فشل الإعلان: {exc}")
        return
    await safe_reply(message, "تم إرسال الإعلان.")


async def cmd_mute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await deny_if_not_staff(update):
        return
    text = update.effective_message.text if update.effective_message else ""
    parsed = parse_moderation_command(text) or ("mute", 60)
    await _apply_moderation(update, context, parsed[0], parsed[1])


async def cmd_unmute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await deny_if_not_staff(update):
        return
    await _apply_moderation(update, context, "unmute", 0)


async def on_bot_control_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.from_user or not query.data:
        return
    if query.from_user.id != ADMIN_ID:
        try:
            await query.answer("هذا الأمر للمدير فقط.", show_alert=True)
        except TelegramError:
            pass
        return
    parts = query.data.split(":")
    action = parts[1] if len(parts) > 1 else ""
    confirmed = len(parts) > 2 and parts[2] == "confirm"
    if action in ("restart", "stop", "purge") and not confirmed:
        try:
            await query.answer()
        except TelegramError:
            pass
        prompts = {
            "restart": "هل تريد إعادة تشغيل البوت؟",
            "stop": "هل تريد إيقاف البوت؟",
            "purge": "هل تريد مسح المحادثات الحديثة لتعود فارغة؟",
        }
        try:
            await query.edit_message_text(prompts[action], reply_markup=confirm_process_keyboard(action))
        except TelegramError:
            pass
        return
    if action == "pause":
        text = await apply_pause(context, True)
        markup = pause_keyboard()
    elif action == "resume":
        text = await apply_pause(context, False)
        markup = pause_keyboard()
    elif action == "lock":
        text = await lock_group_access(context)
        markup = pause_keyboard()
    elif action == "purge":
        deleted, failed = await purge_group_messages(context)
        text = f"تم مسح المحادثات. حُذف {deleted} رسالة."
        if failed:
            text += f" تعذر حذف {failed} رسالة (أقدم من 48 ساعة غالباً)."
        markup = pause_keyboard()
    elif action == "restart":
        text = "جاري إعادة تشغيل البوت..."
        markup = None
        schedule_shutdown(context.application, "restart")
    elif action == "stop":
        text = "جاري إيقاف البوت..."
        markup = None
        schedule_shutdown(context.application, "stop")
    else:
        text = bot_status_text()
        markup = pause_keyboard()
    try:
        await query.answer()
    except TelegramError:
        pass
    body = text if action in ("restart", "stop") else text + "\n\n" + bot_status_text()
    try:
        await query.edit_message_text(body, reply_markup=markup)
    except TelegramError:
        pass


async def cmd_setrules(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await deny_if_not_admin(update):
        return
    message = update.effective_message
    if not message:
        return
    raw = ""
    if context.args:
        raw = " ".join(context.args).strip()
    if not raw and message.reply_to_message and message.reply_to_message.text:
        raw = message.reply_to_message.text.strip()
    if not raw:
        await safe_reply(
            message,
            "أرسل القوانين بعد الأمر، أو رد على رسالة القوانين ثم أرسل /setrules\n"
            "مثال:\n/setrules يمنع كشف الهوية والإساءة",
        )
        return
    if len(raw) > MAX_RULES:
        await safe_reply(message, f"النص طويل جداً. الحد الأقصى {MAX_RULES} حرفاً.")
        return
    db.set_rules(raw)
    await safe_reply(message, "تم تحديث القوانين.")


async def cmd_myinfo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user:
        return
    record = db.get_user(user.id)
    if not record:
        await safe_reply(update.effective_message, "لست مسجّلاً. أرسل /start")
        return
    text = (
        "بياناتك\n"
        "────────\n"
        f"الاسم الحقيقي: {record.get('real_name') or '-'}\n"
        f"الاسم الظاهر: {display_name(record)}\n"
        f"الدور: {record.get('role')}\n"
        f"الحالة: {record.get('status')}\n"
        f"كشف الهوية: {'مسموح' if can_reveal_identity(record) else 'غير مسموح'}\n"
        f"الكتابة داخل المجموعة: {'مسموحة على مسؤوليتك' if record.get('direct_write') else 'غير مسموحة (الخاص فقط)'}"
    )
    await safe_reply(update.effective_message, text)


def direct_write_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("أتحمل المسؤولية", callback_data="dw:on"),
                InlineKeyboardButton("إلغاء", callback_data="dw:cancel"),
            ]
        ]
    )


async def cmd_ingroup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user:
        return
    record = db.get_user(user.id)
    if user.id == ADMIN_ID:
        db.ensure_admin(ADMIN_ID)
        record = db.get_user(user.id)
    if not record or record.get("status") != STATUS_APPROVED:
        await safe_reply(update.effective_message, "يجب أن تكون عضواً مقبولاً أولاً. أرسل /start")
        return
    if db.is_channel_bound():
        await safe_reply(update.effective_message, "القناة لا تدعم الكتابة المباشرة. أرسل رسائلك هنا في الخاص.")
        return
    if record.get("direct_write"):
        await safe_reply(
            update.effective_message,
            "الكتابة داخل المجموعة مفعّلة مسبقاً على مسؤوليتك.\n"
            "إشعار «يكتب» سيظهر باسمك الحقيقي. للإلغاء أرسل /outgroup.",
        )
        return
    await safe_reply(
        update.effective_message,
        "تحذير: الكتابة داخل المجموعة تكشف اسمك الحقيقي في إشعار «فلان يكتب» قبل حذف الرسالة وإعادة نشرها بالاسم المستعار.\n"
        "الخاص يبقى الطريقة الآمنة. أكّد فقط إذا قبلت ذلك على مسؤوليتك.",
        reply_markup=direct_write_confirm_keyboard(),
    )


async def cmd_outgroup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user:
        return
    record = db.get_user(user.id)
    if not record or record.get("status") != STATUS_APPROVED:
        await safe_reply(update.effective_message, "يجب أن تكون عضواً مقبولاً أولاً. أرسل /start")
        return
    db.set_direct_write(user.id, False)
    chat_id = db.get_group_chat_id()
    if chat_id and not db.is_channel_bound():
        await apply_member_chat_permissions(context, chat_id, user.id)
    await safe_reply(
        update.effective_message,
        "تم إلغاء الكتابة داخل المجموعة. أرسل رسائلك هنا في الخاص لتظهر بالاسم المستعار دون كشف هويتك.",
    )


async def on_direct_write_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.from_user or not query.data:
        return
    user_id = query.from_user.id
    record = db.get_user(user_id)
    if user_id == ADMIN_ID:
        db.ensure_admin(ADMIN_ID)
        record = db.get_user(user_id)
    try:
        await query.answer()
    except TelegramError:
        pass
    if not record or record.get("status") != STATUS_APPROVED:
        try:
            await query.edit_message_text("يجب أن تكون عضواً مقبولاً أولاً.")
        except TelegramError:
            pass
        return
    if query.data == "dw:cancel":
        try:
            await query.edit_message_text("تم الإلغاء. استمر بالكتابة من الخاص.")
        except TelegramError:
            pass
        return
    db.set_direct_write(user_id, True)
    chat_id = db.get_group_chat_id()
    applied = False
    if chat_id and not db.is_channel_bound():
        applied = await apply_member_chat_permissions(context, chat_id, user_id)
    note = "يمكنك الآن الكتابة داخل المجموعة." if applied else "تم حفظ الخيار. إن لم تُفتح الكتابة داخل المجموعة تأكد أن البوت مشرف."
    try:
        await query.edit_message_text(
            "تم تفعيل الكتابة داخل المجموعة على مسؤوليتك.\n"
            "إشعار «يكتب» سيظهر باسمك الحقيقي، ثم تُحذف الرسالة وتُعاد بالاسم المستعار.\n"
            f"{note}\n"
            "للإلغاء أرسل /outgroup."
        )
    except TelegramError:
        pass


async def cmd_setgroup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await deny_if_not_admin(update):
        return
    chat = update.effective_chat
    if chat and chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
        text = await bind_chat(context, chat.id, chat.type)
        await safe_reply(update.effective_message, text, reply_markup=pause_keyboard())
        return
    if chat and chat.type == ChatType.CHANNEL:
        await safe_reply(
            update.effective_message,
            "أوامر القناة لا تصل للبوت. اربطها من الخاص عبر /setchannel.",
        )
        return
    token = _new_channel_bind_token()
    db.set_setting("channel_bind_token", token)
    await safe_reply(
        update.effective_message,
        "للمجموعة: أرسل /setgroup داخلها.\n\n" + _channel_bind_instructions(token),
        reply_markup=pause_keyboard(),
    )


def _forwarded_channel_id(message: Message | None) -> int | None:
    if not message:
        return None
    forwarded = getattr(message, "forward_from_chat", None)
    if forwarded and getattr(forwarded, "type", None) == ChatType.CHANNEL:
        return forwarded.id
    origin = getattr(message, "forward_origin", None)
    chat = getattr(origin, "chat", None) if origin else None
    if chat and getattr(chat, "type", None) == ChatType.CHANNEL:
        return chat.id
    return None


async def _bind_channel_from_private(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> bool:
    message = update.effective_message
    if not message:
        return False
    channel_id = _forwarded_channel_id(message) or _forwarded_channel_id(message.reply_to_message)
    if not channel_id:
        return False
    text = await resolve_and_bind_channel(context, channel_id)
    await safe_reply(message, text, reply_markup=pause_keyboard())
    return True


async def cmd_setchannel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await deny_if_not_admin(update):
        return
    message = update.effective_message
    chat = update.effective_chat
    if chat and chat.type == ChatType.CHANNEL:
        await safe_reply(message, "أوامر القناة لا تصل للبوت. استخدم الخاص: حوّل منشوراً أو /setchannel.")
        return
    if await _bind_channel_from_private(update, context):
        return
    raw = " ".join(context.args).strip() if context.args else ""
    target = parse_channel_ref(raw)
    if target is not None:
        text = await resolve_and_bind_channel(context, target)
        await safe_reply(message, text, reply_markup=pause_keyboard())
        return
    token = _new_channel_bind_token()
    db.set_setting("channel_bind_token", token)
    await safe_reply(message, _channel_bind_instructions(token), reply_markup=pause_keyboard())


async def cmd_invite(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await deny_if_not_staff(update):
        return
    target = _target_id(context.args)
    if not target:
        await safe_reply(update.effective_message, "حدد المعرف الرقمي: /invite 123456")
        return
    record = db.get_user(target)
    if not record or record["status"] != STATUS_APPROVED:
        await safe_reply(update.effective_message, "العضو غير موجود أو غير مقبول بعد.")
        return
    await notify_approval(context, target)
    await safe_reply(update.effective_message, f"تم إرسال رابط الدخول إلى {display_name(record)} في الخاص.")


async def cmd_purge(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await deny_if_not_admin(update):
        return
    await safe_reply(
        update.effective_message,
        f"سيتم تفريغ {bound_kind_label()} من الرسائل الحديثة (حتى حوالي 48 ساعة حسب قيود تيليجرام).\n"
        "الرسائل الأقدم من ذلك لا يستطيع البوت حذفها.",
        reply_markup=confirm_process_keyboard("purge"),
    )


async def cmd_lockgroup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await deny_if_not_admin(update):
        return
    text = await lock_group_access(context)
    await safe_reply(update.effective_message, text, reply_markup=pause_keyboard())


async def cmd_pending(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await deny_if_not_staff(update):
        return
    rows = db.list_by_status(STATUS_PENDING)
    if not rows:
        await safe_reply(update.effective_message, "لا توجد طلبات معلقة.")
        return
    lines = ["طلبات الانتظار:"]
    for row in rows:
        lines.append(
            f"- {row['real_name']} / {row['alias']} (`{row['user_id']}`)"
        )
    await safe_reply(update.effective_message, "\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def cmd_members(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await deny_if_not_staff(update):
        return
    rows = db.list_members()
    if not rows:
        await safe_reply(update.effective_message, "لا أعضاء.")
        return
    lines = ["الأعضاء:"]
    for row in rows:
        lines.append(
            f"- {display_name(row)} | {row.get('real_name') or '-'} | {row['status']} | `{row['user_id']}`"
        )
    text = "\n".join(lines)
    await safe_reply(update.effective_message, text[:4000], parse_mode=ParseMode.MARKDOWN)


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await deny_if_not_staff(update):
        return
    data = db.stats()
    text = (
        "إحصاءات\n"
        "────────\n"
        f"الإجمالي: {data['total']}\n"
        f"مقبولون: {data['approved']}\n"
        f"معلقون: {data['pending']}\n"
        f"مرفوضون: {data['rejected']}\n"
        f"محظورون: {data['banned']}\n"
        f"مشرفون: {data['moderators']}\n"
        f"رسائل معاد نشرها: {data['messages']}"
    )
    await safe_reply(update.effective_message, text)


async def _change_status(update: Update, context: ContextTypes.DEFAULT_TYPE, status: str, public_msg: str, private_msg: str) -> None:
    if await deny_if_not_staff(update):
        return
    target = _target_id(context.args)
    if not target:
        await safe_reply(update.effective_message, "حدد المعرف الرقمي للعضو.")
        return
    if target == ADMIN_ID:
        await safe_reply(update.effective_message, "لا يمكن تعديل حالة المدير.")
        return
    record = db.get_user(target)
    if not record:
        await safe_reply(update.effective_message, "العضو غير موجود.")
        return
    updated = db.set_status(target, status)
    await safe_reply(update.effective_message, f"{public_msg}: {display_name(updated)}")
    if status == STATUS_APPROVED:
        await notify_approval(context, target)
        return
    await safe_send_private(context, target, private_msg)


async def cmd_approve(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _change_status(
        update,
        context,
        STATUS_APPROVED,
        "تم قبول",
        "",
    )


async def cmd_reject(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _change_status(
        update,
        context,
        STATUS_REJECTED,
        "تم رفض",
        "تم رفض طلب الانضمام. يمكنك إعادة التسجيل لاحقاً عبر /start.",
    )


async def cmd_ban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await deny_if_not_admin(update):
        return
    await _change_status(
        update,
        context,
        STATUS_BANNED,
        "تم حظر",
        "تم حظرك من المجموعة المستعارة.",
    )


async def cmd_unban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await deny_if_not_admin(update):
        return
    await _change_status(
        update,
        context,
        STATUS_PENDING,
        "تم رفع الحظر وإعادة الطلب إلى الانتظار لـ",
        "تم رفع الحظر. أعد التسجيل عبر /start إن لزم.",
    )


async def cmd_unregister(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await deny_if_not_admin(update):
        return
    target = _target_id(context.args)
    if not target:
        await safe_reply(update.effective_message, "حدد المعرف الرقمي: /unregister 123456")
        return
    if target == ADMIN_ID:
        await safe_reply(update.effective_message, "لا يمكن إلغاء تسجيل المدير.")
        return
    record = db.get_user(target)
    if not record:
        await safe_reply(update.effective_message, "العضو غير موجود.")
        return
    shown = display_name(record)
    if not db.delete_user(target):
        await safe_reply(update.effective_message, "تعذر إلغاء التسجيل.")
        return
    await safe_reply(update.effective_message, f"تم إلغاء تسجيل {shown}. يمكنه إعادة /start.")
    await safe_send_private(context, target, "أُلغي تسجيلك. أعد التسجيل عبر /start إذا رغبت.")


async def cmd_setalias(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await deny_if_not_admin(update):
        return
    args = list(context.args or [])
    target = _target_id(args)
    if not target or len(args) < 2:
        await safe_reply(update.effective_message, "الاستخدام: /setalias 123456 الاسم_الجديد")
        return
    if target == ADMIN_ID:
        await safe_reply(update.effective_message, "لا يمكن تعديل اسم المدير الظاهر.")
        return
    record = db.get_user(target)
    if not record:
        await safe_reply(update.effective_message, "العضو غير موجود.")
        return
    alias = validate_alias(" ".join(args[1:]))
    if not alias:
        await safe_reply(update.effective_message, "الاسم المستعار غير صالح.")
        return
    if db.alias_taken(alias, exclude_user_id=target):
        await safe_reply(update.effective_message, "هذا الاسم المستعار مستخدم.")
        return
    old = record.get("alias") or display_name(record)
    updated = db.set_alias(target, alias)
    shown = display_name(updated)
    await safe_reply(update.effective_message, f"تم تغيير الاسم المستعار من {old} إلى {shown}.")
    await safe_send_private(context, target, f"غيّر المدير اسمك المستعار إلى: {shown}")


async def cmd_setname(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await deny_if_not_admin(update):
        return
    args = list(context.args or [])
    target = _target_id(args)
    if not target or len(args) < 2:
        await safe_reply(update.effective_message, "الاستخدام: /setname 123456 الاسم الحقيقي")
        return
    record = db.get_user(target)
    if not record:
        await safe_reply(update.effective_message, "العضو غير موجود.")
        return
    real_name = validate_real_name(" ".join(args[1:]))
    if not real_name:
        await safe_reply(update.effective_message, "الاسم الحقيقي غير صالح.")
        return
    old = record.get("real_name") or ""
    updated = db.set_real_name(target, real_name)
    await safe_reply(
        update.effective_message,
        f"تم تغيير الاسم الحقيقي من {old} إلى {updated.get('real_name')}.",
    )
    await safe_send_private(context, target, f"غيّر المدير اسمك الحقيقي إلى: {real_name}")


async def cmd_setmod(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await deny_if_not_admin(update):
        return
    target = _target_id(context.args)
    if not target:
        await safe_reply(update.effective_message, "حدد المعرف الرقمي.")
        return
    if target == ADMIN_ID:
        await safe_reply(update.effective_message, "المدير لا يُعيَّن مشرفاً.")
        return
    record = db.get_user(target)
    if not record or record["status"] != STATUS_APPROVED:
        await safe_reply(update.effective_message, "يجب أن يكون العضو مقبولاً أولاً.")
        return
    number = record.get("moderator_number") or db.next_moderator_number()
    updated = db.set_role(target, ROLE_MODERATOR, moderator_number=number, can_reveal=0)
    await safe_reply(update.effective_message, f"تم تعيين {display_name(updated)} مشرفاً.")
    await safe_send_private(context, target, f"تم تعيينك {display_name(updated)}.")


async def cmd_unsetmod(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await deny_if_not_admin(update):
        return
    target = _target_id(context.args)
    if not target:
        await safe_reply(update.effective_message, "حدد المعرف الرقمي.")
        return
    record = db.get_user(target)
    if not record or record["role"] != ROLE_MODERATOR:
        await safe_reply(update.effective_message, "هذا المستخدم ليس مشرفاً.")
        return
    db.set_role(target, ROLE_MEMBER, moderator_number=None, can_reveal=0)
    await safe_reply(update.effective_message, "تم إلغاء الإشراف.")
    await safe_send_private(context, target, "تم إلغاء صلاحية الإشراف.")


async def cmd_allowreveal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await deny_if_not_admin(update):
        return
    target = _target_id(context.args)
    if not target:
        await safe_reply(update.effective_message, "حدد المعرف الرقمي.")
        return
    record = db.get_user(target)
    if not record or record["role"] != ROLE_MODERATOR:
        await safe_reply(update.effective_message, "السماح بالكشف للمشرفين فقط.")
        return
    db.set_can_reveal(target, True)
    await safe_reply(update.effective_message, "تم السماح لهذا المشرف بكشف الهوية.")
    await safe_send_private(context, target, "يمكنك الآن كشف هوية صاحب رسالة بالرد عليها ثم إرسال *")


async def cmd_wipe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await deny_if_not_admin(update):
        return
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("تأكيد المسح", callback_data="wipe:confirm"),
                InlineKeyboardButton("إلغاء", callback_data="wipe:cancel"),
            ]
        ]
    )
    await safe_reply(
        update.effective_message,
        "سيتم مسح كل الأعضاء والرسائل والإعدادات.\n"
        "حساب المدير فقط سيبقى.\n"
        "هذا الإجراء لا يمكن التراجع عنه.",
        reply_markup=keyboard,
    )


async def on_wipe_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.from_user or not query.data:
        return
    actor_id = query.from_user.id
    if actor_id != ADMIN_ID:
        try:
            await query.answer("هذا الأمر للمدير فقط.", show_alert=True)
        except TelegramError:
            pass
        return
    try:
        await query.answer()
    except TelegramError:
        pass
    action = query.data.split(":", 1)[-1]
    if action != "confirm":
        try:
            await query.edit_message_text("تم إلغاء المسح.")
        except TelegramError:
            pass
        return
    try:
        db.reset_all_data(ADMIN_ID)
    except Exception:
        logger.exception("wipe failed")
        try:
            await query.edit_message_text("فشل المسح. حاول لاحقاً.")
        except TelegramError:
            pass
        return
    try:
        await query.edit_message_text("تم مسح كل البيانات وإعادة تهيئة البوت.")
    except TelegramError:
        pass
    await safe_send_private(context, ADMIN_ID, "تم تفريغ قاعدة البيانات. الأعضاء يحتاجون إعادة التسجيل عبر /start.")


async def cmd_denyreveal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await deny_if_not_admin(update):
        return
    target = _target_id(context.args)
    if not target:
        await safe_reply(update.effective_message, "حدد المعرف الرقمي.")
        return
    record = db.get_user(target)
    if not record:
        await safe_reply(update.effective_message, "المستخدم غير موجود.")
        return
    db.set_can_reveal(target, False)
    await safe_reply(update.effective_message, "تم منع كشف الهوية عن هذا المستخدم.")


async def on_approval_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data or not query.from_user:
        return
    try:
        await query.answer()
    except TelegramError:
        pass
    actor = db.get_user(query.from_user.id)
    if not is_staff(actor, ADMIN_ID, query.from_user.id):
        try:
            await query.answer("غير مصرح.", show_alert=True)
        except TelegramError:
            pass
        return
    try:
        action, raw_id = query.data.split(":", 1)
        target_id = int(raw_id)
    except (ValueError, AttributeError):
        return
    if target_id == ADMIN_ID:
        await query.edit_message_text("لا يمكن تعديل المدير.")
        return
    if action == "approve":
        updated = db.set_status(target_id, STATUS_APPROVED)
        await notify_approval(context, target_id)
        label = "قبول"
    else:
        updated = db.set_status(target_id, STATUS_REJECTED)
        await safe_send_private(context, target_id, "تم رفض طلب الانضمام.")
        label = "رفض"
    name = display_name(updated) if updated else str(target_id)
    try:
        await query.edit_message_text(f"تم {label}: {name} (`{target_id}`)")
    except TelegramError:
        pass


def reveal_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("⚡", callback_data="rv")]]
    )


def _is_reveal_command(text: str | None) -> bool:
    if not text:
        return False
    value = text.strip().replace("＊", "*").replace("✱", "*")
    return value in {"*", "⚡"}


def _lookup_mapped_sender(chat_id: int, message_id: int) -> dict | None:
    mapped = db.get_by_relayed(chat_id, message_id)
    if mapped:
        return mapped
    return db.get_by_original(chat_id, message_id)


async def send_identity_private(
    context: ContextTypes.DEFAULT_TYPE,
    actor_id: int,
    sender_id: int,
) -> bool:
    target = db.get_user(sender_id)
    info = format_identity(target, sender_id)
    sent = await safe_send_private(context, actor_id, info, parse_mode=ParseMode.MARKDOWN)
    if not sent:
        sent = await safe_send_private(context, actor_id, info)
    return sent


async def handle_reveal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if not message or not user or not chat:
        return False
    if not _is_reveal_command(message.text):
        return False
    if not is_bound_chat(chat):
        return False

    actor = db.get_user(user.id)
    if user.id == ADMIN_ID:
        db.ensure_admin(ADMIN_ID)
        actor = db.get_user(user.id)

    try:
        await message.delete()
    except TelegramError as exc:
        logger.info("could not delete reveal command: %s", exc)

    if not can_reveal_identity(actor):
        await safe_send_private(context, user.id, "ليست لديك صلاحية كشف الهوية.")
        return True

    reply = message.reply_to_message
    if not reply:
        await safe_send_private(context, user.id, "للكشف: رد على الرسالة ثم أرسل *")
        return True

    mapped = _lookup_mapped_sender(chat.id, reply.message_id)
    if not mapped:
        await safe_send_private(context, user.id, "تعذر تحديد صاحب هذه الرسالة.")
        return True
    await send_identity_private(context, user.id, mapped["sender_id"])
    return True


async def on_reveal_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.from_user:
        return
    actor_id = query.from_user.id
    actor = db.get_user(actor_id)
    if actor_id == ADMIN_ID:
        db.ensure_admin(ADMIN_ID)
        actor = db.get_user(actor_id)

    if not can_reveal_identity(actor):
        try:
            await query.answer("غير مصرح. هذه الأداة للمدير فقط.", show_alert=True)
        except TelegramError:
            pass
        return

    message = query.message
    if message is None or message.chat is None:
        try:
            await query.answer("تعذر تحديد الرسالة.", show_alert=True)
        except TelegramError:
            pass
        return

    mapped = _lookup_mapped_sender(message.chat.id, message.message_id)
    if not mapped:
        try:
            await query.answer("تعذر تحديد صاحب هذه الرسالة.", show_alert=True)
        except TelegramError:
            pass
        return

    sent = await send_identity_private(context, actor_id, mapped["sender_id"])
    try:
        if sent:
            await query.answer("تم إرسال الهوية في الخاص")
        else:
            await query.answer("افتح الخاص مع البوت أولاً وأرسل /start", show_alert=True)
    except TelegramError:
        pass


async def resolve_reply_to(chat_id: int, reply: Message | None) -> int | None:
    if not reply:
        return None
    mapped = db.get_by_original(chat_id, reply.message_id)
    if mapped:
        return mapped["relayed_id"]
    mapped = db.get_by_relayed(chat_id, reply.message_id)
    if mapped:
        return mapped["relayed_id"]
    return reply.message_id


async def delete_original(message: Message) -> None:
    try:
        await message.delete()
    except BadRequest as exc:
        logger.info("delete failed (permissions?): %s", exc)
    except TelegramError as exc:
        logger.warning("delete failed: %s", exc)


RESTRICTED_PERMISSIONS = ChatPermissions(
    can_send_messages=False,
    can_send_audios=False,
    can_send_documents=False,
    can_send_photos=False,
    can_send_videos=False,
    can_send_video_notes=False,
    can_send_voice_notes=False,
    can_send_polls=False,
    can_send_other_messages=False,
    can_add_web_page_previews=False,
)
OPEN_PERMISSIONS = ChatPermissions(
    can_send_messages=False,
    can_send_audios=False,
    can_send_documents=False,
    can_send_photos=False,
    can_send_videos=False,
    can_send_video_notes=False,
    can_send_voice_notes=False,
    can_send_polls=False,
    can_send_other_messages=False,
    can_add_web_page_previews=False,
    can_invite_users=False,
    can_pin_messages=False,
    can_change_info=False,
)
DIRECT_WRITE_PERMISSIONS = ChatPermissions(
    can_send_messages=True,
    can_send_audios=True,
    can_send_documents=True,
    can_send_photos=True,
    can_send_videos=True,
    can_send_video_notes=True,
    can_send_voice_notes=True,
    can_send_polls=True,
    can_send_other_messages=True,
    can_add_web_page_previews=True,
    can_invite_users=False,
    can_pin_messages=False,
    can_change_info=False,
)


def _message_scan_text(message: Message) -> str:
    parts = [message.text or "", message.caption or ""]
    return " ".join(p for p in parts if p).strip()


def _reply_sender_id(chat_id: int, reply: Message | None) -> int | None:
    if not reply:
        return None
    mapped = db.get_by_relayed(chat_id, reply.message_id)
    if mapped:
        return mapped["sender_id"]
    mapped = db.get_by_original(chat_id, reply.message_id)
    if mapped:
        return mapped["sender_id"]
    fwd_chat = getattr(reply, "forward_from_chat", None)
    fwd_mid = getattr(reply, "forward_from_message_id", None)
    if fwd_chat and fwd_mid:
        mapped = db.get_by_relayed(fwd_chat.id, fwd_mid) or db.get_by_original(fwd_chat.id, fwd_mid)
        if mapped:
            return mapped["sender_id"]
    alias = extract_relay_alias(reply.text, reply.caption)
    if alias:
        user = db.find_user_by_shown_name(alias)
        if user:
            return user["user_id"]
    if reply.from_user and not reply.from_user.is_bot:
        return reply.from_user.id
    return None


async def restrict_member(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int,
    seconds: int,
    reason: str = "",
) -> bool:
    until = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    try:
        await context.bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=RESTRICTED_PERMISSIONS,
            until_date=until,
        )
        db.set_mute(user_id, int(until.timestamp()), reason)
        return True
    except TelegramError as exc:
        logger.warning("restrict failed for %s: %s", user_id, exc)
        db.set_mute(user_id, int(until.timestamp()), reason)
        return False


async def apply_member_chat_permissions(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int,
) -> bool:
    if db.is_channel_bound():
        return False
    if user_id == ADMIN_ID:
        return False
    if db.is_muted(user_id):
        perms = RESTRICTED_PERMISSIONS
    elif db.allows_direct_write(user_id):
        perms = DIRECT_WRITE_PERMISSIONS
        until = datetime.now(timezone.utc) - timedelta(seconds=30)
    else:
        perms = OPEN_PERMISSIONS
        until = None
    kwargs = {
        "chat_id": chat_id,
        "user_id": user_id,
        "permissions": perms,
        "use_independent_chat_permissions": True,
    }
    if until is not None:
        kwargs["until_date"] = until
    try:
        await context.bot.restrict_chat_member(**kwargs)
        return True
    except TypeError:
        kwargs.pop("use_independent_chat_permissions", None)
        try:
            await context.bot.restrict_chat_member(**kwargs)
            return True
        except TelegramError as exc:
            logger.warning("apply member permissions failed for %s: %s", user_id, exc)
            return False
    except TelegramError as exc:
        logger.warning("apply member permissions failed for %s: %s", user_id, exc)
        return False


async def sync_member_write_permissions(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int | None = None,
) -> int:
    target = chat_id or db.get_group_chat_id()
    if not target or db.is_channel_bound():
        return 0
    count = 0
    for member in db.list_approved_members():
        uid = int(member["user_id"])
        if uid == ADMIN_ID:
            continue
        if await apply_member_chat_permissions(context, target, uid):
            count += 1
    return count


async def unrestrict_member(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int) -> bool:
    db.clear_mute(user_id)
    return await apply_member_chat_permissions(context, chat_id, user_id)


async def kick_member(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int,
    mark_banned: bool = False,
) -> bool:
    try:
        await context.bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
        await context.bot.unban_chat_member(chat_id=chat_id, user_id=user_id, only_if_banned=True)
        if mark_banned:
            db.set_status(user_id, STATUS_BANNED)
        return True
    except TelegramError as exc:
        logger.warning("kick failed for %s: %s", user_id, exc)
        if mark_banned:
            db.set_status(user_id, STATUS_BANNED)
        return False


async def enforce_security(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    message: Message,
    sender: dict,
) -> bool:
    if is_staff(sender, ADMIN_ID, sender.get("user_id")):
        return False
    text = _message_scan_text(message)
    if not text:
        return False
    members = db.list_approved_members()
    reply_uid = _reply_sender_id(chat_id, message.reply_to_message)
    hit = scan_message(text, sender, members, reply_uid)
    if not hit:
        return False

    await delete_original(message)
    alias = display_name(sender)
    uid = sender["user_id"]

    try:
        if hit.kind == "self":
            count = db.add_violation(uid, "self")
            if count == 1:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=(
                        f"تنبيه لـ {alias}: تم حذف منشورك لأنك أفصحْت عن هويتك الحقيقية.\n"
                        "هذه المرة الأولى. في المرة الثانية تتحمل المسؤولية كاملة."
                    ),
                )
            else:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=(
                        f"{alias} أفصح عن هويته للمرة الثانية.\n"
                        "يتحمل المسؤولية الكاملة عن قراره."
                    ),
                )
            await safe_send_private(context, uid, "تم حذف رسالتك لأنها تتضمن إفصاحاً عن هويتك الحقيقية.")
            return True

        count = db.add_violation(uid, hit.kind)
        await restrict_member(context, chat_id, uid, 60, hit.reason)
        if count == 1:
            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    f"تحذير أول وأخير لـ {alias}.\n"
                    f"السبب: {hit.reason}.\n"
                    f"الرسالة: {hit.redacted}\n"
                    "تم كتمك دقيقة واحدة. المخالفة التالية تؤدي إلى الطرد النهائي."
                ),
            )
            await safe_send_private(
                context,
                uid,
                "تم حذف رسالتك وكتمك دقيقة واحدة لمحاولة كشف هوية. هذا التحذير الأول والأخير.",
            )
        else:
            await kick_member(context, chat_id, uid, mark_banned=True)
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"تم طرد {alias} نهائياً بعد تكرار محاولة كشف الهوية.",
            )
            await safe_send_private(context, uid, f"تم طردك من {bound_kind_label()} لتكرار محاولة كشف الهوية.")
        return True
    except TelegramError as exc:
        logger.warning("security notice failed: %s", exc)
        return True


async def handle_power_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    message = update.effective_message
    user = update.effective_user
    if not message or not user or not message.text:
        return False
    action = parse_power_command(message.text)
    if not action:
        return False
    actor = db.get_user(user.id)
    if not is_admin(actor, ADMIN_ID, user.id):
        if is_bound_chat(update.effective_chat):
            await delete_original(message)
        await safe_send_private(context, user.id, "Pause and resume are admin-only.")
        return True
    paused = action == "pause"
    text = await apply_pause(context, paused)
    await safe_reply(message, text, reply_markup=pause_keyboard())
    if is_bound_chat(update.effective_chat):
        try:
            await message.delete()
        except TelegramError:
            pass
    return True


async def _apply_moderation(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    action: str,
    seconds: int,
) -> bool:
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if not message or not user or not chat:
        return False

    actor = db.get_user(user.id)
    if user.id == ADMIN_ID:
        db.ensure_admin(ADMIN_ID)
        actor = db.get_user(user.id)
    if not is_staff(actor, ADMIN_ID, user.id):
        if is_bound_chat(chat):
            await delete_original(message)
        await safe_send_private(context, user.id, "أوامر الكتم للمدير والمشرفين فقط.")
        return True

    bound_id = db.get_group_chat_id()
    lookup_chat_id = chat.id if is_bound_chat(chat) else bound_id
    if chat.type == ChatType.PRIVATE:
        lookup_chat_id = bound_id
    if not lookup_chat_id:
        await safe_reply(message, "اربط المجموعة أو القناة أولاً عبر /setgroup أو /setchannel")
        return True

    reply = message.reply_to_message
    if not reply:
        await safe_reply(message, "رد على رسالة البوت ثم أرسل /mute أو /unmute")
        return True
    target_id = _reply_sender_id(lookup_chat_id, reply)
    if not target_id:
        await safe_reply(message, "تعذر تحديد صاحب الرسالة المعاد نشرها.")
        return True
    if target_id == ADMIN_ID:
        await safe_reply(message, "لا يمكن كتم المدير.")
        return True
    target = db.get_user(target_id)
    alias = display_name(target) if target else str(target_id)

    if action == "unmute":
        await unrestrict_member(context, lookup_chat_id, target_id)
        if is_bound_chat(chat) and chat.type != ChatType.CHANNEL:
            await delete_original(message)
            await context.bot.send_message(chat_id=lookup_chat_id, text=f"تم إلغاء كتم {alias}.")
        else:
            await safe_reply(message, f"تم إلغاء كتم {alias}.")
        await safe_send_private(context, target_id, "تم إلغاء الكتم. يمكنك الكتابة مجدداً.")
        return True

    await restrict_member(context, lookup_chat_id, target_id, seconds, "كتم إداري")
    if is_bound_chat(chat) and chat.type != ChatType.CHANNEL:
        await delete_original(message)
        await context.bot.send_message(
            chat_id=lookup_chat_id,
            text=f"تم كتم {alias} لمدة {format_duration(seconds)}.",
        )
    else:
        await safe_reply(message, f"تم كتم {alias} لمدة {format_duration(seconds)}.")
    await safe_send_private(context, target_id, f"تم كتمك لمدة {format_duration(seconds)}.")
    return True


async def handle_moderation_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    message = update.effective_message
    if not message or not message.text:
        return False
    parsed = parse_moderation_command(message.text)
    if not parsed:
        return False
    action, seconds = parsed
    return await _apply_moderation(update, context, action, seconds)


async def relay_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        await _relay_message(update, context)
    except Exception:
        logger.exception("relay_message crashed")


async def try_bind_channel_by_token(message: Message, chat, context: ContextTypes.DEFAULT_TYPE) -> bool:
    token = extract_channel_bind_token(message.text or message.caption)
    expected = (db.get_setting("channel_bind_token") or "").upper()
    if not token or not expected or token != expected:
        return False
    db.set_setting("channel_bind_token", "")
    bound = db.get_group_chat_id()
    if bound and bound != chat.id:
        return True
    await bind_chat(context, chat.id, ChatType.CHANNEL)
    try:
        await message.delete()
    except TelegramError:
        pass
    actor = getattr(message, "from_user", None)
    actor_id = actor.id if actor else ADMIN_ID
    await safe_send_private(
        context,
        actor_id,
        f"تم ربط القناة عبر رمز الربط. المعرف: {chat.id}",
        reply_markup=pause_keyboard(),
    )
    return True


async def _relay_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if not message or not chat:
        return
    if chat.type == ChatType.CHANNEL:
        if await try_bind_channel_by_token(message, chat, context):
            return
        if not user:
            return
    if not user:
        return
    if not is_bound_chat(chat):
        return
    if message.from_user and message.from_user.is_bot:
        return
    bound = db.get_group_chat_id()
    if bound and bound != chat.id:
        return
    if not bound:
        db.set_bound_chat(chat.id, chat.type)

    if await handle_moderation_command(update, context):
        return

    if await handle_reveal(update, context):
        return

    if await handle_power_command(update, context):
        return

    if chat.type == ChatType.CHANNEL:
        return

    record = db.get_user(user.id)
    if user.id == ADMIN_ID:
        db.ensure_admin(ADMIN_ID)
        record = db.get_user(user.id)
    if record and record.get("status") == STATUS_APPROVED and record.get("direct_write"):
        await republish_group_message(update, context, record)
        return

    await delete_original(message)
    await safe_send_private(
        context,
        user.id,
        "لا تكتب داخل المجموعة حتى لا يظهر اسمك في إشعار «يكتب».\n"
        "أرسل رسالتك هنا في الخاص لتظهر بالاسم المستعار.\n"
        "إذا أردت الكتابة داخل المجموعة على مسؤوليتك أرسل /ingroup.",
    )


async def republish_group_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    record: dict,
) -> None:
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if not message or not user or not chat:
        return
    if db.is_paused():
        return
    if db.is_muted(user.id) and not is_staff(record, ADMIN_ID, user.id):
        await delete_original(message)
        await safe_send_private(context, user.id, "أنت مكتوم حالياً ولا يمكنك الكتابة.")
        return
    try:
        if await enforce_security(context, chat.id, message, record):
            return
    except Exception:
        logger.exception("security enforcement failed")
    reply_to = None
    if message.reply_to_message:
        mapped = db.get_by_original(chat.id, message.reply_to_message.message_id)
        if mapped:
            reply_to = mapped["relayed_id"]
        else:
            mapped = db.get_by_relayed(chat.id, message.reply_to_message.message_id)
            if mapped:
                reply_to = mapped["relayed_id"]
    alias = display_name(record)
    original_id = message.message_id
    await delete_original(message)
    try:
        sent = await _copy_as_alias(context, chat.id, message, alias, reply_to)
    except TelegramError as exc:
        logger.exception("group republish failed: %s", exc)
        await safe_send_private(context, user.id, "تعذر إعادة نشر الرسالة. حاول من الخاص.")
        return
    if sent:
        try:
            db.save_message(chat.id, original_id, sent.message_id, user.id)
        except Exception:
            logger.exception("failed to store message map")


async def publish_from_private(
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    record: dict,
    message: Message,
) -> Message | None:
    chat_id = db.get_group_chat_id()
    if not chat_id:
        await safe_reply(message, "المجموعة أو القناة غير مربوطة بعد. ينتظر المدير /setgroup أو /setchannel.")
        return None
    if db.is_paused():
        await safe_reply(message, "البوت متوقف مؤقتاً. انتظر استئناف المدير.")
        return None
    if db.is_muted(user_id) and not is_staff(record, ADMIN_ID, user_id):
        await safe_reply(message, "أنت مكتوم حالياً ولا يمكنك الكتابة.")
        return None
    try:
        if await enforce_security(context, chat_id, message, record):
            return None
    except Exception:
        logger.exception("security enforcement failed")
    alias = display_name(record)
    try:
        sent = await _copy_as_alias(context, chat_id, message, alias, None)
    except TelegramError as exc:
        logger.exception("private publish failed: %s", exc)
        await safe_reply(message, "تعذر نشر الرسالة. حاول لاحقاً.")
        return None
    if sent:
        try:
            db.save_message(chat_id, message.message_id, sent.message_id, user_id)
        except Exception:
            logger.exception("failed to store message map")
        await safe_reply(message, f"تم نشر رسالتك في {bound_kind_label()} بالاسم المستعار.")
    return sent


async def on_private_post(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if not message or not user or not chat or chat.type != ChatType.PRIVATE:
        return
    if message.from_user and message.from_user.is_bot:
        return
    if user.id == ADMIN_ID:
        db.ensure_admin(ADMIN_ID)
        if await _bind_channel_from_private(update, context):
            return
    record = db.get_user(user.id)
    if user.id == ADMIN_ID:
        db.ensure_admin(ADMIN_ID)
        record = db.get_user(user.id)
    if not record or record["status"] != STATUS_APPROVED:
        if not record:
            await safe_reply(message, "سجّل أولاً عبر /start.")
        elif record["status"] == STATUS_PENDING:
            await safe_reply(message, "طلبك قيد المراجعة. انتظر موافقة المدير.")
        elif record["status"] == STATUS_BANNED:
            await safe_reply(message, "حسابك محظور.")
        else:
            await safe_reply(message, "حسابك غير مقبول. أعد التسجيل عبر /start.")
        return
    await publish_from_private(context, user.id, record, message)


async def _copy_as_alias(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    message: Message,
    alias: str,
    reply_to: int | None,
) -> Message | None:
    kwargs: dict[str, Any] = {"reply_markup": reveal_keyboard()}
    if reply_to:
        kwargs["reply_to_message_id"] = reply_to
        kwargs["allow_sending_without_reply"] = True

    if message.text:
        return await context.bot.send_message(
            chat_id=chat_id,
            text=build_text(alias, message.text),
            **kwargs,
        )
    caption = build_caption(alias, message.caption)
    if message.photo:
        return await context.bot.send_photo(
            chat_id=chat_id,
            photo=message.photo[-1].file_id,
            caption=caption,
            **kwargs,
        )
    if message.video:
        return await context.bot.send_video(
            chat_id=chat_id,
            video=message.video.file_id,
            caption=caption,
            **kwargs,
        )
    if message.document:
        return await context.bot.send_document(
            chat_id=chat_id,
            document=message.document.file_id,
            caption=caption,
            **kwargs,
        )
    if message.audio:
        return await context.bot.send_audio(
            chat_id=chat_id,
            audio=message.audio.file_id,
            caption=caption,
            **kwargs,
        )
    if message.voice:
        return await context.bot.send_voice(
            chat_id=chat_id,
            voice=message.voice.file_id,
            caption=caption,
            **kwargs,
        )
    if message.video_note:
        note = await context.bot.send_video_note(
            chat_id=chat_id,
            video_note=message.video_note.file_id,
            **kwargs,
        )
        await context.bot.send_message(
            chat_id=chat_id,
            text=build_text(alias, ""),
            reply_to_message_id=note.message_id,
            allow_sending_without_reply=True,
            reply_markup=reveal_keyboard(),
        )
        return note
    if message.sticker:
        sticker = await context.bot.send_sticker(
            chat_id=chat_id,
            sticker=message.sticker.file_id,
            **kwargs,
        )
        await context.bot.send_message(
            chat_id=chat_id,
            text=build_text(alias, ""),
            reply_to_message_id=sticker.message_id,
            allow_sending_without_reply=True,
            reply_markup=reveal_keyboard(),
        )
        return sticker
    if message.animation:
        return await context.bot.send_animation(
            chat_id=chat_id,
            animation=message.animation.file_id,
            caption=caption,
            **kwargs,
        )
    if message.location:
        loc = await context.bot.send_location(
            chat_id=chat_id,
            latitude=message.location.latitude,
            longitude=message.location.longitude,
            **kwargs,
        )
        await context.bot.send_message(
            chat_id=chat_id,
            text=build_text(alias, "موقع"),
            reply_to_message_id=loc.message_id,
            allow_sending_without_reply=True,
            reply_markup=reveal_keyboard(),
        )
        return loc
    return await context.bot.send_message(
        chat_id=chat_id,
        text=build_text(alias, message.caption or message.text or ""),
        **kwargs,
    )


async def on_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    chat = update.effective_chat
    if not message or not chat:
        return
    bound = db.get_group_chat_id()
    if bound and bound != chat.id:
        return
    if not bound:
        db.set_bound_chat(chat.id, chat.type)
    for member in message.new_chat_members:
        if member.is_bot:
            continue
        if member.id == ADMIN_ID:
            continue
        record = db.get_user(member.id)
        if record and record["status"] == STATUS_APPROVED:
            await apply_member_chat_permissions(context, chat.id, member.id)
            continue
        await kick_member(context, chat.id, member.id)
        await safe_send_private(
            context,
            member.id,
            f"{bound_kind_label()} مغلقة. سجّل عبر /start في الخاص، وبعد موافقة المدير يصلك رابط الدخول.",
        )
    try:
        await message.delete()
    except TelegramError:
        pass


async def on_join_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    request = update.chat_join_request
    if not request or not request.from_user:
        return
    user_id = request.from_user.id
    chat_id = request.chat.id
    bound = db.get_group_chat_id()
    if bound and bound != chat_id:
        return
    if not bound:
        db.set_bound_chat(chat_id, request.chat.type)
    record = db.get_user(user_id)
    if user_id == ADMIN_ID or (record and record["status"] == STATUS_APPROVED):
        try:
            await request.approve()
        except TelegramError as exc:
            logger.warning("approve join request failed: %s", exc)
        if record and record["status"] == STATUS_APPROVED:
            await apply_member_chat_permissions(context, chat_id, user_id)
        return
    try:
        await request.decline()
    except TelegramError as exc:
        logger.warning("decline join request failed: %s", exc)
    await safe_send_private(
        context,
        user_id,
        "لا يمكن الدخول مباشرة. سجّل عبر /start في الخاص، وبعد موافقة المدير يصلك رابط الدخول.",
    )


async def on_my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    event = update.my_chat_member
    if not event or not event.chat:
        return
    chat = event.chat
    if not is_bound_chat(chat):
        return
    new_status = event.new_chat_member.status if event.new_chat_member else ""
    if new_status not in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.MEMBER):
        return
    bound = db.get_group_chat_id()
    if bound and bound != chat.id:
        return
    first_bind = not bound
    if first_bind:
        db.set_bound_chat(chat.id, chat.type)
    if new_status == ChatMemberStatus.ADMINISTRATOR:
        try:
            await lock_group_access(context, chat.id)
        except TelegramError as exc:
            logger.warning("auto-lock after bot join failed: %s", exc)
    if first_bind:
        actor_id = event.from_user.id if event.from_user else ADMIN_ID
        label = "القناة" if chat.type == ChatType.CHANNEL else "المجموعة"
        await safe_send_private(
            context,
            actor_id,
            f"تم ربط {label} تلقائياً. المعرف: {chat.id}\n"
            "إذا لم تُقفل الصلاحيات أرسل /setgroup داخلها أو /setchannel من الخاص.",
        )
        if chat.type != ChatType.CHANNEL:
            await notify_existing_members(context, chat.id)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("exception while handling update", exc_info=context.error)
    detail = "".join(traceback.format_exception(None, context.error, context.error.__traceback__)) if context.error else ""
    logger.debug(detail[-2000:])
    if isinstance(update, Update) and update.effective_user:
        try:
            await notify_admin(
                context,
                f"خطأ غير متوقع: {html.escape(str(context.error))[:500]}",
            )
        except Exception:
            logger.exception("failed to notify admin of error")


def auto_purge_enabled() -> bool:
    stored = db.get_setting("auto_purge_enabled")
    if stored is not None and stored != "":
        return stored.lower() in ("1", "true", "yes", "on")
    return bool(config.AUTO_PURGE_ENABLED)


def auto_purge_hours() -> int:
    stored = db.get_setting("auto_purge_hours")
    if stored and str(stored).isdigit():
        return max(1, int(stored))
    try:
        return max(1, int(config.AUTO_PURGE_HOURS or 24))
    except (TypeError, ValueError):
        return 24


async def run_scheduled_purge(context: ContextTypes.DEFAULT_TYPE) -> tuple[int, int]:
    if not auto_purge_enabled():
        logger.info("auto purge skipped: disabled")
        return 0, 0
    if not db.get_group_chat_id():
        logger.info("auto purge skipped: no bound chat")
        return 0, 0
    deleted, failed = await purge_group_messages(context)
    now = datetime.now(timezone.utc).isoformat()
    db.set_setting("last_auto_purge", now)
    logger.info("auto purge finished deleted=%s failed=%s", deleted, failed)
    await notify_admin(
        context,
        f"تم الحذف التلقائي للمحادثات.\nالمحذوف: {deleted}\nتعذر: {failed}\nالوقت: {now}",
    )
    await announce_group(context, "تم تفريغ المحادثات تلقائياً حسب جدولة الـ 24 ساعة.")
    return deleted, failed


async def post_init(application: Application) -> None:
    try:
        await application.bot.set_my_commands(MEMBER_COMMANDS)
        await application.bot.set_my_commands(
            ADMIN_COMMANDS,
            scope=BotCommandScopeChat(chat_id=ADMIN_ID),
        )
    except TelegramError as exc:
        logger.warning("failed to register bot commands: %s", exc)
    hours = auto_purge_hours()
    jq = getattr(application, "job_queue", None)
    if jq is not None:
        jq.run_repeating(
            run_scheduled_purge,
            interval=timedelta(hours=hours),
            first=timedelta(hours=hours),
            name="auto_purge",
        )
        logger.info("auto purge scheduled every %s hours via job queue", hours)
        return
    asyncio.create_task(auto_purge_loop(application))
    logger.info("auto purge scheduled every %s hours via asyncio", hours)


async def auto_purge_loop(application: Application) -> None:
    while True:
        await asyncio.sleep(max(3600, auto_purge_hours() * 3600))
        class _Ctx:
            bot = application.bot
        try:
            await run_scheduled_purge(_Ctx())
        except Exception:
            logger.exception("scheduled purge failed")


def build_application() -> Application:
    db.init_db()
    db.ensure_admin(ADMIN_ID)
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", cmd_start)],
        states={
            WAITING_REAL_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, recv_real_name)
            ],
            WAITING_ALIAS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, recv_alias)
            ],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
        name="register",
        persistent=False,
        allow_reentry=True,
    )
    app.add_handler(conv)
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("rules", cmd_rules))
    app.add_handler(CommandHandler("setrules", cmd_setrules))
    app.add_handler(CommandHandler("myinfo", cmd_myinfo))
    app.add_handler(CommandHandler("ingroup", cmd_ingroup))
    app.add_handler(CommandHandler("outgroup", cmd_outgroup))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CommandHandler("setgroup", cmd_setgroup))
    app.add_handler(CommandHandler("setchannel", cmd_setchannel))
    app.add_handler(CommandHandler("invite", cmd_invite))
    app.add_handler(CommandHandler("purge", cmd_purge))
    app.add_handler(CommandHandler("lockgroup", cmd_lockgroup))
    app.add_handler(CommandHandler("pending", cmd_pending))
    app.add_handler(CommandHandler("members", cmd_members))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("approve", cmd_approve))
    app.add_handler(CommandHandler("reject", cmd_reject))
    app.add_handler(CommandHandler("ban", cmd_ban))
    app.add_handler(CommandHandler("unban", cmd_unban))
    app.add_handler(CommandHandler("unregister", cmd_unregister))
    app.add_handler(CommandHandler("setalias", cmd_setalias))
    app.add_handler(CommandHandler("setname", cmd_setname))
    app.add_handler(CommandHandler("setmod", cmd_setmod))
    app.add_handler(CommandHandler("unsetmod", cmd_unsetmod))
    app.add_handler(CommandHandler("allowreveal", cmd_allowreveal))
    app.add_handler(CommandHandler("denyreveal", cmd_denyreveal))
    app.add_handler(CommandHandler("wipe", cmd_wipe))
    app.add_handler(CommandHandler("pause", cmd_pause))
    app.add_handler(CommandHandler("resume", cmd_resume))
    app.add_handler(CommandHandler("control", cmd_control))
    app.add_handler(CommandHandler("restart", cmd_restart))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("whois", cmd_whois))
    app.add_handler(CommandHandler("announce", cmd_announce))
    app.add_handler(CommandHandler("mute", cmd_mute))
    app.add_handler(CommandHandler("unmute", cmd_unmute))
    app.add_handler(CallbackQueryHandler(on_approval_callback, pattern=r"^(approve|reject):\d+$"))
    app.add_handler(CallbackQueryHandler(on_reveal_callback, pattern=r"^rv$"))
    app.add_handler(CallbackQueryHandler(on_wipe_callback, pattern=r"^wipe:(confirm|cancel)$"))
    app.add_handler(CallbackQueryHandler(on_direct_write_callback, pattern=r"^dw:(on|cancel)$"))
    app.add_handler(
        CallbackQueryHandler(
            on_bot_control_callback,
            pattern=r"^bot:(pause|resume|status|restart|stop|purge|lock)(:confirm)?$",
        )
    )
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_new_member))
    app.add_handler(ChatJoinRequestHandler(on_join_request))
    app.add_handler(ChatMemberHandler(on_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(
        MessageHandler(
            filters.ChatType.CHANNEL
            & ~filters.COMMAND
            & ~filters.StatusUpdate.ALL
            & ~filters.UpdateType.EDITED_CHANNEL_POST,
            relay_message,
        )
    )
    app.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE
            & ~filters.COMMAND
            & ~filters.StatusUpdate.ALL
            & ~filters.UpdateType.EDITED_MESSAGE,
            on_private_post,
        )
    )
    app.add_handler(
        MessageHandler(
            filters.ChatType.GROUPS
            & ~filters.StatusUpdate.ALL
            & ~filters.UpdateType.EDITED_MESSAGE,
            relay_message,
        )
    )
    app.add_error_handler(error_handler)
    return app


def restart_process() -> None:
    python = sys.executable or "python3"
    os.execv(python, [python, *sys.argv])


def main() -> None:
    global _SHUTDOWN_ACTION
    if not BOT_TOKEN:
        raise SystemExit("BOT_TOKEN is missing")
    application = build_application()
    logger.info("bot started as alias group manager")
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
        close_loop=False,
    )
    if _SHUTDOWN_ACTION == "restart":
        logger.info("restarting process")
        restart_process()
    logger.info("bot stopped")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("stopped by user")
    except Exception:
        logger.exception("fatal error")
        raise
