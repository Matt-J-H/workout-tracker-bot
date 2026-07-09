"""Week/day helpers.

The week runs Sunday -> Saturday. Days are indexed 0..6 where 0 = Sunday
and 6 = Saturday. Intended days are stored as a comma-separated string of
those indices (e.g. "1,3,5" = Mon, Wed, Fri).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

# index 0 == Sunday
DAY_ABBR = ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"]
DAY_NAMES = [
    "Sunday",
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
]

# Accept a bunch of spellings when parsing user input.
_NAME_TO_IDX: dict[str, int] = {}
for _i, _full in enumerate(DAY_NAMES):
    _NAME_TO_IDX[_full.lower()] = _i
    _NAME_TO_IDX[_full[:3].lower()] = _i  # sun, mon, ...
    _NAME_TO_IDX[DAY_ABBR[_i].lower()] = _i  # su, mo, ...
    _NAME_TO_IDX[str(_i)] = _i


def get_timezone(tz_name: str) -> ZoneInfo:
    return ZoneInfo(tz_name)


def now_in(tz_name: str) -> datetime:
    return datetime.now(get_timezone(tz_name))


def today_in(tz_name: str) -> date:
    return now_in(tz_name).date()


def day_index(d: date) -> int:
    """Return 0..6 where 0 = Sunday for the given date."""
    # Python's weekday(): Mon=0 .. Sun=6. Shift so Sun=0.
    return (d.weekday() + 1) % 7


def week_start(d: date) -> date:
    """Return the Sunday on or before the given date."""
    return d - timedelta(days=day_index(d))


def week_end(d: date) -> date:
    """Return the Saturday on or after the given date."""
    return week_start(d) + timedelta(days=6)


def week_dates(start: date) -> list[date]:
    """The seven dates (Sun..Sat) for a week beginning at `start`."""
    return [start + timedelta(days=i) for i in range(7)]


def parse_workout_date(text: str, reference: date) -> date:
    """Parse a user-entered workout date. Accepts YYYY-MM-DD (preferred) plus a
    few conveniences like M/D and M/D/YYYY. `reference` supplies the year when
    it's omitted. Raises ValueError if nothing matches."""
    s = text.strip()
    if not s:
        raise ValueError("empty date")
    try:
        return date.fromisoformat(s)
    except ValueError:
        pass
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%m/%d"):
        try:
            d = datetime.strptime(s, fmt).date()
        except ValueError:
            continue
        if fmt == "%m/%d":
            d = d.replace(year=reference.year)
        return d
    raise ValueError(f"Unrecognized date: {text!r}")


def parse_days(text: str) -> list[int]:
    """Parse '  mon, Wed friday' or '1 3 5' -> [1, 3, 5]. Raises ValueError."""
    if not text or not text.strip():
        return []
    tokens = [t for t in text.replace(",", " ").split() if t]
    result: set[int] = set()
    for tok in tokens:
        key = tok.strip().lower()
        if key not in _NAME_TO_IDX:
            raise ValueError(f"Unrecognized day: {tok!r}")
        result.add(_NAME_TO_IDX[key])
    return sorted(result)


def days_to_str(days: list[int]) -> str:
    """Store a list of day indices as a comma-separated string."""
    return ",".join(str(d) for d in sorted(set(days)))


def str_to_days(text: str | None) -> list[int]:
    """Read the stored comma-separated string back into a list of indices."""
    if not text:
        return []
    return sorted({int(x) for x in text.split(",") if x.strip().isdigit()})


def format_days(days: list[int]) -> str:
    """Human-friendly, e.g. [1,3,5] -> 'Mon, Wed, Fri'; [] -> 'none set'."""
    if not days:
        return "none set"
    return ", ".join(DAY_NAMES[d][:3] for d in sorted(set(days)))


def days_input_str(days: list[int]) -> str:
    """Like format_days but returns '' for empty, for pre-filling a text field."""
    if not days:
        return ""
    return ", ".join(DAY_NAMES[d][:3] for d in sorted(set(days)))
