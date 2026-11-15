"""A small TOML writer for generated site configs (tomllib only reads).

Supported: str, int, float, bool, lists of scalars, nested dicts (written as [tables]) and lists of dicts
(written as [[arrays of tables]]). That covers every site config. Round-trip is tested against tomllib.
"""
from __future__ import annotations

import json
import math


def _key(k: str) -> str:
    return k if k.replace("_", "").replace("-", "").isalnum() else json.dumps(k)


def _scalar(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if not math.isfinite(v):
            raise ValueError("TOML has no NaN/inf in site configs")
        return repr(v)
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)    # JSON string escapes are valid TOML basic strings
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_scalar(x) for x in v) + "]"
    raise TypeError(f"cannot write {type(v).__name__} to TOML")


def _is_table_list(v) -> bool:
    return isinstance(v, (list, tuple)) and len(v) > 0 and all(isinstance(x, dict) for x in v)


def _emit(d: dict, path: list[str], out: list[str]) -> None:
    scalars = [(k, v) for k, v in d.items() if not isinstance(v, dict) and not _is_table_list(v)]
    for k, v in scalars:
        out.append(f"{_key(k)} = {_scalar(v)}")
    for k, v in d.items():
        if isinstance(v, dict):
            out.append("")
            out.append("[" + ".".join(_key(p) for p in [*path, k]) + "]")
            _emit(v, [*path, k], out)
        elif _is_table_list(v):
            for item in v:
                out.append("")
                out.append("[[" + ".".join(_key(p) for p in [*path, k]) + "]]")
                _emit(item, [*path, k], out)


def dumps(data: dict, header: str = "") -> str:
    out: list[str] = [f"# {line}" for line in header.splitlines()] if header else []
    _emit(data, [], out)
    return "\n".join(out).strip() + "\n"
