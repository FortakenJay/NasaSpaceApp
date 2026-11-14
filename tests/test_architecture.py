"""Boundary checks: the database is reachable only through marswalk.db (repo), and the frontend
calls the network only from its central API module."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_only_db_package_imports_sqlalchemy():
    offenders = []
    for py in (ROOT / "src" / "marswalk").rglob("*.py"):
        rel = py.relative_to(ROOT / "src" / "marswalk").as_posix()
        if rel.startswith("db/"):
            continue
        text = py.read_text(encoding="utf-8")
        # the API may type-hint a Session for dependency injection, but never query
        if rel == "api/app.py":
            assert not re.search(r"\bselect\(|\.query\(|\.execute\(|\.scalars\(", text), rel
            continue
        if re.search(r"^\s*(from|import)\s+sqlalchemy", text, re.M):
            offenders.append(rel)
    assert offenders == []


def test_frontend_network_calls_only_in_api_module():
    offenders = []
    for f in (ROOT / "frontend" / "src").rglob("*.ts*"):
        rel = f.relative_to(ROOT / "frontend" / "src").as_posix()
        if rel.startswith("api/"):
            continue
        if re.search(r"\bfetch\(|XMLHttpRequest|axios", f.read_text(encoding="utf-8")):
            offenders.append(rel)
    assert offenders == []
