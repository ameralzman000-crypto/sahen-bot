import asyncio
import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import bot
import config
import database as db
from utils import can_reveal_identity


class DummyMsg:
    def __init__(self, text="*", message_id=50, reply_to=None, chat_id=-100):
        self.text = text
        self.caption = None
        self.message_id = message_id
        self.reply_to_message = reply_to
        self.chat_id = chat_id
        self.from_user = None
        self.photo = None
        self.video = None
        self.document = None
        self.audio = None
        self.voice = None
        self.video_note = None
        self.sticker = None
        self.animation = None
        self.location = None
        self.delete = AsyncMock()
        self.reply_text = AsyncMock()


def _update(user_id, message, chat_type="supergroup"):
    user = SimpleNamespace(id=user_id, username="u", is_bot=False)
    chat = SimpleNamespace(id=-100, type=chat_type)
    return SimpleNamespace(
        effective_user=user,
        effective_message=message,
        effective_chat=chat,
        message=message,
    )


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    path = str(tmp_path / "t.db")
    monkeypatch.setattr(config, "DB_PATH", path)
    db.init_db()
    db.ensure_admin(config.ADMIN_ID)
    return path


def test_unauthorized_reveal_is_blocked(isolated_db):
    async def _run():
        db.upsert_registration(3003, "عضو", "النسر", None)
        db.set_status(3003, "approved")
        original = DummyMsg(text="hello", message_id=10)
        reveal = DummyMsg(text="*", message_id=11, reply_to=original)
        update = _update(3003, reveal)
        context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()))
        with patch.object(bot, "safe_send_private", new=AsyncMock(return_value=True)) as priv:
            handled = await bot.handle_reveal(update, context)
        assert handled is True
        priv.assert_awaited()
        sent_text = priv.await_args.args[2]
        assert "صلاحية" in sent_text
        assert "الاسم الحقيقي" not in sent_text
        reveal.delete.assert_awaited()

    asyncio.run(_run())


def test_admin_reveal_sends_private_identity(isolated_db):
    async def _run():
        db.upsert_registration(4004, "ليلى أحمد", "الوردة", "layla")
        db.set_status(4004, "approved")
        db.save_message(-100, 1, 20, 4004)
        target_msg = DummyMsg(text="hi", message_id=20)
        reveal = DummyMsg(text="*", message_id=21, reply_to=target_msg)
        update = _update(config.ADMIN_ID, reveal)
        context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()))
        with patch.object(bot, "safe_send_private", new=AsyncMock(return_value=True)) as priv:
            handled = await bot.handle_reveal(update, context)
        assert handled is True
        info = priv.await_args.args[2]
        assert "ليلى أحمد" in info
        assert "الوردة" in info
        assert "4004" in info

    asyncio.run(_run())


def test_moderator_without_flag_cannot_reveal(isolated_db):
    async def _run():
        db.upsert_registration(5005, "مشرف", "الحارس", None)
        db.set_status(5005, "approved")
        db.set_role(5005, "moderator", moderator_number=1, can_reveal=0)
        user = db.get_user(5005)
        assert can_reveal_identity(user) is False
        reveal = DummyMsg(text="*", message_id=3, reply_to=DummyMsg(message_id=2))
        update = _update(5005, reveal)
        context = SimpleNamespace(bot=SimpleNamespace())
        with patch.object(bot, "safe_send_private", new=AsyncMock(return_value=True)) as priv:
            await bot.handle_reveal(update, context)
        assert "صلاحية" in priv.await_args.args[2]

    asyncio.run(_run())


def test_reply_sender_id_uses_message_map(isolated_db):
    db.upsert_registration(8008, "عضو", "الذئب", None)
    db.set_status(8008, "approved")
    db.save_message(-100, 5, 55, 8008)
    reply = DummyMsg(text="✦ الذئب\n────────\nhello", message_id=55)
    assert bot._reply_sender_id(-100, reply) == 8008


def test_reply_sender_id_from_forwarded_channel(isolated_db):
    db.upsert_registration(8009, "عضو", "الصقر", None)
    db.set_status(8009, "approved")
    db.save_message(-200, 9, 90, 8009)
    reply = DummyMsg(text="✦ الصقر\n────────\nhi", message_id=1)
    reply.forward_from_chat = SimpleNamespace(id=-200, type="channel")
    reply.forward_from_message_id = 90
    assert bot._reply_sender_id(-200, reply) == 8009


