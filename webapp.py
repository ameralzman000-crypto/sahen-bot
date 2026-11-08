import html
import secrets
from urllib.parse import quote
from aiohttp import web

import config
import database as db
from envutil import persist_env
from bot_runtime import bot_status, start_bot, stop_bot, restart_bot, get_bot
from utils import display_name

_runner = None
SESSIONS = set()


def esc(value):
    return html.escape(str(value or ""))


def page(body, flash=""):
    notice = f'<div class="flash">{esc(flash)}</div>' if flash else ""
    return f"""<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>لوحة تحكم الشاهين</title>
<style>
:root{{--bg:#0d1520;--card:#162233;--line:#2a3c52;--gold:#e8c66a;--text:#f3f4f6;--muted:#9fb0c3;--ok:#34d399;--bad:#f87171;--warn:#fbbf24}}
*{{box-sizing:border-box}}body{{font-family:system-ui,Tahoma,Arial;background:var(--bg);color:var(--text);margin:0}}
.wrap{{max-width:1180px;margin:auto;padding:18px}}h1,h2{{color:var(--gold);margin:0 0 12px}}
.top{{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:16px;flex-wrap:wrap}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;margin-bottom:16px}}
.card,section{{background:var(--card);padding:16px;border-radius:14px;margin-bottom:14px;border:1px solid var(--line)}}
.num{{font-size:26px;color:var(--gold)}}small{{color:var(--muted)}}
table{{width:100%;border-collapse:collapse;font-size:14px}}td,th{{padding:8px;border-bottom:1px solid var(--line);text-align:right;vertical-align:middle}}
input,button,select,textarea{{padding:9px 10px;border-radius:8px;border:1px solid var(--line);background:#101a27;color:var(--text);font:inherit}}
button,.btn{{background:var(--gold);color:#111;cursor:pointer;border:0;font-weight:700;text-decoration:none;display:inline-block}}
.row{{display:grid;grid-template-columns:1fr 1fr;gap:10px}}
.actions{{display:flex;flex-wrap:wrap;gap:6px}}
.btn.gray{{background:#334155;color:#fff}}.btn.red{{background:#b91c1c;color:#fff}}.btn.green{{background:#047857;color:#fff}}
.flash{{background:#1f3b2d;color:#bbf7d0;padding:10px 12px;border-radius:10px;margin-bottom:12px}}
.badge{{padding:3px 8px;border-radius:999px;font-size:12px}}
.ok{{background:#064e3b;color:var(--ok)}}.bad{{background:#7f1d1d;color:var(--bad)}}.warn{{background:#78350f;color:var(--warn)}}
nav a{{color:var(--gold);margin-left:10px}}textarea{{width:100%;min-height:120px}}
@media(max-width:800px){{.row{{grid-template-columns:1fr}}}}
</style></head><body><div class="wrap">{notice}{body}</div></body></html>"""


def cookie_ok(request):
    token = request.cookies.get("shahin_session", "")
    return token in SESSIONS


def login_page(error=""):
    err = f"<p class='bad'>{esc(error)}</p>" if error else ""
    return page(f"""
    <h1>لوحة تحكم الشاهين</h1>
    <section>
      {err}
      <p>أدخل كلمة مرور المدير للوصول إلى الإعدادات.</p>
      <form method="post" action="/login">
        <input type="password" name="password" placeholder="كلمة المرور" required>
        <button>دخول</button>
      </form>
    </section>
    """)


def go(path, flash=""):
    loc = path + (("?flash=" + quote(flash)) if flash else "")
    raise web.HTTPFound(loc)


def mask_token(token):
    if not token:
        return "غير مضبوط"
    if len(token) <= 10:
        return "*" * len(token)
    return token[:6] + "..." + token[-4:]


def status_badge(user):
    status = user.get("status") or ""
    muted = db.is_muted(user["user_id"])
    extra = " + مكتوم" if muted else ""
    cls = {"approved": "ok", "pending": "warn", "rejected": "bad", "banned": "bad"}.get(status, "warn")
    return f'<span class="badge {cls}">{esc(status)}{extra}</span>'


@web.middleware
async def auth_middleware(request, handler):
    if request.path in ("/login", "/health"):
        return await handler(request)
    if request.path == "/" and request.method == "GET" and not cookie_ok(request):
        return web.Response(text=login_page(), content_type="text/html")
    if request.path == "/logout":
        return await handler(request)
    if not cookie_ok(request):
        raise web.HTTPFound("/login")
    return await handler(request)


