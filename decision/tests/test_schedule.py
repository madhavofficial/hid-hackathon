from datetime import datetime
from zoneinfo import ZoneInfo

from decision.schedule import access_for, load_schedule

IST = ZoneInfo("Asia/Kolkata")


def test_mock_schedule_splits_the_three_enrolled_people():
    schedule = load_schedule()
    saturday_evening = datetime(2026, 11, 14, 17, 19, tzinfo=IST)
    assert access_for("kirthan", saturday_evening, schedule) == "allow"
    assert access_for("roshini", saturday_evening, schedule) == "allow"
    assert access_for("sreekar", saturday_evening, schedule) == "deny"


def test_roshini_is_allowed_every_day_and_kirthan_steps_up_on_monday():
    schedule = load_schedule()
    monday_noon = datetime(2026, 11, 16, 12, 0, tzinfo=IST)
    assert access_for("roshini", monday_noon, schedule) == "allow"
    assert access_for("kirthan", monday_noon, schedule) == "step_up"