def test_help_contains_admin_commands():
    assert "/approve" in bot.HELP_TEXT
    assert "⚡" in bot.HELP_TEXT
    assert "/wipe" in bot.HELP_TEXT
    assert "/rules" in bot.HELP_TEXT
    assert "/pause" in bot.HELP_TEXT
    assert "/resume" in bot.HELP_TEXT
    assert "/control" in bot.HELP_TEXT
    assert "/restart" in bot.HELP_TEXT
    assert "/stop" in bot.HELP_TEXT
    assert "/whois" in bot.HELP_TEXT
    assert "/announce" in bot.HELP_TEXT
    assert "/mute" in bot.HELP_TEXT
    assert "/invite" in bot.HELP_TEXT
    assert "/purge" in bot.HELP_TEXT
    assert "/lockgroup" in bot.HELP_TEXT
    assert "/setchannel" in bot.HELP_TEXT
    assert "/ingroup" in bot.HELP_TEXT
    assert "/outgroup" in bot.HELP_TEXT


def test_approval_message_includes_invite(isolated_db):
    text = bot.approval_message("https://t.me/+abc")
    assert "https://t.me/+abc" in text
    assert "تم قبول طلبك" in text
    missing = bot.approval_message(None)
    assert "لم يتم توليد رابط الدخول" in missing
    assert "/ingroup" in text
    db.set_bound_chat(-200, "channel")
    channel_text = bot.approval_message("https://t.me/+abc")
    assert "القناة" in channel_text
    assert "لا تظهر إشعار كتابة" in channel_text


def test_reveal_keyboard_uses_lightning():
    markup = bot.reveal_keyboard()
    button = markup.inline_keyboard[0][0]
    assert button.text == "⚡"
    assert button.callback_data == "rv"


def test_reveal_callback_admin_gets_private_identity(isolated_db):
    async def _run():
        db.upsert_registration(6006, "نورة علي", "النجمة", "noura")
        db.set_status(6006, "approved")
        db.save_message(-100, 1, 80, 6006)
        query = SimpleNamespace(
            from_user=SimpleNamespace(id=config.ADMIN_ID),
            data="rv",
            message=SimpleNamespace(
                message_id=80,
                chat=SimpleNamespace(id=-100),
            ),
            answer=AsyncMock(),
        )
        update = SimpleNamespace(callback_query=query, effective_user=query.from_user)
        context = SimpleNamespace(bot=SimpleNamespace())
        with patch.object(bot, "safe_send_private", new=AsyncMock(return_value=True)) as priv:
            await bot.on_reveal_callback(update, context)
        info = priv.await_args.args[2]
        assert "نورة علي" in info
        assert "النجمة" in info
        query.answer.assert_awaited()

    asyncio.run(_run())


def test_reveal_callback_member_is_blocked(isolated_db):
    async def _run():
        db.upsert_registration(7007, "عضو", "الغيم", None)
        db.set_status(7007, "approved")
        db.save_message(-100, 2, 81, 7007)
        query = SimpleNamespace(
            from_user=SimpleNamespace(id=7007),
            data="rv",
            message=SimpleNamespace(message_id=81, chat=SimpleNamespace(id=-100)),
            answer=AsyncMock(),
        )
        update = SimpleNamespace(callback_query=query, effective_user=query.from_user)
        context = SimpleNamespace(bot=SimpleNamespace())
        with patch.object(bot, "safe_send_private", new=AsyncMock(return_value=True)) as priv:
            await bot.on_reveal_callback(update, context)
        priv.assert_not_awaited()
        alert = query.answer.await_args
        assert "غير مصرح" in alert.args[0]

    asyncio.run(_run())


def test_pause_control_rejected_for_member(isolated_db):
    async def _run():
        query = SimpleNamespace(
            from_user=SimpleNamespace(id=7007),
            data="bot:pause",
            answer=AsyncMock(),
            edit_message_text=AsyncMock(),
        )
        update = SimpleNamespace(callback_query=query, effective_user=query.from_user)
        context = SimpleNamespace(bot=SimpleNamespace())
        await bot.on_bot_control_callback(update, context)
        assert "للمدير فقط" in query.answer.await_args.args[0]
        assert db.is_paused() is False

    asyncio.run(_run())


def test_pause_control_admin_toggles(isolated_db):
    async def _run():
        query = SimpleNamespace(
            from_user=SimpleNamespace(id=config.ADMIN_ID),
            data="bot:pause",
            answer=AsyncMock(),
            edit_message_text=AsyncMock(),
        )
        update = SimpleNamespace(callback_query=query, effective_user=query.from_user)
        context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()))
        await bot.on_bot_control_callback(update, context)
        assert db.is_paused() is True
        query.data = "bot:resume"
        await bot.on_bot_control_callback(update, context)
        assert db.is_paused() is False

    asyncio.run(_run())


