import os
from pathlib import Path
from src.common import env_loader

def test_missing_env_is_safe(monkeypatch):
    monkeypatch.setattr(env_loader,"ROOT",Path(".does-not-exist")); env_loader.load_project_env()

def test_env_loads_without_overriding_process(monkeypatch,tmp_path):
    (tmp_path/".env").write_text("TIMELYGPT_ENABLED=true\nTIMELYGPT_MODEL=file-model\nTIMELYGPT_API_KEY=example\n",encoding="utf-8")
    monkeypatch.setattr(env_loader,"ROOT",tmp_path); monkeypatch.setenv("TIMELYGPT_MODEL","process-model"); monkeypatch.delenv("TIMELYGPT_ENABLED",raising=False); monkeypatch.delenv("TIMELYGPT_API_KEY",raising=False)
    env_loader.load_project_env(); assert os.environ["TIMELYGPT_MODEL"]=="process-model" and os.environ["TIMELYGPT_ENABLED"]=="true" and os.environ["TIMELYGPT_API_KEY"]=="example"

def test_invalid_lines_are_ignored(monkeypatch,tmp_path):
    (tmp_path/".env").write_text("not valid\nTIMELYGPT_ENABLED=false\n",encoding="utf-8"); monkeypatch.setattr(env_loader,"ROOT",tmp_path); monkeypatch.delenv("TIMELYGPT_ENABLED",raising=False); env_loader.load_project_env(); assert os.environ["TIMELYGPT_ENABLED"]=="false"

def test_example_has_no_secret_values():
    text=Path(".env.example").read_text(encoding="utf-8"); assert "TIMELYGPT_API_KEY=" in text and "사용자의_실제" not in text

def test_ignore_rules():
    import subprocess
    assert subprocess.run(["git","check-ignore",".env"],capture_output=True,text=True).returncode==0
    assert subprocess.run(["git","check-ignore",".env.local"],capture_output=True,text=True).returncode==0
    assert subprocess.run(["git","check-ignore",".env.example"],capture_output=True,text=True).returncode!=0
