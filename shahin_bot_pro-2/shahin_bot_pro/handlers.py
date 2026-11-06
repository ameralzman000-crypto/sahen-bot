import logging
from datetime import datetime, timezone
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatType
from telegram.ext import ContextTypes
from config import settings
import database as db
from settings_store import bind_group, unbind_group

log = logging.getLogger(__name__)
USER_MENU = InlineKeyboardMarkup([
    [InlineKeyboardButton("تسجيل / إعادة تقديم", callback_data="register")],
    [InlineKeyboardButton("حالة طلبي", callback_data="status")],
    [InlineKeyboardButton("القوانين", callback_data="rules")],
    [InlineKeyboardButton("الدعم الفني", callback_data="support")],
])
ADMIN_MENU = InlineKeyboardMarkup([
    [InlineKeyboardButton("الإحصائيات", callback_data="adm:stats"),
     InlineKeyboardButton("الطلبات المعلقة", callback_data="adm:pending")],
    [InlineKeyboardButton("آخر الأعضاء", callback_data="adm:users"),
     InlineKeyboardButton("سجل النشاط", callback_data="adm:audit")],
    [InlineKeyboardButton("البحث عن عضو", callback_data="adm:search")],
])
RULES = (
    "قوانين مجموعة عين الشاهين\n"
    "1. الاحترام المتبادل.\n"
    "2. يمنع نشر الروابط دون إذن.\n"
    "3. استخدم الاسم المستعار عند النشر عبر البوت.\n"
    "4. يمنع انتحال الهوية أو إساءة استخدام النظام."
)


def is_admin(user_id):
    return user_id in settings.admin_ids


def admin_kb_for_user(user_id):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("قبول", callback_data=f"decision:approved:{user_id}"),
        InlineKeyboardButton("رفض", callback_data=f"decision:rejected:{user_id}")
    ], [
        InlineKeyboardButton("إيقاف", callback_data=f"decision:suspended:{user_id}")
    ]])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    if update.effective_chat.type != ChatType.PRIVATE:
        return
    if is_admin(u.id):
        linked = (
            f"المجموعة المربوطة: {settings.group_title or 'بدون اسم'}\nالآيدي: {settings.group_id}"
            if settings.group_id else
            "لا توجد مجموعة مربوطة بعد.\nأسهل طريقة: أضف البوت مشرفاً في المجموعة ثم اكتب /link داخلها، أو أعد توجيه أي رسالة من المجموعة إلى البوت هنا."
        )
        await update.message.reply_text(
            "أهلاً بك في لوحة إدارة بوت الشاهين.\n" + linked,
            reply_markup=ADMIN_MENU,
        )
    else:
        await update.message.reply_text(
            f"أهلاً {u.first_name} بك في نظام عين الشاهين.\nاختر الخدمة المطلوبة:",
            reply_markup=USER_MENU,
        )


async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.effective_message.reply_text(
        "القائمة الرئيسية:",
        reply_markup=ADMIN_MENU if is_admin(update.effective_user.id) else USER_MENU,
    )


async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await update.effective_message.reply_text("لوحة الإدارة:", reply_markup=ADMIN_MENU)