def test_control_keyboard_has_restart_and_stop(isolated_db):
    markup = bot.pause_keyboard()
    labels = [btn.text for row in markup.inline_keyboard for btn in row]
    assert "إيقاف مؤقت" in labels or "استئناف إعادة النشر" in labels
    assert "مسح المحادثات" in labels
    assert "قفل الدخول" in labels
    assert "إعادة تشغيل البوت" in labels
    assert "إيقاف البوت" in labels


def test_restart_requires_confirm(isolated_db):
    async def _run():
        query = SimpleNamespace(
            from_user=SimpleNamespace(id=config.ADMIN_ID),
            data="bot:restart",
            answer=AsyncMock(),
            edit_message_text=AsyncMock(),
        )
        update = SimpleNamespace(callback_query=query, effective_user=query.from_user)
        app = SimpleNamespace(stop_running=lambda: None)
        context = SimpleNamespace(bot=SimpleNamespace(), application=app)
        await bot.on_bot_control_callback(update, context)
        assert bot._SHUTDOWN_ACTION is None
        prompt = query.edit_message_text.await_args.args[0]
        assert "إعادة تشغيل" in prompt

    asyncio.run(_run())


def test_stop_confirm_schedules_shutdown(isolated_db):
    async def _run():
        bot._SHUTDOWN_ACTION = None
        stopped = []
        query = SimpleNamespace(
            from_user=SimpleNamespace(id=config.ADMIN_ID),
            data="bot:stop:confirm",
            answer=AsyncMock(),
            edit_message_text=AsyncMock(),
        )
        update = SimpleNamespace(callback_query=query, effective_user=query.from_user)
        app = SimpleNamespace(stop_running=lambda: stopped.append(True))
        context = SimpleNamespace(bot=SimpleNamespace(), application=app)
        await bot.on_bot_control_callback(update, context)
        assert bot._SHUTDOWN_ACTION == "stop"
        assert stopped == [True]
        assert "إيقاف" in query.edit_message_text.await_args.args[0]
        bot._SHUTDOWN_ACTION = None

    asyncio.run(_run())


def test_purge_deletes_recent_history(isolated_db):
    async def _run():
        db.set_group_chat_id(-100)
        db.save_message(-100, 1, 10, 11)
        marker = SimpleNamespace(message_id=120)
        bot_api = SimpleNamespace(
            send_message=AsyncMock(return_value=marker),
            delete_message=AsyncMock(),
            delete_messages=AsyncMock(),
        )
        context = SimpleNamespace(bot=bot_api)
        deleted, failed = await bot.purge_group_messages(context)
        assert failed == 0
        assert deleted >= 120
        assert db.list_message_ids(-100) == []
        bot_api.send_message.assert_awaited()
        bot_api.delete_messages.assert_awaited()
        first_batch = bot_api.delete_messages.await_args_list[0].kwargs["message_ids"]
        assert 120 in first_batch
        assert 10 in first_batch or any(10 in call.kwargs["message_ids"] for call in bot_api.delete_messages.await_args_list)

    asyncio.run(_run())


def test_lock_group_access_revokes_public_invite(isolated_db):
    async def _run():
        db.set_group_chat_id(-100)
        db.set_setting("group_invite_link", "https://t.me/+old")
        context = SimpleNamespace(
            bot=SimpleNamespace(
                export_chat_invite_link=AsyncMock(return_value="https://t.me/+new"),
                set_chat_permissions=AsyncMock(),
                restrict_chat_member=AsyncMock(),
            )
        )
        text = await bot.lock_group_access(context)
        assert "مقفلة" in text
        assert db.get_setting("group_invite_link") == ""
        context.bot.export_chat_invite_link.assert_awaited()
        context.bot.set_chat_permissions.assert_awaited()

    asyncio.run(_run())


def test_publish_from_private_posts_alias(isolated_db):
    async def _run():
        db.set_group_chat_id(-100)
        rec = db.upsert_registration(9009, "سامي علي", "الظل", None)
        db.set_status(9009, "approved")
        rec = db.get_user(9009)
        message = DummyMsg(text="مرحبا من الخاص")
        sent = SimpleNamespace(message_id=77)
        context = SimpleNamespace(
            bot=SimpleNamespace(send_message=AsyncMock(return_value=sent))
        )
        result = await bot.publish_from_private(context, 9009, rec, message)
        assert result is sent
        posted = context.bot.send_message.await_args.kwargs["text"]
        assert "الظل" in posted
        assert "مرحبا من الخاص" in posted
        mapped = db.get_by_relayed(-100, 77)
        assert mapped["sender_id"] == 9009
        assert "المجموعة" in message.reply_text.await_args.args[0]

    asyncio.run(_run())


