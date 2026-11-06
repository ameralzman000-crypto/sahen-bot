from config import settings
from envutil import persist_env
import database as db


def apply_updates(updates, actor_id=0, action="settings_updated", target_id=None, details=""):
    for key, value in updates.items():
        db.set_setting(key, value)
    persist_env(updates)
    settings.reload()
    db.audit(actor_id, action, target_id, details)


def bind_group(group_id, title="", username="", link="", actor_id=0):
    group_id = int(group_id)
    title = title or ""
    username = username or ""
    invite = link or settings.group_link
    if username and not invite:
        invite = f"https://t.me/{username.lstrip('@')}"
    db.upsert_known_group(group_id, title, username, "linked")
    apply_updates(
        {
            "TARGET_GROUP_ID": str(group_id),
            "TARGET_GROUP_TITLE": title,
            "TARGET_GROUP_LINK": invite or "",
        },
        actor_id=actor_id,
        action="group_linked",
        target_id=group_id,
        details=title,
    )
    return {
        "id": group_id,
        "title": title,
        "username": username,
        "link": invite or "",
    }


def unbind_group(actor_id=0):
    apply_updates(
        {
            "TARGET_GROUP_ID": "0",
            "TARGET_GROUP_TITLE": "",
            "TARGET_GROUP_LINK": "",
        },
        actor_id=actor_id,
        action="group_cleared",
        details="",
    )
