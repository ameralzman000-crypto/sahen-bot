import asyncio
import logging

import config
import bot as aliasbot

log = logging.getLogger("shahin.runtime")

_app = None
_status = "stopped"
_error = ""
_lock = asyncio.Lock()


def bot_status():
    return {"status": _status, "error": _error}


def get_bot():
    return _app


def _sync_token():
    config.reload_from_env()
    aliasbot.BOT_TOKEN = config.BOT_TOKEN
    aliasbot.ADMIN_ID = config.ADMIN_ID


async def start_bot():
    global _app, _status, _error
    async with _lock:
        if _status == "running":
            return True
        _sync_token()
        if not config.BOT_TOKEN:
            _status = "stopped"
            _error = "BOT_TOKEN غير مضبوط"
            return False
        if not config.ADMIN_ID:
            _status = "stopped"
            _error = "ADMIN_ID غير مضبوط"
            return False
        try:
            app = aliasbot.build_application()
            await app.initialize()
            await app.start()
            await app.updater.start_polling(
                allowed_updates=aliasbot.Update.ALL_TYPES,
                drop_pending_updates=True,
            )
            _app = app
            _status = "running"
            _error = ""
            log.info("Alias bot polling started")
            return True
        except Exception as exc:
            log.exception("Failed to start Telegram bot")
            _app = None
            _status = "error"
            _error = str(exc)
            try:
                await app.shutdown()
            except Exception:
                pass
            return False


async def stop_bot():
    global _app, _status, _error
    async with _lock:
        app = _app
        _app = None
        if not app:
            if _status != "error":
                _status = "stopped"
            return
        try:
            if app.updater and app.updater.running:
                await app.updater.stop()
            if app.running:
                await app.stop()
            await app.shutdown()
        except Exception:
            log.exception("Failed to stop Telegram bot cleanly")
        _status = "stopped"
        _error = ""
        log.info("Telegram bot stopped")


async def restart_bot():
    await stop_bot()
    await asyncio.sleep(0.4)
    return await start_bot()