def test_publish_from_private_to_channel(isolated_db):
    async def _run():
        db.set_bound_chat(-200, "channel")
        rec = db.upsert_registration(9010, "سامي علي", "الظل", None)
        db.set_status(9010, "approved")
        rec = db.get_user(9010)
        message = DummyMsg(text="مرحبا للقناة")
        sent = SimpleNamespace(message_id=88)
        context = SimpleNamespace(
            bot=SimpleNamespace(send_message=AsyncMock(return_value=sent))
        )
        result = await bot.publish_from_private(context, 9010, rec, message)
        assert result is sent
        posted = context.bot.send_message.await_args.kwargs["text"]
        assert "الظل" in posted
        mapped = db.get_by_relayed(-200, 88)
        assert mapped["sender_id"] == 9010
        assert "القناة" in message.reply_text.await_args.args[0]

    asyncio.run(_run())


def test_lock_channel_skips_permissions(isolated_db):
    async def _run():
        db.set_bound_chat(-200, "channel")
        context = SimpleNamespace(
            bot=SimpleNamespace(
                export_chat_invite_link=AsyncMock(return_value="https://t.me/+new"),
                set_chat_permissions=AsyncMock(),
            )
        )
        text = await bot.lock_group_access(context)
        assert "القناة مقفلة" in text
        assert "التعليقات" in text
        context.bot.export_chat_invite_link.assert_awaited()
        context.bot.set_chat_permissions.assert_not_awaited()

    asyncio.run(_run())


def _channel_bot_api(chat_id=-300):
    return SimpleNamespace(
        get_chat=AsyncMock(return_value=SimpleNamespace(id=chat_id, type="channel")),
        get_me=AsyncMock(return_value=SimpleNamespace(id=1)),
        get_chat_member=AsyncMock(return_value=SimpleNamespace(status="administrator")),
        export_chat_invite_link=AsyncMock(return_value="https://t.me/+x"),
        set_chat_permissions=AsyncMock(),
    )


def test_setchannel_binds_forwarded_channel(isolated_db):
    async def _run():
        message = DummyMsg(text="/setchannel")
        message.forward_from_chat = SimpleNamespace(id=-300, type="channel")
        update = _update(config.ADMIN_ID, message, chat_type="private")
        update.effective_chat = SimpleNamespace(id=config.ADMIN_ID, type="private")
        context = SimpleNamespace(args=[], bot=_channel_bot_api(-300))
        await bot.cmd_setchannel(update, context)
        assert db.get_group_chat_id() == -300
        assert db.is_channel_bound() is True
        assert "القناة" in message.reply_text.await_args.args[0]

    asyncio.run(_run())


def test_setchannel_without_args_shows_private_instructions(isolated_db):
    async def _run():
        message = DummyMsg(text="/setchannel")
        message.forward_from_chat = None
        update = _update(config.ADMIN_ID, message, chat_type="private")
        update.effective_chat = SimpleNamespace(id=config.ADMIN_ID, type="private")
        context = SimpleNamespace(args=[], bot=SimpleNamespace())
        await bot.cmd_setchannel(update, context)
        sent = message.reply_text.await_args.args[0]
        assert "من الخاص" in sent
        assert "BIND-" in sent
        assert db.get_setting("channel_bind_token")

    asyncio.run(_run())


def test_parse_channel_ref_accepts_id_and_username():
    assert bot.parse_channel_ref("-1001234567890") == -1001234567890
    assert bot.parse_channel_ref("@mychannel") == "@mychannel"
    assert bot.parse_channel_ref("https://t.me/mychannel") == "@mychannel"
    assert bot.parse_channel_ref("https://t.me/+secret") is None


