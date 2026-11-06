from __future__ import annotations

import re
from dataclasses import dataclass

from utils import display_name, normalize_space


DURATION_RE = re.compile(
    r"(?P<num>\d+)\s*(?P<unit>"
    r"ث(?:وان[يى]|انية)?|"
    r"د(?:قائق|قيقة)?|"
    r"س(?:اع(?:ة|ات))?|"
    r"ي(?:وم|ام)?|"
    r"m(?:in(?:ute)?s?)?|"
    r"h(?:our)?s?|"
    r"d(?:ay)?s?"
    r")",
    re.I | re.UNICODE,
)

INVISIBLE_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]")
MUTE_HEAD_RE = re.compile(
    r"^[/!٫]?\s*(كتم|mute)\b",
    re.I | re.UNICODE,
)
UNMUTE_HEAD_RE = re.compile(
    r"^[/!٫]?\s*(فك[_\s]?الكتم|إلغاء[_\s]?الكتم|الغاء[_\s]?الكتم|unmute)\b",
    re.I | re.UNICODE,
)
PAUSE_HEAD_RE = re.compile(
    r"^[/!٫]?\s*(pause)\b",
    re.I | re.UNICODE,
)
RESUME_HEAD_RE = re.compile(
    r"^[/!٫]?\s*(resume)\b",
    re.I | re.UNICODE,
)
RELAY_ALIAS_RE = re.compile(r"^✦\s+(.+?)(?:\n|$)")

UNIT_SECONDS = {
    "ث": 1,
    "د": 60,
    "س": 3600,
    "ي": 86400,
}


def normalize_command_text(text: str | None) -> str:
    value = INVISIBLE_RE.sub("", text or "")
    value = normalize_space(value)
    if not value:
        return ""
    first, *rest = value.split(" ", 1)
    if first.startswith(("/", "!", "٫")):
        first = first[1:]
    if "@" in first:
        first = first.split("@", 1)[0]
    return first + ((" " + rest[0]) if rest else "")


def parse_moderation_command(text: str | None) -> tuple[str, int] | None:
    value = normalize_command_text(text)
    if not value:
        return None
    if UNMUTE_HEAD_RE.match(value):
        return ("unmute", 0)
    if MUTE_HEAD_RE.match(value):
        return ("mute", parse_mute_duration(value))
    return None


def parse_power_command(text: str | None) -> str | None:
    value = normalize_command_text(text)
    if not value:
        return None
    if PAUSE_HEAD_RE.match(value):
        return "pause"
    if RESUME_HEAD_RE.match(value):
        return "resume"
    return None


def extract_relay_alias(text: str | None, caption: str | None = None) -> str | None:
    src = text or caption or ""
    match = RELAY_ALIAS_RE.match(src.strip())
    if not match:
        return None
    return normalize_space(match.group(1))


PROBE_PATTERNS = [
    re.compile(r"م[يى]ن\s*(أنت|انت|إنت|انتي|إنتي|هدا|هذا|هذه|هاي|هيدا|هيدي|هاد)\b", re.I),
    re.compile(r"م[يى]ن\s+اللي\b", re.I),
    re.compile(r"م[يى]ن\s+عم\s+يحكي", re.I),
    re.compile(r"م[يى]ن\s+(صاحب|كات[بب]|المرسل|الشخص|الحاكي|الحكي)", re.I),
    re.compile(r"م[يى]ن\s+حك[اىي]", re.I),
    re.compile(r"منو\s*(انت|أنت|هذا|هاد)", re.I),
    re.compile(r"(اسمك|اسمه|اسمها)\s*(الحقيقي|الحقيقى|الاصلي|الأصلي|الواقعي|الكامل)?", re.I),
    re.compile(r"شو\s*اسمك", re.I),
    re.compile(r"شنو\s*اسمك", re.I),
    re.compile(r"اسمك\s*ايه", re.I),
    re.compile(r"(كشف|قول[ي]?|قلي)\s*(هويت|اسمك|اسمه)", re.I),
    re.compile(r"عرف\s*(حالك|نفسك|عن\s*حالك)", re.I),
    re.compile(r"\bهويتك\b", re.I),
    re.compile(r"who\s+are\s+you", re.I),
    re.compile(r"real\s+name", re.I),
    re.compile(r"what(?:'s| is)\s+your\s+name", re.I),
]

LINK_HINTS = re.compile(
    r"(الحقيقي|الحقيقى|الاصلي|الأصلي|اسمه|اسمها|يعني|هو نفسه|هي نفسها|هذا هو|هويته)",
    re.I,
)


@dataclass
class Violation:
    kind: str
    reason: str
    redacted: str


def _tokens(text: str) -> str:
    return normalize_space(text)


