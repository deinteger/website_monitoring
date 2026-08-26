"""Conservative retention policy for generated outputs, never state files."""
from __future__ import annotations
from datetime import date, timedelta
from pathlib import Path

def expired_report_dirs(output_root, keep_days=90, today=None):
    today=today or date.today(); cutoff=today-timedelta(days=keep_days); root=Path(output_root)
    return [p for p in root.iterdir() if p.is_dir() and p.name != "latest" and _date(p.name) and _date(p.name) < cutoff]
def _date(name):
    try: return date.fromisoformat(name)
    except ValueError: return None