async def login(request):
    data = await request.post()
    password = str(data.get("password") or "")
    expected = config.WEB_PASSWORD
    if not expected or len(password) != len(expected) or not secrets.compare_digest(password, expected):
        return web.Response(text=login_page("كلمة المرور غير صحيحة."), content_type="text/html", status=401)
    token = secrets.token_urlsafe(24)
    SESSIONS.add(token)
    resp = web.HTTPFound("/")
    resp.set_cookie("shahin_session", token, httponly=True, samesite="Lax", max_age=60 * 60 * 12)
    raise resp


async def logout(request):
    token = request.cookies.get("shahin_session", "")
    SESSIONS.discard(token)
    resp = web.HTTPFound("/login")
    resp.del_cookie("shahin_session")
    raise resp


async def login_get(request):
    if cookie_ok(request):
        raise web.HTTPFound("/")
    return web.Response(text=login_page(), content_type="text/html")


def user_rows(users):
    if not users:
        return "<tr><td colspan='7'>لا يوجد أعضاء.</td></tr>"
    out = []
    for r in users:
        muted = db.is_muted(r["user_id"])
        mute_label = "فك الكتم" if muted else "كتم"
        out.append(f"""<tr>
        <td>{r['user_id']}</td>
        <td>{esc(r.get('real_name'))}<br><small>@{esc(r.get('username') or '-')}</small></td>
        <td>{esc(display_name(r))}<br><small>{esc(r.get('alias') or '')}</small></td>
        <td>{esc(r.get('role'))}</td>
        <td>{status_badge(r)}</td>
        <td>
          <form class="actions" method="post" action="/users/action">
            <input type="hidden" name="user_id" value="{r['user_id']}">
            <button class="btn green" name="action" value="approved">قبول</button>
            <button class="btn gray" name="action" value="rejected">رفض</button>
            <button class="btn gray" name="action" value="mute">{mute_label}</button>
            <button class="btn gray" name="action" value="mod">مشرف</button>
            <button class="btn red" name="action" value="banned">حظر</button>
            <button class="btn red" name="action" value="unregister">إلغاء التسجيل</button>
          </form>
          <form class="actions" method="post" action="/users/action" style="margin-top:6px">
            <input type="hidden" name="user_id" value="{r['user_id']}">
            <input type="hidden" name="action" value="setalias">
            <input name="alias" placeholder="اسم مستعار جديد" required>
            <button class="btn gray">تعديل المستعار</button>
          </form>
          <form class="actions" method="post" action="/users/action" style="margin-top:6px">
            <input type="hidden" name="user_id" value="{r['user_id']}">
            <input type="hidden" name="action" value="setname">
            <input name="real_name" placeholder="اسم حقيقي جديد" required>
            <button class="btn gray">تعديل الحقيقي</button>
          </form>
        </td>
        </tr>""")
    return "".join(out)


