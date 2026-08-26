from pathlib import Path

from run_all import main


def test_dry_run_validates_config_without_writing_state(tmp_path: Path, capsys) -> None:
    assert main(["--dry-run", "--config-dir", "config", "--state-dir", str(tmp_path)]) == 0
    assert "검증 완료" in capsys.readouterr().out
    assert list(tmp_path.iterdir()) == []


def test_rejects_max_urls_above_config_limit(tmp_path: Path, capsys) -> None:
    assert main(["--max-urls", "11", "--state-dir", str(tmp_path)]) == 2
    assert "--max-urls" in capsys.readouterr().out