async def webapp_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await update.effective_message.reply_text(
        f"لوحة الويب تعمل على المنفذ: {settings.web_port}\n"
        "افتح اللوحة من رابط المعاينة. غيّر التوكن والمجموعة والكتم من هناك."
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid, data = q.from_user.id, q.data
    if data.startswith("adm:"):
        if not is_admin(uid):
            await q.answer("غير مصرح لك.", show_alert=True)
            return
        action = data.split(":", 1)[1]
        if action == "stats":
            c = db.counts()
            msg = (
                f"إحصائيات شاهين\nالمجموع: {c['total']}\nمقبول: {c['approved']}\n"
                f"معلق: {c['pending']}\nمرفوض: {c['rejected']}\nموقوف: {c['suspended']}\n"
                f"مكتوم: {c['muted']}\nتذاكر مفتوحة: {c['tickets']}"
            )
            await q.message.reply_text(msg, reply_markup=ADMIN_MENU)
        elif action == "pending":
            rows = db.list_users("pending", 30)
            if not rows:
                await q.message.reply_text("لا توجد طلبات معلقة حالياً.", reply_markup=ADMIN_MENU)
            else:
                for row in rows:
                    await q.message.reply_text(
                        f"طلب #{row['user_id']}\nالاسم: {row['real_name']}\n"
                        f"المستعار: {row['alias']}\nحساب تيليغرام: {row['telegram_name']}",
                        reply_markup=admin_kb_for_user(row["user_id"]),
                    )
        elif action == "users":
            rows = db.list_users(limit=20)
            text = "آخر الأعضاء:\n" + (
                "\n".join(
                    f"{r['alias'] or '—'} | {r['status']} | {'مكتوم' if r.get('muted') else 'مسموح'} | {r['user_id']}"
                    for r in rows
                ) if rows else "لا يوجد أعضاء."
            )
            await q.message.reply_text(text, reply_markup=ADMIN_MENU)
        elif action == "audit":
            rows = db.recent_audit(15)
            text = "آخر النشاطات:\n" + (
                "\n".join(f"{r['created_at']} | {r['action']} | الهدف {r['target_id']}" for r in rows)
                if rows else "لا يوجد نشاط مسجل."
            )
            await q.message.reply_text(text, reply_markup=ADMIN_MENU)
        elif action == "search":
            context.user_data["awaiting_search"] = True
            await q.message.reply_text("أرسل جزءاً من الاسم أو الاسم المستعار أو آيدي العضو.")
        return

    if data == "register":
        row = db.get_user(uid)
        if row and row["status"] == "approved":
            await q.message.reply_text(f"أنت مقبول مسبقاً. اسمك المستعار: {row['alias']}", reply_markup=USER_MENU)
            return
        if row and row.get("reject_until"):
            try:
                until = datetime.fromisoformat(row["reject_until"])
                if until > datetime.now(timezone.utc):
                    seconds = int((until - datetime.now(timezone.utc)).total_seconds())
                    await q.message.reply_text(
                        f"تم رفض طلبك. أعد المحاولة بعد {seconds // 60} دقيقة و{seconds % 60} ثانية.",
                        reply_markup=USER_MENU,
                    )
                    return
            except ValueError:
                pass
        context.user_data["awaiting_real_name"] = True
        await q.message.reply_text("اكتب اسمك الحقيقي برسالة واحدة. لا ترسل معلومات حساسة إضافية.")
    elif data == "status":
        row = db.get_user(uid)
        if not row:
            msg = "لم تقدّم طلباً بعد."
        else:
            mute = "مكتوم" if row.get("muted") else "مسموح بالحديث"
            msg = f"حالة الطلب: {row['status']}\nالاسم المستعار: {row['alias'] or 'لم يُحدد'}\nالحديث: {mute}"
        await q.message.reply_text(msg, reply_markup=USER_MENU)
    elif data == "rules":
        await q.message.reply_text(RULES, reply_markup=USER_MENU)
    elif data == "support":
        context.user_data["awaiting_support"] = True
        await q.message.reply_text("اكتب رسالتك للدعم الفني. أرسل /menu للخروج.")


async def registration_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != ChatType.PRIVATE or is_admin(update.effective_user.id):
        return
    if not context.user_data.get("awaiting_real_name"):
        return
    text = (update.message.text or "").strip()
    if len(text) < settings.auto_approve_min_name or len(text) > 80:
        await update.message.reply_text("الاسم قصير جداً أو طويل. أرسل اسماً بين 3 و80 حرفاً.")
        return
    context.user_data["awaiting_real_name"] = False
    u = update.effective_user
    old = db.get_user(u.id)
    alias = old["alias"] if old and old.get("alias") else db.unique_alias()
    if settings.auto_approve:
        db.upsert_pending(u.id, u.full_name, text, alias)
        db.set_status(u.id, "approved", 0, "auto approval enabled")
        status = "تم قبول طلبك تلقائياً وفق إعدادات النظام."
    else:
        db.upsert_pending(u.id, u.full_name, text, alias)
        status = "تم استلام طلبك، وهو الآن قيد مراجعة الإدارة."
    row = db.get_user(u.id)
    await update.message.reply_text(f"اسمك المستعار: {row['alias']}\n{status}", reply_markup=USER_MENU)
    if settings.auto_approve:
        await _send_invite(context, u.id)
    if not settings.auto_approve:
        for admin_id in settings.admin_ids:
            try:
                await context.bot.send_message(
                    admin_id,
                    f"طلب انضمام جديد\nالاسم: {text}\nالمستعار: {row['alias']}\nآيدي تيليغرام: {u.id}",
                    reply_markup=admin_kb_for_user(u.id),
                )
            except Exception:
                log.exception("Failed notifying admin %s", admin_id)


async def support_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != ChatType.PRIVATE or is_admin(update.effective_user.id):
        return
    if not context.user_data.get("awaiting_support"):
        return
    text = (update.message.text or "").strip()
    if not text:
        return
    u = update.effective_user
    row = db.get_user(u.id)
    if not row:
        db.upsert_pending(u.id, u.full_name, u.full_name, db.unique_alias())
    ticket_id = db.add_ticket(u.id, text)
    for admin_id in settings.admin_ids:
        try:
            await context.bot.send_message(
                admin_id,
                f"تذكرة دعم #{ticket_id}\nالمستخدم: {u.full_name}\n"
                f"الاسم المستعار: {(db.get_user(u.id) or {}).get('alias')}\nآيدي: {u.id}\n\n{text}\n\n"
                f"للرد استخدم: /reply {u.id} نص الرد",
            )
        except Exception:
            log.exception("Failed forwarding support ticket")
    await update.message.reply_text(f"وصلت رسالتك للدعم برقم #{ticket_id}.", reply_markup=USER_MENU)
    context.user_data["awaiting_support"] = False


def _chat_meta(chat):
    username = getattr(chat, "username", None) or ""
    return {
        "id": chat.id,
        "title": chat.title or chat.full_name or str(chat.id),
        "username": username,
        "link": f"https://t.me/{username}" if username else "",
    }


async def remember_group_chat(chat, status="seen"):
    chat_type = str(getattr(chat, "type", "") or "")
    if not chat or chat_type not in (ChatType.GROUP, ChatType.SUPERGROUP, "group", "supergroup"):
        return None
    meta = _chat_meta(chat)
    db.upsert_known_group(meta["id"], meta["title"], meta["username"], status)
    return meta


async def notify_admins(context, text):
    for admin_id in settings.admin_ids:
        try:
            await context.bot.send_message(admin_id, text)
        except Exception:
            log.exception("Failed notifying admin %s", admin_id)


async def my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if not chat or chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return
    meta = await remember_group_chat(chat, "seen")
    member = update.my_chat_member
    new_status = member.new_chat_member.status if member else ""
    old_status = member.old_chat_member.status if member else ""
    if new_status in ("administrator", "creator"):
        bound = bind_group(meta["id"], meta["title"], meta["username"], meta["link"], actor_id=update.effective_user.id if update.effective_user else 0)
        await notify_admins(
            context,
            f"تم ربط المجموعة تلقائياً لأن البوت أصبح مشرفاً.\nالاسم: {bound['title']}\nالآيدي: {bound['id']}\n"
            "يمكنك تغيير الربط لاحقاً من اللوحة أو بأمر /unlink",
        )
        try:
            await context.bot.send_message(chat.id, "تم ربط هذه المجموعة ببوت الشاهين. للنشر استخدم الرسائل الخاصة مع البوت.")
        except Exception:
            pass
    elif old_status in ("administrator", "member", "restricted") and new_status in ("left", "kicked"):
        if settings.group_id == chat.id:
            unbind_group(update.effective_user.id if update.effective_user else 0)
            await notify_admins(context, f"أُزيل البوت من المجموعة {meta['title']} وتم إلغاء الربط.")


async def group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if not chat or chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return
    await remember_group_chat(chat, "seen")


async def link_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    chat = update.effective_chat
    if chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
        meta = await remember_group_chat(chat, "linked")
        bound = bind_group(meta["id"], meta["title"], meta["username"], meta["link"], actor_id=update.effective_user.id)
        await update.message.reply_text(f"تم ربط هذه المجموعة.\nالاسم: {bound['title']}\nالآيدي: {bound['id']}")
        return
    await update.message.reply_text(
        "لربط المجموعة بدون نسخ الآيدي استخدم إحدى الطرق:\n"
        "1) أضف البوت مشرفاً في المجموعة.\n"
        "2) اكتب /link داخل المجموعة.\n"
        "3) أعد توجيه أي رسالة من المجموعة إلى البوت هنا في الخاص."
    )


async def unlink_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not settings.group_id:
        await update.message.reply_text("لا توجد مجموعة مربوطة حالياً.")
        return
    unbind_group(update.effective_user.id)
    await update.message.reply_text("تم إلغاء ربط المجموعة.")


def extract_forwarded_chat(message):
    if not message:
        return None
    chat = getattr(message, "forward_from_chat", None)
    if chat:
        return chat
    origin = getattr(message, "forward_origin", None)
    return getattr(origin, "chat", None) if origin else None


async def general_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != ChatType.PRIVATE:
        return
    u = update.effective_user
    if is_admin(u.id):
        forwarded_chat = extract_forwarded_chat(update.message)
        if forwarded_chat and getattr(forwarded_chat, "type", None) in (ChatType.GROUP, ChatType.SUPERGROUP, "group", "supergroup"):
            meta = await remember_group_chat(forwarded_chat, "linked")
            bound = bind_group(
                forwarded_chat.id,
                getattr(forwarded_chat, "title", "") or (meta["title"] if meta else str(forwarded_chat.id)),
                getattr(forwarded_chat, "username", "") or "",
                actor_id=u.id,
            )
            await update.message.reply_text(
                f"تم ربط المجموعة من الرسالة المعاد توجيهها.\nالاسم: {bound['title']}\nالآيدي: {bound['id']}"
            )
            return
        text = (update.message.text or "").strip()
        if context.user_data.get("awaiting_search"):
            context.user_data["awaiting_search"] = False
            rows = db.search_users(text, 20)
            if not rows:
                await update.message.reply_text("لا توجد نتائج.")
            else:
                await update.message.reply_text(
                    "\n".join(
                        f"{r['alias']} | {r['real_name']} | {r['status']} | "
                        f"{'مكتوم' if r.get('muted') else 'مسموح'} | {r['user_id']}"
                        for r in rows
                    ),
                    reply_markup=ADMIN_MENU,
                )
            return
        return
    row = db.get_user(u.id)
    text = (update.message.text or "").strip()
    if row and row["status"] == "approved":
        await publish_alias_message(update, context, row, text)
    else:
        await update.message.reply_text("استخدم أزرار القائمة، أو أكمل التسجيل أولاً.", reply_markup=USER_MENU)


async def reply_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    args = context.args or []
    if len(args) < 2 or not args[0].lstrip("-").isdigit():
        await update.message.reply_text("الصيغة: /reply USER_ID نص الرد")
        return
    target_id = int(args[0])
    reply_text = " ".join(args[1:])
    try:
        await context.bot.send_message(target_id, "رد الإدارة:\n" + reply_text)
        await update.message.reply_text("تم إرسال الرد.")
        db.audit(update.effective_user.id, "support_reply", target_id, reply_text[:200])
        tickets = db.list_tickets("open", 50)
        for ticket in tickets:
            if ticket["user_id"] == target_id:
                db.close_ticket(ticket["ticket_id"], update.effective_user.id)
                break
    except Exception as exc:
        await update.message.reply_text(f"تعذر الإرسال: {exc}")


async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != ChatType.PRIVATE:
        return
    u = update.effective_user
    if is_admin(u.id):
        message = " ".join(context.args or []).strip()
        if not message:
            await update.message.reply_text("اكتب الرسالة بعد الأمر: /broadcast نص الرسالة")
            return
        await publish_admin_broadcast(update, context, message)
        return
    row = db.get_user(u.id)
    if not row or row["status"] != "approved":
        await update.message.reply_text("يجب أن تكون مقبولاً أولاً.", reply_markup=USER_MENU)
        return
    message = " ".join(context.args or []).strip()
    if not message:
        await update.message.reply_text("اكتب الرسالة بعد الأمر: /broadcast نص الرسالة")
        return
    await publish_alias_message(update, context, row, message)


async def publish_admin_broadcast(update, context, message):
    if not settings.group_id:
        await update.message.reply_text("لم يضبط المدير المجموعة بعد من لوحة التحكم.")
        return
    try:
        await context.bot.send_message(chat_id=settings.group_id, text=f"إعلان الإدارة:\n{message}")
        await update.message.reply_text("تم نشر الإعلان في المجموعة.")
        db.audit(update.effective_user.id, "admin_broadcast", None, message[:200])
    except Exception:
        log.exception("Admin broadcast failed")
        await update.message.reply_text("تعذر النشر. تأكد أن البوت مشرف في المجموعة.")


async def publish_alias_message(update, context, row, message):
    if not message:
        await update.message.reply_text("الرسالة فارغة.")
        return
    if row.get("muted"):
        await update.message.reply_text("تم كتم حسابك. لا يمكنك النشر حالياً.")
        return
    if not settings.group_id:
        await update.message.reply_text("لم تُضبط المجموعة بعد. تواصل مع الإدارة.")
        return
    try:
        await context.bot.send_message(
            chat_id=settings.group_id,
            text=f"{row['alias']}:\n{message}",
        )
        await update.message.reply_text("تم نشر رسالتك في المجموعة بالاسم المستعار.")
        db.audit(row["user_id"], "alias_broadcast", None, message[:200])
    except Exception:
        log.exception("Alias broadcast failed")
        await update.message.reply_text("تعذر النشر. تأكد أن البوت مشرف في المجموعة ولديه صلاحية إرسال الرسائل.")


async def _send_invite(context, user_id):
    try:
        invite = None
        if settings.group_id:
            invite = await context.bot.create_chat_invite_link(
                chat_id=settings.group_id, member_limit=1, creates_join_request=False
            )
        if invite:
            await context.bot.send_message(user_id, f"رابط دعوة خاص للمجموعة (استخدام واحد): {invite.invite_link}")
        elif settings.group_link:
            await context.bot.send_message(user_id, f"رابط المجموعة: {settings.group_link}")
    except Exception:
        log.exception("Could not create/send invite link")
        if settings.group_link:
            try:
                await context.bot.send_message(user_id, f"رابط المجموعة: {settings.group_link}")
            except Exception:
                pass


async def admin_decision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id):
        await q.answer("غير مصرح لك.", show_alert=True)
        return
    try:
        _, status, target = q.data.split(":")
        target_id = int(target)
    except (ValueError, TypeError):
        await q.message.reply_text("بيانات القرار غير صالحة.")
        return
    if status not in ("approved", "rejected", "suspended"):
        await q.message.reply_text("حالة غير معروفة.")
        return
    row = db.get_user(target_id)
    if not row:
        await q.message.reply_text("العضو غير موجود في قاعدة البيانات.")
        return
    db.set_status(target_id, status, q.from_user.id, "admin decision")
    await q.edit_message_reply_markup(reply_markup=None)
    await q.message.reply_text(f"تم تحديث حالة {target_id} إلى {status}.")
    if status == "approved":
        message = f"تم قبول طلبك. اسمك المستعار: {row['alias']}."
        try:
            invite = await context.bot.create_chat_invite_link(
                chat_id=settings.group_id, member_limit=1, creates_join_request=False
            ) if settings.group_id else None
            if invite:
                message += f"\nرابط دعوة خاص (استخدام واحد): {invite.invite_link}"
            elif settings.group_link:
                message += f"\nرابط المجموعة: {settings.group_link}"
        except Exception:
            log.exception("Could not create invite link")
            if settings.group_link:
                message += f"\nرابط المجموعة: {settings.group_link}"
    elif status == "rejected":
        message = "تم رفض طلبك. يمكنك إعادة المحاولة بعد 10 دقائق."
    else:
        message = "تم إيقاف حسابك مؤقتاً. تواصل مع الإدارة عند الحاجة."
    try:
        await context.bot.send_message(target_id, message, reply_markup=USER_MENU)
    except Exception:
        log.warning("Could not notify user %s", target_id)