async def dashboard(request):
    config.reload_from_env()
    flash = request.query.get("flash", "")
    query = request.query.get("q", "").strip()
    stats = db.stats()
    runtime = bot_status()
    users = db.list_members()
    if query:
        q = query.casefold()
        users = [
            u for u in users
            if q in str(u.get("user_id", "")).casefold()
            or q in str(u.get("real_name") or "").casefold()
            or q in str(u.get("alias") or "").casefold()
            or q in str(u.get("username") or "").casefold()
        ]
    pending = db.list_by_status(config.STATUS_PENDING)
    bot_cls = "ok" if runtime["status"] == "running" else "bad"
    group_id = db.get_group_chat_id() or ""
    group_type = db.get_bound_chat_type()
    paused = db.is_paused()
    rules = db.get_rules()
    body = f"""
    <div class="top">
      <h1>لوحة تحكم الشاهين</h1>
      <nav><a href="/">تحديث</a><a href="/logout">خروج</a></nav>
    </div>
    <div class="cards">
      {''.join(f'<div class="card"><small>{label}</small><div class="num">{value}</div></div>' for label,value in [
        ('كل الأعضاء', stats['total']), ('مقبولون', stats['approved']), ('معلقون', stats['pending']),
        ('مرفوضون', stats['rejected']), ('محظورون', stats['banned']), ('مشرفون', stats['moderators']),
        ('رسائل معاد نشرها', stats['messages'])
      ])}
      <div class="card"><small>حالة البوت</small><div class="num"><span class="badge {bot_cls}">{esc(runtime['status'])}</span></div>
      <small>{'إيقاف مؤقت للنشر' if paused else 'إعادة النشر تعمل'}<br>{esc(runtime['error'])}</small></div>
    </div>

    <section>
      <h2>تشغيل البوت</h2>
      <p>التوكن الحالي: <code>{esc(mask_token(config.BOT_TOKEN))}</code> | المدير: <code>{config.ADMIN_ID}</code></p>
      <form class="actions" method="post" action="/bot/control">
        <button class="btn green" name="action" value="start">تشغيل البوت</button>
        <button class="btn gray" name="action" value="stop">إيقاف البوت</button>
        <button class="btn" name="action" value="restart">إعادة تشغيل</button>
        <button class="btn gray" name="action" value="pause">إيقاف إعادة النشر</button>
        <button class="btn green" name="action" value="resume">استئناف النشر</button>
      </form>
      <form method="post" action="/settings/purge" style="margin-top:12px">
        <p>الحذف التلقائي للمحادثات كل
          <input type="number" name="hours" min="1" max="168" value="{esc(db.get_setting('auto_purge_hours') or config.AUTO_PURGE_HOURS)}" style="width:80px">
          ساعة
        </p>
        <div class="actions">
          <button class="btn green" name="action" value="enable">تفعيل الحذف التلقائي</button>
          <button class="btn gray" name="action" value="disable">إيقاف الحذف التلقائي</button>
          <button class="btn red" name="action" value="now">حذف الآن</button>
        </div>
        <small>آخر حذف تلقائي: {esc(db.get_setting('last_auto_purge') or 'لم يتم بعد')} | الحالة: {"مفعّل" if (db.get_setting("auto_purge_enabled") or "true").lower() in ("1","true","yes","on") else "متوقف"}</small>
      </form>
    </section>

    <div class="row">
      <section>
        <h2>تغيير توكن البوت</h2>
        <p>ضع توكن جديد من BotFather ثم احفظ. سيتم إعادة تشغيل البوت تلقائياً.</p>
        <form method="post" action="/settings/token">
          <input type="text" name="bot_token" placeholder="123456:ABC..." required style="width:100%;margin-bottom:8px">
          <button>حفظ التوكن وإعادة التشغيل</button>
        </form>
      </section>
      <section>
        <h2>المجموعة / القناة</h2>
        <p>المربوطة الآن: <code>{esc(group_id or 'غير مربوط')}</code> ({esc(group_type)})</p>
        <p><small>أسهل ربط: أضف البوت مشرفاً، أو اكتب /setgroup داخل المجموعة، أو /setchannel من الخاص.</small></p>
        <form method="post" action="/settings/group">
          <input type="text" name="group_id" value="{esc(group_id)}" placeholder="-100..." style="width:100%;margin-bottom:8px">
          <select name="chat_type" style="margin-bottom:8px">
            <option value="supergroup" {"selected" if group_type != "channel" else ""}>مجموعة</option>
            <option value="channel" {"selected" if group_type == "channel" else ""}>قناة</option>
          </select>
          <div class="actions">
            <button class="btn green" name="action" value="save">حفظ الربط</button>
            <button class="btn red" name="action" value="clear">حذف الربط</button>
          </div>
        </form>
      </section>
    </div>

    <section>
      <h2>المدير والقوانين</h2>
      <form method="post" action="/settings/general" class="row">
        <div>
          <p>آيدي المدير</p>
          <input type="text" name="admin_id" value="{config.ADMIN_ID}" style="width:100%">
          <p>كلمة مرور اللوحة</p>
          <input type="password" name="web_password" placeholder="اتركه فارغاً للإبقاء على الحالية" style="width:100%">
          <p><button>حفظ الإعدادات</button></p>
        </div>
        <div>
          <p>نص القوانين</p>
          <textarea name="rules">{esc(rules)}</textarea>
        </div>
      </form>
    </section>

    <section>
      <h2>طلبات الانتظار</h2>
      <table>
        <thead><tr><th>آيدي</th><th>الاسم</th><th>المستعار</th><th>تحكم</th></tr></thead>
        <tbody>
        {''.join(f'''<tr><td>{p["user_id"]}</td><td>{esc(p.get("real_name"))}</td><td>{esc(p.get("alias"))}</td>
        <td><form class="actions" method="post" action="/users/action">
        <input type="hidden" name="user_id" value="{p["user_id"]}">
        <button class="btn green" name="action" value="approved">قبول</button>
        <button class="btn red" name="action" value="rejected">رفض</button>
        </form></td></tr>''' for p in pending) or "<tr><td colspan='4'>لا توجد طلبات معلقة.</td></tr>"}
        </tbody>
      </table>
    </section>

    <section>
      <h2>الأعضاء والتحكم</h2>
      <form method="get" action="/" style="margin-bottom:10px">
        <input name="q" value="{esc(query)}" placeholder="بحث بالاسم أو الآيدي">
        <button>بحث</button>
      </form>
      <table>
        <thead><tr><th>آيدي</th><th>الاسم</th><th>المستعار</th><th>الدور</th><th>الحالة</th><th>تحكم</th></tr></thead>
        <tbody>{user_rows(users)}</tbody>
      </table>
    </section>
    """
    return web.Response(text=page(body, flash), content_type="text/html")