def _word_pattern(phrase: str) -> re.Pattern:
    escaped = re.escape(phrase)
    return re.compile(rf"(?<!\w){escaped}(?!\w)", re.I | re.UNICODE)


def _contains_phrase(text: str, phrase: str) -> bool:
    if not phrase:
        return False
    return bool(_word_pattern(phrase).search(text))


def redact_sensitive(text: str, members: list[dict]) -> str:
    result = text or ""
    names = []
    for member in members:
        real = normalize_space(member.get("real_name") or "")
        if real:
            names.append(real)
            parts = real.split()
            if len(parts) >= 2:
                names.extend([p for p in parts if len(p) >= 4])
    for name in sorted(set(names), key=len, reverse=True):
        result = _word_pattern(name).sub("******", result)
    result = re.sub(r"\s+", " ", result).strip()
    if len(result) > 220:
        result = result[:217] + "..."
    return result or "******"


def _approved_members(members: list[dict]) -> list[dict]:
    return [m for m in members if m and m.get("status") == "approved" and m.get("real_name")]


def _is_probe(text: str) -> bool:
    return any(pat.search(text) for pat in PROBE_PATTERNS)


def _mentions_member_real_name(text: str, member: dict, reply_to_id: int | None) -> bool:
    real = normalize_space(member.get("real_name") or "")
    if not real:
        return False
    if _contains_phrase(text, real):
        return True
    parts = real.split()
    if reply_to_id == member.get("user_id") and parts:
        first = parts[0]
        if len(first) >= 3 and _contains_phrase(text, first):
            return True
    if len(parts) >= 2 and all(_contains_phrase(text, p) for p in parts if len(p) >= 3):
        return True
    return False


def _mentions_alias(text: str, member: dict) -> bool:
    alias = normalize_space(member.get("alias") or "")
    shown = normalize_space(display_name(member))
    if alias and _contains_phrase(text, alias):
        return True
    if shown and shown != alias and _contains_phrase(text, shown):
        return True
    return False


def scan_message(
    text: str,
    sender: dict | None,
    members: list[dict],
    reply_to_user_id: int | None = None,
) -> Violation | None:
    body = _tokens(text)
    if not body:
        return None
    people = _approved_members(members)
    sender_id = sender.get("user_id") if sender else None
    redacted = redact_sensitive(body, people)

    self_hit = False
    other_name_hit = False
    alias_with_name = False
    if sender:
        if _mentions_member_real_name(body, sender, reply_to_user_id):
            self_hit = True

    for member in people:
        uid = member.get("user_id")
        if uid == sender_id:
            continue
        named = _mentions_member_real_name(body, member, reply_to_user_id)
        if not named:
            continue
        other_name_hit = True
        if _mentions_alias(body, member) or reply_to_user_id == uid or LINK_HINTS.search(body):
            alias_with_name = True

    if other_name_hit and (alias_with_name or reply_to_user_id or LINK_HINTS.search(body) or _is_probe(body)):
        return Violation("link", "ربط اسم مستعار باسم حقيقي", redacted)
    if other_name_hit and len(normalize_space((sender or {}).get("real_name") or "").split()) >= 1:
        if any(_mentions_member_real_name(body, m, None) for m in people if m.get("user_id") != sender_id):
            full_hits = [
                m
                for m in people
                if m.get("user_id") != sender_id
                and _contains_phrase(body, normalize_space(m.get("real_name") or ""))
            ]
            if full_hits:
                return Violation("link", "ذكر الاسم الحقيقي لعضو في المجموعة", redacted)

    if _is_probe(body):
        return Violation("probe", "سؤال عن هوية عضو", redacted)
    if self_hit:
        return Violation("self", "إفصاح عن الهوية الحقيقية", redacted)
    return None


def parse_mute_duration(text: str | None) -> int:
    if not text:
        return 60
    match = DURATION_RE.search(text)
    if not match:
        return 60
    number = int(match.group("num"))
    unit = match.group("unit") or "د"
    first = unit[0]
    if first in UNIT_SECONDS:
        seconds = number * UNIT_SECONDS[first]
    else:
        lowered = first.lower()
        mapping = {"m": 60, "h": 3600, "d": 86400}
        seconds = number * mapping.get(lowered, 60)
    return max(30, min(seconds, 30 * 86400))


def format_duration(seconds: int) -> str:
    if seconds % 86400 == 0:
        days = seconds // 86400
        return f"{days} يوم" if days == 1 else f"{days} أيام"
    if seconds % 3600 == 0:
        hours = seconds // 3600
        return f"{hours} ساعة" if hours == 1 else f"{hours} ساعات"
    minutes = max(1, seconds // 60)
    if minutes == 1:
        return "دقيقة واحدة"
    return f"{minutes} دقائق"
