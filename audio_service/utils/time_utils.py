def format_timestamp(seconds: float) -> str:
    total = int(seconds)
    ms = int(round((seconds - total) * 1000))
    return f"{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}.{ms:03d}"
