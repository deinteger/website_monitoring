from datetime import date
from src.common.retention import expired_report_dirs

def test_retention_selects_only_old_dated_report_directories(tmp_path):
    for name in ("2026-01-01","2026-08-25","latest","other"):(tmp_path/name).mkdir()
    assert [x.name for x in expired_report_dirs(tmp_path,keep_days=30,today=date(2026,8,26))] == ["2026-01-01"]
