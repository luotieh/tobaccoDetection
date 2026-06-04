def seconds_to_timestamp(seconds: float) -> str:
    seconds = max(0.0, float(seconds or 0.0))
    total_ms = int(round(seconds * 1000))
    ms = total_ms % 1000
    total_seconds = total_ms // 1000
    sec = total_seconds % 60
    minutes = (total_seconds // 60) % 60
    hours = total_seconds // 3600
    return f"{hours:02d}:{minutes:02d}:{sec:02d}.{ms:03d}"


def validate_time_range(start: float, end: float) -> bool:
    return start >= 0 and end >= 0 and end >= start