def test_bind_token_from_channel_post(isolated_db):
    async def _run():
        db.set_setting("channel_bind_token", "ABCDEF12")
        message = DummyMsg(text="BIND-ABCDEF12")
        chat = SimpleNamespace(id=-400, type="channel")
        context = SimpleNamespace(
            bot=SimpleNamespace(
                export_chat_invite_link=AsyncMock(return_value="https://t.me/+x"),
                set_chat_permissions=AsyncMock(),
                send_message=AsyncMock(),
            )
        )
        with patch.object(bot, "safe_send_private", new=AsyncMock(return_value=True)):
            handled = await bot.try_bind_channel_by_token(message, chat, context)
        assert handled is True
        assert db.get_group_chat_id() == -400
        assert db.is_channel_bound() is True
        assert db.get_setting("channel_bind_token") == ""
        message.delete.assert_awaited()

    asyncio.run(_run())


def test_notify_approval_sends_one_time_invite(isolated_db):
    async def _run():
        db.set_group_chat_id(-100)
        invite = SimpleNamespace(invite_link="https://t.me/+secret")
        context = SimpleNamespace(
            bot=SimpleNamespace(create_chat_invite_link=AsyncMock(return_value=invite))
        )
        with patch.object(bot, "safe_send_private", new=AsyncMock(return_value=True)) as priv:
            await bot.notify_approval(context, 4242)
        context.bot.create_chat_invite_link.assert_awaited()
        kwargs = context.bot.create_chat_invite_link.await_args.kwargs
        assert kwargs["member_limit"] == 1
        assert kwargs["name"] == "approved-4242"
        sent = priv.await_args.args[2]
        assert "https://t.me/+secret" in sent

    asyncio.run(_run())


def test_direct_write_confirm_enables_flag(isolated_db):
    async def _run():
        db.upsert_registration(7070, "عضو", "الغيم", None)
        db.set_status(7070, "approved")
        db.set_bound_chat(-100, "supergroup")
        query = SimpleNamespace(
            from_user=SimpleNamespace(id=7070),
            data="dw:on",
            answer=AsyncMock(),
            edit_message_text=AsyncMock(),
        )
        update = SimpleNamespace(callback_query=query, effective_user=query.from_user)
        context = SimpleNamespace(
            bot=SimpleNamespace(restrict_chat_member=AsyncMock())
        )
        await bot.on_direct_write_callback(update, context)
        assert db.allows_direct_write(7070) is True
        context.bot.restrict_chat_member.assert_awaited()
        kwargs = context.bot.restrict_chat_member.await_args.kwargs
        assert kwargs["permissions"].can_send_messages is True
        assert kwargs.get("until_date") is not None
        assert "مسؤوليتك" in query.edit_message_text.await_args.args[0]

    asyncio.run(_run())


def test_outgroup_disables_direct_write(isolated_db):
    async def _run():
        db.upsert_registration(7071, "عضو", "المطر", None)
        db.set_status(7071, "approved")
        db.set_direct_write(7071, True)
        db.set_bound_chat(-100, "supergroup")
        message = DummyMsg(text="/outgroup")
        update = _update(7071, message, chat_type="private")
        context = SimpleNamespace(bot=SimpleNamespace(restrict_chat_member=AsyncMock()))
        await bot.cmd_outgroup(update, context)
        assert db.allows_direct_write(7071) is False
        assert "إلغاء الكتابة" in message.reply_text.await_args.args[0] or "الخاص" in message.reply_text.await_args.args[0]

    asyncio.run(_run())


def test_relay_direct_write_republishes(isolated_db):
    async def _run():
        db.upsert_registration(7072, "عضو", "النجم", None)
        db.set_status(7072, "approved")
        db.set_direct_write(7072, True)
        db.set_bound_chat(-100, "supergroup")
        message = DummyMsg(text="رسالة داخل المجموعة")
        update = _update(7072, message)
        sent = SimpleNamespace(message_id=91)
        context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock(return_value=sent)))
        await bot._relay_message(update, context)
        message.delete.assert_awaited()
        posted = context.bot.send_message.await_args.kwargs["text"]
        assert "النجم" in posted
        assert "رسالة داخل المجموعة" in posted
        mapped = db.get_by_relayed(-100, 91)
        assert mapped["sender_id"] == 7072

    asyncio.run(_run())


def test_wipe_callback_rejects_non_admin(isolated_db):
    async def _run():
        query = SimpleNamespace(
            from_user=SimpleNamespace(id=9999),
            data="wipe:confirm",
            answer=AsyncMock(),
            edit_message_text=AsyncMock(),
        )
        update = SimpleNamespace(callback_query=query, effective_user=query.from_user)
        context = SimpleNamespace(bot=SimpleNamespace())
        await bot.on_wipe_callback(update, context)
        assert "للمدير فقط" in query.answer.await_args.args[0]
        query.edit_message_text.assert_not_awaited()

    asyncio.run(_run())


