import asyncio
import logging

import config
import database as db
from webapp import start_web_server
from bot_runtime import start_bot

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=getattr(logging, str(config.LOG_LEVEL).upper(), logging.INFO),
)
log = logging.getLogger("shahin")


async def main():
    db.init_db()
    db.ensure_admin(config.ADMIN_ID)
    if db.get_setting("auto_purge_enabled") is None:
        db.set_setting("auto_purge_enabled", "true" if config.AUTO_PURGE_ENABLED else "false")
    if db.get_setting("auto_purge_hours") is None:
        db.set_setting("auto_purge_hours", str(config.AUTO_PURGE_HOURS or 24))
    await start_web_server()
    log.info("Web dashboard started on %s:%s", config.WEB_HOST, config.WEB_PORT)
    if config.BOT_TOKEN and config.ADMIN_ID:
        ok = await start_bot()
        if ok:
            log.info("Telegram bot started")
        else:
            log.warning("Telegram bot did not start; control it from the dashboard")
    else:
        log.warning("BOT_TOKEN or ADMIN_ID missing; save settings from the dashboard")
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