async def save_token(request):
    data = await request.post()
    token = str(data.get("bot_token") or "").strip()
    if ":" not in token:
        go("/", "توكن غير صالح")
    persist_env({"BOT_TOKEN": token})
    config.reload_from_env()
    ok = await restart_bot()
    go("/", "تم حفظ التوكن وتشغيل البوت" if ok else f"حُفظ التوكن لكن التشغيل فشل: {bot_status()['error']}")


async def save_group(request):
    data = await request.post()
    action = str(data.get("action") or "save")
    if action == "clear":
        db.set_setting("group_chat_id", "")
        db.set_setting("bound_chat_type", "supergroup")
        go("/", "تم حذف ربط المجموعة")
    raw_id = str(data.get("group_id") or "").strip()
    chat_type = str(data.get("chat_type") or "supergroup")
    try:
        group_id = int(raw_id)
    except ValueError:
        go("/", "آيدي المجموعة غير صالح")
    db.set_bound_chat(group_id, chat_type)
    go("/", "تم حفظ ربط المجموعة/القناة")


async def save_general(request):
    data = await request.post()
    updates = {}
    admin_id = str(data.get("admin_id") or "").strip()
    if admin_id.lstrip("-").isdigit():
        updates["ADMIN_ID"] = admin_id
        updates["ADMIN_IDS"] = admin_id
    password = str(data.get("web_password") or "").strip()
    if password:
        updates["WEB_PASSWORD"] = password
    if updates:
        persist_env(updates)
        config.reload_from_env()
        db.ensure_admin(config.ADMIN_ID)
    rules = str(data.get("rules") or "").strip()
    if rules:
        db.set_rules(rules[: config.MAX_RULES])
    go("/", "تم حفظ الإعدادات")


async def bot_control(request):
    data = await request.post()
    action = str(data.get("action") or "")
    if action == "start":
        ok = await start_bot()
        go("/", "تم تشغيل البوت" if ok else f"فشل التشغيل: {bot_status()['error']}")
    if action == "stop":
        await stop_bot()
        go("/", "تم إيقاف البوت")
    if action == "restart":
        ok = await restart_bot()
        go("/", "تمت إعادة التشغيل" if ok else f"فشل إعادة التشغيل: {bot_status()['error']}")
    if action == "pause":
        db.set_paused(True)
        go("/", "تم إيقاف إعادة النشر مؤقتاً")
    if action == "resume":
        db.set_paused(False)
        go("/", "تم استئناف إعادة النشر")
    go("/", "إجراء غير معروف")


async def save_purge(request):
    data = await request.post()
    action = str(data.get("action") or "")
    hours_raw = str(data.get("hours") or "24").strip()
    try:
        hours = max(1, min(168, int(hours_raw)))
    except ValueError:
        hours = 24
    db.set_setting("auto_purge_hours", str(hours))
    persist_env({"AUTO_PURGE_HOURS": str(hours)})
    config.reload_from_env()
    if action == "disable":
        db.set_setting("auto_purge_enabled", "false")
        persist_env({"AUTO_PURGE_ENABLED": "false"})
        go("/", "تم إيقاف الحذف التلقائي")
    if action == "enable":
        db.set_setting("auto_purge_enabled", "true")
        persist_env({"AUTO_PURGE_ENABLED": "true"})
        go("/", f"تم تفعيل الحذف التلقائي كل {hours} ساعة")
    if action == "now":
        app = get_bot()
        if not app:
            go("/", "البوت متوقف. شغّله أولاً ثم احذف.")
        from bot import run_scheduled_purge
        class _Ctx:
            bot = app.bot
        deleted, failed = await run_scheduled_purge(_Ctx())
        go("/", f"تم الحذف الآن. المحذوف: {deleted} — تعذر: {failed}")
    go("/", "تم حفظ جدولة الحذف")


