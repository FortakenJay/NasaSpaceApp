"""Which Bases exist and which one is in focus.

Gale (the site config the server was started with) is the built-in Base: always there, never deleted. Every other
Base lives in data_root()/bases/<id>/:
    base.json   metadata: name, status (creating | ready | failed | interrupted), point, terrain product, alignment,
                radiation estimate, warnings, size on disk, error
    site.toml   the generated site config (load_site reads it like Gale's)
    stops.json  the start (the rover at the Base) and no science stops
Its downloaded data sits where every site's does: raw_dir(site) and cache_dir(site).

The focused Base is a database setting ("focused_base"), so it survives restarts. Database rows (stops, plans, field
notes) are reached only through db.repo.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import secrets
import shutil
from pathlib import Path

from marswalk.config import SiteConfig, load_site
from marswalk.db import repo

FOCUS_KEY = "focused_base"
BUILTIN = "builtin"
USER = "user"


def bases_dir() -> Path:
    from marswalk.sources.fetch import data_root
    return data_root() / "bases"


def new_id(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:32] or "base"
    return f"b_{slug}_{secrets.token_hex(3)}"


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def dir_size(*paths: Path) -> int:
    total = 0
    for p in paths:
        if p.is_dir():
            total += sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
        elif p.is_file():
            total += p.stat().st_size
    return total


class BaseRegistry:
    def __init__(self, builtin_site: SiteConfig, sessions):
        self.builtin = builtin_site
        self.sessions = sessions

    # --- reading ---------------------------------------------------------------------------------
    def builtin_info(self) -> dict:
        from marswalk.spaceweather.radiation import rates
        gy, sv, est, note = rates(self.builtin.spaceweather)
        s = self.builtin
        return {"id": s.id, "name": s.name, "kind": BUILTIN, "status": "ready", "lat": s.start.lat, "lon": s.start.lon,
                "bbox": dict(s.bbox), "product_id": s.dtm.get("id"), "scale_m": None, "deletable": False,
                "alignment": {"source": "measured", "quality": "good"} if s.dtm.get("basemap_offset_m") else None,
                "radiation": {"gcr_mgy_per_day": gy, "dose_eq_msv_per_day": sv, "estimate": est, "note": note},
                "warnings": [], "created_at": None, "error": None}

    def _read(self, base_dir: Path) -> dict | None:
        try:
            info = json.loads((base_dir / "base.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        info.setdefault("kind", USER)
        info["deletable"] = True
        return info

    def list(self) -> list[dict]:
        users = [i for d in sorted(bases_dir().glob("*/")) if (i := self._read(d))] if bases_dir().exists() else []
        users.sort(key=lambda i: i.get("created_at") or "")
        return [self.builtin_info(), *users]

    def info(self, base_id: str) -> dict:
        if base_id == self.builtin.id:
            return self.builtin_info()
        info = self._read(bases_dir() / base_id) if _safe(base_id) else None
        if info is None:
            raise repo.NotFound(f"base {base_id!r}")
        return info

    def site(self, base_id: str) -> SiteConfig:
        """The site config of a ready Base."""
        if base_id == self.builtin.id:
            return self.builtin
        info = self.info(base_id)
        if info.get("status") != "ready":
            raise repo.NotAllowed(f"base {base_id!r} is not ready ({info.get('status')})")
        return load_site(bases_dir() / base_id / "site.toml")

    # --- writing ---------------------------------------------------------------------------------
    def write_info(self, info: dict) -> None:
        d = bases_dir() / info["id"]
        d.mkdir(parents=True, exist_ok=True)
        clean = {k: v for k, v in info.items() if k != "deletable"}
        tmp = d / "base.json.part"
        tmp.write_text(json.dumps(clean, indent=1), encoding="utf-8")
        tmp.replace(d / "base.json")

    def focused_id(self) -> str:
        with self.sessions() as s:
            fid = repo.get_setting(s, FOCUS_KEY)
        if not fid or fid == self.builtin.id:
            return self.builtin.id
        try:
            return fid if self.info(fid).get("status") == "ready" else self.builtin.id
        except repo.NotFound:
            return self.builtin.id

    def set_focus(self, base_id: str) -> SiteConfig:
        site = self.site(base_id)            # raises if missing or not ready
        with self.sessions() as s:
            repo.seed_site(s, site)
            repo.set_setting(s, FOCUS_KEY, base_id)
        return site

    def seed(self, base_id: str) -> None:
        with self.sessions() as s:
            repo.seed_site(s, self.site(base_id))

    def delete(self, base_id: str) -> None:
        """Delete a user Base: its files, downloaded data and database rows. Gale cannot be deleted."""
        if base_id == self.builtin.id:
            raise repo.NotAllowed("the built-in Base cannot be deleted")
        self.info(base_id)                    # 404 if unknown
        from marswalk.sources.fetch import data_root
        with self.sessions() as s:
            repo.delete_site(s, base_id)
            if repo.get_setting(s, FOCUS_KEY) == base_id:
                repo.set_setting(s, FOCUS_KEY, self.builtin.id)
        for d in (bases_dir() / base_id, data_root() / "raw" / base_id, data_root() / "cache" / base_id):
            shutil.rmtree(d, ignore_errors=True)

    def startup(self) -> None:
        """After a restart: jobs that were running are 'interrupted'; ready Bases are in the database."""
        for info in self.list()[1:]:
            if info.get("status") == "creating":
                info["status"], info["error"] = "interrupted", "the server stopped while this Base was downloading"
                self.write_info(info)
            elif info.get("status") == "ready":
                try:
                    self.seed(info["id"])
                except Exception:  # noqa: BLE001 - a broken Base must not stop the server
                    pass

    def size_bytes(self, base_id: str) -> int:
        from marswalk.sources.fetch import data_root
        return dir_size(bases_dir() / base_id, data_root() / "raw" / base_id, data_root() / "cache" / base_id)


def _safe(base_id: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9_]{1,64}", base_id))
