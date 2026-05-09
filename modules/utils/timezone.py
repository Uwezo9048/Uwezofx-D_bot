from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def get_timezone(timezone_name=None):
    name = str(timezone_name or "").strip()
    if name:
        try:
            return ZoneInfo(name), name
        except ZoneInfoNotFoundError:
            pass
    local_tz = datetime.now().astimezone().tzinfo
    local_name = getattr(local_tz, "key", None) or datetime.now().astimezone().tzname() or "Local"
    return local_tz, local_name


def now(timezone_name=None):
    tz, _ = get_timezone(timezone_name)
    return datetime.now(tz)


def format_now(fmt="%H:%M:%S", timezone_name=None):
    return now(timezone_name).strftime(fmt)


def format_epoch(timestamp, fmt="%Y-%m-%d %H:%M:%S", timezone_name=None, include_tz=False):
    try:
        ts = int(float(timestamp))
    except (TypeError, ValueError):
        return ""
    if ts <= 0:
        return ""
    tz, tz_name = get_timezone(timezone_name)
    text = datetime.fromtimestamp(ts, tz).strftime(fmt)
    return f"{text} {tz_name}" if include_tz else text
