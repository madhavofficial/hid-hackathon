"""Mock campus access hours. A live match is checked against this after biometrics."""

import json
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

_SCHEDULE_PATH = Path(__file__).resolve().parent / "campus_schedule.json"
_DAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def load_schedule(path: Path | None = None) -> dict:
    raw = json.loads((path or _SCHEDULE_PATH).read_text())
    people = {}
    for person_id, windows in raw.get("people", {}).items():
        people[person_id] = [
            {
                "days": {_DAYS[day] for day in window["days"]},
                "start": time.fromisoformat(window["start"]),
                "end": time.fromisoformat(window["end"]),
            }
            for window in windows
        ]
    return {"timezone": raw.get("timezone", "Asia/Kolkata"), "people": people}


def access_for(person_id: str, now: datetime, schedule: dict) -> str:
    """Return allow, step_up, or deny for an already recognized person."""
    windows = schedule["people"].get(person_id)
    if not windows:
        return "deny"
    local = now.astimezone(ZoneInfo(schedule["timezone"]))
    current = local.timetz().replace(tzinfo=None)
    for window in windows:
        if local.weekday() in window["days"] and window["start"] <= current < window["end"]:
            return "allow"
    return "step_up"


def campus_access(person_id: str, now: datetime | None = None) -> str:
    schedule = load_schedule()
    moment = now or datetime.now(ZoneInfo(schedule["timezone"]))
    return access_for(person_id, moment, schedule)
