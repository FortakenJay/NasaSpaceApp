"""Load site and EVA configuration (TOML) and the per-site stops file (JSON).

Implemented: this is the contract every other module reads from.
"""
from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

def _project_root() -> Path:
    """The checkout that holds configs/. An editable install lives in src/, so parents[2] is the
    checkout. On Vercel the imported package is in site-packages, and the checkout is the process
    working directory."""
    here = Path(__file__).resolve()
    for p in (Path.cwd(), *here.parents):
        if (p / "configs" / "sites").is_dir():
            return p
    return here.parents[2]


PROJECT_ROOT = _project_root()


@dataclass(frozen=True)
class Stop:
    id: str
    name: str
    lat: float
    lon: float
    dtm_z_m: float | None = None
    work_time_min: float = 0.0
    science: str = ""
    kind: str = "stop"  # "start" | "stop"


@dataclass(frozen=True)
class SiteConfig:
    id: str
    name: str
    bbox: dict[str, float]
    body: dict[str, float]
    products: dict[str, dict]
    spaceweather: dict
    start: Stop
    stops: tuple[Stop, ...]
    path: Path

    @property
    def dtm(self) -> dict:
        return self.products["dtm"]

    @property
    def merged_dem(self) -> dict | None:
        """The wider USGS merged DEM, if the site uses one (`[products.merged_dem]` with enabled = true)."""
        m = self.products.get("merged_dem")
        return m if m and m.get("enabled", True) else None


@dataclass(frozen=True)
class EVAConfig:
    eva: dict
    suit: dict
    route: dict
    hazards: dict
    cost: dict = field(default_factory=dict)
    path: Path | None = None
    comms: dict = field(default_factory=dict)
    consumables: dict = field(default_factory=dict)

    @property
    def cost_model(self) -> str:
        return self.cost.get("model", "metabolic")


def load_dotenv(path: Path | None = None) -> list[str]:
    """Read KEY=VALUE lines from the project's .env (git-ignored) into the environment. Variables that are
    already set win. Returns the names it set. This is where NASA_API_KEY lives, so it is typed once."""
    import os
    p = path or PROJECT_ROOT / ".env"
    if not p.exists():
        return []
    names = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.removeprefix("export ").strip(), v.strip().strip("'\"")
        if k and v and k not in os.environ:
            os.environ[k] = v
            names.append(k)
    return names


def _resolve(path: str | Path) -> Path:
    p = Path(path)
    return p if p.is_absolute() else PROJECT_ROOT / p


def load_stops(path: str | Path) -> tuple[Stop, tuple[Stop, ...]]:
    raw = json.loads(_resolve(path).read_text(encoding="utf-8"))
    s = raw["start"]
    start = Stop(id=s["id"], name=s["name"], lat=s["lat"], lon=s["lon"],
                 dtm_z_m=s.get("dtm_z_m"), kind="start")
    stops = tuple(
        Stop(id=x["id"], name=x["name"], lat=x["lat"], lon=x["lon"], dtm_z_m=x.get("dtm_z_m"),
             work_time_min=x.get("work_time_min", 0), science=x.get("science", ""))
        for x in raw["stops"]
    )
    return start, stops


def load_site(path: str | Path) -> SiteConfig:
    p = _resolve(path)
    raw = tomllib.loads(p.read_text(encoding="utf-8"))
    start, stops = load_stops(raw["site"]["stops_file"])
    return SiteConfig(
        id=raw["site"]["id"], name=raw["site"]["name"], bbox=raw["site"]["bbox"],
        body=raw["body"], products=raw["products"], spaceweather=raw.get("spaceweather", {}),
        start=start, stops=stops, path=p,
    )


def load_eva(path: str | Path) -> EVAConfig:
    p = _resolve(path)
    raw = tomllib.loads(p.read_text(encoding="utf-8"))
    return EVAConfig(eva=raw["eva"], suit=raw.get("suit", {}), route=raw["route"],
                     hazards=raw["hazards"], cost=raw.get("cost", {}), path=p, comms=raw.get("comms", {}),
                     consumables=raw.get("consumables", {}))