async def user_action(request):
    data = await request.post()
    try:
        user_id = int(data.get("user_id"))
    except (TypeError, ValueError):
        go("/", "آيدي غير صالح")
    action = str(data.get("action") or "")
    user = db.get_user(user_id)
    if not user:
        go("/", "العضو غير موجود")
    app = get_bot()
    if action == "approved":
        db.set_status(user_id, config.STATUS_APPROVED)
        if app:
            try:
                from bot import notify_approval
                class _Ctx:
                    bot = app.bot
                await notify_approval(_Ctx(), user_id)
            except Exception:
                pass
        go("/", f"تم قبول {user_id}")
    if action == "rejected":
        db.set_status(user_id, config.STATUS_REJECTED)
        if app:
            try:
                await app.bot.send_message(user_id, "تم رفض طلبك.")
            except Exception:
                pass
        go("/", f"تم رفض {user_id}")
    if action == "banned":
        db.set_status(user_id, config.STATUS_BANNED)
        go("/", f"تم حظر {user_id}")
    if action == "mute":
        if db.is_muted(user_id):
            db.clear_mute(user_id)
            go("/", "تم فك الكتم")
        db.set_mute(user_id, 4102444800, "dashboard")
        go("/", "تم كتم العضو")
    if action == "mod":
        if user.get("role") == config.ROLE_MODERATOR:
            db.set_role(user_id, config.ROLE_MEMBER, None, 0)
            go("/", "تم إلغاء الإشراف")
        number = db.next_moderator_number()
        db.set_role(user_id, config.ROLE_MODERATOR, number, 0)
        go("/", f"تم تعيين مشرف {number}")
    if action == "unregister":
        if user_id == config.ADMIN_ID:
            go("/", "لا يمكن إلغاء تسجيل المدير")
        if not db.delete_user(user_id):
            go("/", "تعذر إلغاء التسجيل")
        if app:
            try:
                await app.bot.send_message(user_id, "أُلغي تسجيلك. أعد التسجيل عبر /start إذا رغبت.")
            except Exception:
                pass
        go("/", f"تم إلغاء تسجيل {user_id}")
    if action == "setalias":
        if user_id == config.ADMIN_ID:
            go("/", "لا يمكن تعديل اسم المدير الظاهر")
        from utils import validate_alias
        alias = validate_alias(str(data.get("alias") or ""))
        if not alias:
            go("/", "الاسم المستعار غير صالح")
        if db.alias_taken(alias, exclude_user_id=user_id):
            go("/", "هذا الاسم المستعار مستخدم")
        db.set_alias(user_id, alias)
        if app:
            try:
                await app.bot.send_message(user_id, f"غيّر المدير اسمك المستعار إلى: {alias}")
            except Exception:
                pass
        go("/", f"تم تعديل الاسم المستعار لـ {user_id}")
    if action == "setname":
        from utils import validate_real_name
        real_name = validate_real_name(str(data.get("real_name") or ""))
        if not real_name:
            go("/", "الاسم الحقيقي غير صالح")
        db.set_real_name(user_id, real_name)
        if app:
            try:
                await app.bot.send_message(user_id, f"غيّر المدير اسمك الحقيقي إلى: {real_name}")
            except Exception:
                pass
        go("/", f"تم تعديل الاسم الحقيقي لـ {user_id}")
    go("/", "إجراء غير معروف")


async def health(request):
    return web.json_response({"ok": True, "service": "shahin-dashboard", "bot": bot_status()["status"]})


async def start_web_server():
    global _runner
    if _runner:
        return
    db.init_db()
    db.ensure_admin(config.ADMIN_ID)
    app = web.Application(middlewares=[auth_middleware])
    app.router.add_get("/health", health)
    app.router.add_get("/login", login_get)
    app.router.add_post("/login", login)
    app.router.add_get("/logout", logout)
    app.router.add_get("/", dashboard)
    app.router.add_post("/settings/token", save_token)
    app.router.add_post("/settings/group", save_group)
    app.router.add_post("/settings/general", save_general)
    app.router.add_post("/bot/control", bot_control)
    app.router.add_post("/settings/purge", save_purge)
    app.router.add_post("/users/action", user_action)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, config.WEB_HOST, config.WEB_PORT)
    try:
        await site.start()
        _runner = runner
    except OSError:
        await runner.cleanup()
        raise
