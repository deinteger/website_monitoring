"""Load only the project-root .env without overriding process environment."""
from __future__ import annotations
import os
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]

def load_project_env() -> None:
    path=ROOT/".env"
    if not path.is_file(): return
    try:
        from dotenv import load_dotenv
        load_dotenv(path, override=False)
        return
    except ImportError:
        pass
    # Safe minimal fallback for environments before dependency installation.
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line=line.strip()
            if not line or line.startswith("#") or "=" not in line: continue
            key,value=line.split("=",1); key=key.strip()
            if key and key.isidentifier() and key not in os.environ:
                os.environ[key]=value.strip().strip('"').strip("'")
    except (OSError, UnicodeError):
        return