def test_wipe_callback_admin_resets_data(isolated_db):
    async def _run():
        db.upsert_registration(7777, "عضو", "السهل", None)
        db.set_status(7777, "approved")
        query = SimpleNamespace(
            from_user=SimpleNamespace(id=config.ADMIN_ID),
            data="wipe:confirm",
            answer=AsyncMock(),
            edit_message_text=AsyncMock(),
        )
        update = SimpleNamespace(callback_query=query, effective_user=query.from_user)
        context = SimpleNamespace(bot=SimpleNamespace())
        with patch.object(bot, "safe_send_private", new=AsyncMock(return_value=True)):
            await bot.on_wipe_callback(update, context)
        assert db.get_user(7777) is None
        assert db.get_user(config.ADMIN_ID)["role"] == "admin"
        query.edit_message_text.assert_awaited()

    asyncio.run(_run())


def test_admin_unregister_and_setalias(isolated_db):
    async def _run():
        db.upsert_registration(4242, "خالد علي", "الذئب", None)
        db.set_status(4242, "approved")
        unreg_msg = DummyMsg(text="/unregister 4242")
        unreg_update = _update(config.ADMIN_ID, unreg_msg, chat_type="private")
        context = SimpleNamespace(args=["4242"], bot=SimpleNamespace(send_message=AsyncMock()))
        with patch.object(bot, "safe_send_private", new=AsyncMock(return_value=True)):
            await bot.cmd_unregister(unreg_update, context)
        assert db.get_user(4242) is None
        assert "إلغاء تسجيل" in unreg_msg.reply_text.await_args.args[0]

        db.upsert_registration(4243, "سارة علي", "الوردة", None)
        db.set_status(4243, "approved")
        alias_msg = DummyMsg(text="/setalias 4243 النسر")
        alias_update = _update(config.ADMIN_ID, alias_msg, chat_type="private")
        alias_ctx = SimpleNamespace(args=["4243", "النسر"], bot=SimpleNamespace(send_message=AsyncMock()))
        with patch.object(bot, "safe_send_private", new=AsyncMock(return_value=True)):
            await bot.cmd_setalias(alias_update, alias_ctx)
        assert db.get_user(4243)["alias"] == "النسر"
        assert "النسر" in alias_msg.reply_text.await_args.args[0]

        name_msg = DummyMsg(text="/setname 4243 سارة محمد")
        name_update = _update(config.ADMIN_ID, name_msg, chat_type="private")
        name_ctx = SimpleNamespace(args=["4243", "سارة", "محمد"], bot=SimpleNamespace(send_message=AsyncMock()))
        with patch.object(bot, "safe_send_private", new=AsyncMock(return_value=True)):
            await bot.cmd_setname(name_update, name_ctx)
        assert db.get_user(4243)["real_name"] == "سارة محمد"
        assert "سارة محمد" in name_msg.reply_text.await_args.args[0]

    asyncio.run(_run())


def test_existing_members_notice_sent_once(isolated_db):
    async def _run():
        db.set_bound_chat(-100, "supergroup")
        sent = SimpleNamespace(message_id=42)
        context = SimpleNamespace(
            bot=SimpleNamespace(
                get_me=AsyncMock(return_value=SimpleNamespace(username="shahin_bot")),
                send_message=AsyncMock(return_value=sent),
                pin_chat_message=AsyncMock(),
            )
        )
        first = await bot.notify_existing_members(context, -100)
        second = await bot.notify_existing_members(context, -100)
        assert first is True
        assert second is False
        context.bot.send_message.assert_awaited_once()
        posted = context.bot.send_message.await_args.kwargs["text"]
        assert "الموجودين قبل دخول البوت" in posted
        assert "@shahin_bot" in posted
        assert "/start" in posted
        context.bot.pin_chat_message.assert_awaited_once()

    asyncio.run(_run())


def test_existing_members_notice_skipped_for_channel(isolated_db):
    async def _run():
        db.set_bound_chat(-200, "channel")
        context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()))
        result = await bot.notify_existing_members(context, -200)
        assert result is False
        context.bot.send_message.assert_not_awaited()

    asyncio.run(_run())


def test_build_application(isolated_db, monkeypatch):
    monkeypatch.setattr(config, "BOT_TOKEN", "123456:TESTTOKEN")
    monkeypatch.setattr(bot, "BOT_TOKEN", "123456:TESTTOKEN")
    app = bot.build_application()
    assert app is not None
    assert len(app.handlers) >= 1
