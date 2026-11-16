"""Which public data covers a point on Mars: the HiRISE stereo DTM catalog, plus the products derived from it.

The PDS HiRISE DTM index (DTMCUMINDEX.TAB, ~8 MB) lists every released DTM and its orthoimages, one row per file,
with the valid-data footprint as four corner points. Checked 2026-11-15:
- 1,370 DTMs, about 0.1 % of Mars. 1,213 are equirectangular, 164 polar stereographic. Map scales 1 m and 2 m.
- CORNER1..4 trace the skewed stereo strip (the valid data), not the raster rectangle, so "is this point inside" is
  a fair first test. The job still checks the elevation at the point itself (strip edges are ragged).
- The index's projection fields are rounded (MAP_SCALE 1.01) and its PROJECTION_CENTER_LONGITUDE can be wrong, so the
  exact grid is always read from the DTM file itself (GDAL, a header read), never built from the index.

Everything here is pure (no network) except ensure_index(), so it is tested against a small fixture index.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import math
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

PDS_ROOT = "https://hirise-pds.lpl.arizona.edu/PDS/"
INDEX_TAB_URL = PDS_ROOT + "INDEX/DTMCUMINDEX.TAB"
INDEX_LBL_URL = PDS_ROOT + "INDEX/DTMCUMINDEX.LBL"
CATALOG_FORMAT = 1

THEMIS_TI_URL = ("https://asc-astropedia.s3.us-west-2.amazonaws.com/Mars/Odyssey/THEMIS-Global-Thermal-Inertia-Mosaic/"
                 "Quantitative-32-Bit/THEMIS_TI_Mosaic_Quant_{tile}_100mpp.cub")
# Global photo tiles (geographic tiling, 512 px tiles: resolution 180/512/2^z deg per px; verified 2026-11-15 from
# MapServer?f=json: origin (-180, 90), GCS_Mars_2000_Sphere). HiRISE only where HiRISE imaged; CTX everywhere.
HIRISE_GLOBAL_TILES = "https://astro.arcgis.com/arcgis/rest/services/OnMars/HiRISE/MapServer/tile/{z}/{y}/{x}"
CTX_GLOBAL_TILES = "https://astro.arcgis.com/arcgis/rest/services/OnMars/CTX/MapServer/tile/{z}/{y}/{x}"
THEMIS_DAYIR_TILES = ("https://trek.nasa.gov/tiles/Mars/EQ/THEMIS_DayIR_ControlledMosaics_100m_v2_oct2018/1.0.0/"
                      "default/default028mm/{z}/{y}/{x}.png")

MAX_SCALE_M = 1.1          # "1 m" DTMs (index scale 1.00 / 1.01); 2 m DTMs are listed but not supported yet
BASE_HALF_M = 3000.0       # analysis window: the Base +- 3 km (2 km walk limit + 1 km margin), as at Gale
R_MARS = 3396190.0


@dataclass
class DtmEntry:
    product_id: str
    url: str
    folder: str
    scale_m: float
    projection: str
    corners: list[list[float]]          # [[lat, lon], x4], lon in -180..180
    rationale: str = ""
    version: str = ""
    orthos: dict[str, str] = field(default_factory=dict)   # "RED_C" -> url, "RED_A", "IRB_C", ...


def _wrap(lon: float) -> float:
    """Longitude into -180..180."""
    return (lon + 180.0) % 360.0 - 180.0


# --- parsing --------------------------------------------------------------------------------------------------------

def column_names(lbl_text: str) -> list[str]:
    """Column names, in order, from a PDS3 TABLE label (`OBJECT = COLUMN ... NAME = X`)."""
    names = re.findall(r"OBJECT\s*=\s*COLUMN.*?NAME\s*=\s*\"?([A-Z0-9_]+)\"?", lbl_text, re.S)
    if not names:
        raise ValueError("no COLUMN objects in the index label")
    return names


def parse(lbl_text: str, tab_lines) -> list[DtmEntry]:
    """DTM entries from the index, with each DTM's orthoimages attached (same PDS folder)."""
    names = column_names(lbl_text)
    rows = [dict(zip(names, (c.strip() for c in r))) for r in csv.reader(tab_lines, skipinitialspace=True) if r]
    dtms: dict[str, DtmEntry] = {}
    left_obs: dict[str, str] = {}
    orthos: dict[str, list[tuple[str, str, str]]] = {}     # folder -> [(observation, kind, url)]
    for r in rows:
        spec = r.get("FILE_NAME_SPECIFICATION", "")
        folder = spec.rsplit("/", 1)[0]
        kind = r.get("DATA_TYPE", "").upper()
        if kind == "DTM":
            try:
                corners = [[float(r[f"CORNER{i}_LATITUDE"]), _wrap(float(r[f"CORNER{i}_LONGITUDE"]))] for i in (1, 2, 3, 4)]
                scale = float(r["MAP_SCALE"])
            except (KeyError, ValueError):
                continue
            pid = r["PRODUCT_ID"]
            prev = dtms.get(folder)
            # one DTM per folder; if a folder lists several versions keep the highest
            if prev is None or r.get("PRODUCT_VERSION_ID", "") > prev.version:
                dtms[folder] = DtmEntry(product_id=pid, url=PDS_ROOT + spec, folder=folder, scale_m=scale,
                                        projection=r.get("MAP_PROJECTION_TYPE", "").upper(), corners=corners,
                                        rationale=r.get("RATIONALE_DESC", ""), version=r.get("PRODUCT_VERSION_ID", ""))
                left_obs[folder] = r.get("LEFT_OBSERVATION_ID", "")
        elif kind == "ORTHOIMAGE":
            m = re.search(r"/((?:ESP|PSP)_\d+_\d+)_(RED|IRB)_([AC])_\d+_ORTHO", spec)
            if m:
                orthos.setdefault(folder, []).append((m.group(1), f"{m.group(2)}_{m.group(3)}", PDS_ROOT + spec))
    for folder, e in dtms.items():
        # A folder holds orthos of BOTH stereo images; prefer the DTM's left observation (the one Gale's hand-made
        # config uses), then any.
        left = left_obs.get(folder, "")
        found: dict[str, str] = {}
        for obs, k, url in sorted(orthos.get(folder, []), key=lambda t: t[0] != left):
            found.setdefault(k, url)
        e.orthos = found
    return list(dtms.values())


# --- the cached catalog -----------------------------------------------------------------------------------------------

def catalog_dir() -> Path:
    from marswalk.sources.fetch import data_root
    return data_root() / "cache" / "catalog"


def ensure_index(max_age_days: float = 30.0, log: Callable[[str], None] = print, force: bool = False) -> list[DtmEntry]:
    """The catalog, downloading and parsing the PDS index when missing or older than `max_age_days`.
    A failed refresh falls back to the cached copy."""
    from marswalk.sources.raster import download
    d = catalog_dir()
    cat = d / "catalog.json"
    fresh = cat.exists() and (dt.datetime.now().timestamp() - cat.stat().st_mtime) < max_age_days * 86400
    if fresh and not force:
        return load_catalog(cat)
    try:
        log("catalog: downloading the HiRISE DTM index (about 8 MB) ...")
        for name in ("DTMCUMINDEX.LBL", "DTMCUMINDEX.TAB"):
            (d / name).unlink(missing_ok=True)
        lbl = download(INDEX_LBL_URL, d / "DTMCUMINDEX.LBL", timeout=120)
        tab = download(INDEX_TAB_URL, d / "DTMCUMINDEX.TAB", timeout=300)
        with open(tab, encoding="latin-1", newline="") as f:
            entries = parse(lbl.read_text(encoding="latin-1"), f)
        tmp = cat.with_suffix(".part")
        tmp.write_text(json.dumps({"format": CATALOG_FORMAT, "built_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                                   "entries": [asdict(e) for e in entries]}))
        tmp.replace(cat)
        log(f"catalog: {len(entries)} DTMs")
        return entries
    except Exception:
        if cat.exists():
            log("catalog: refresh failed, using the cached copy")
            return load_catalog(cat)
        raise


def load_catalog(path: Path) -> list[DtmEntry]:
    raw = json.loads(Path(path).read_text())
    return [DtmEntry(**e) for e in raw["entries"]]


# --- geometry -------------------------------------------------------------------------------------------------------

def _local_xy(lat: float, lon: float, lat0: float, lon0: float) -> tuple[float, float]:
    """Metres east/north of (lat0, lon0), equirectangular around the reference (fine for a strip a few km wide)."""
    k = math.pi / 180.0 * R_MARS
    return _wrap(lon - lon0) * k * math.cos(math.radians(lat0)), (lat - lat0) * k


def contains(e: DtmEntry, lat: float, lon: float) -> bool:
    """Is (lat, lon) inside the DTM's footprint quadrilateral? Safe across the 0/360 and +-180 seams."""
    pts = [_local_xy(c[0], c[1], lat, lon) for c in e.corners]
    inside = False
    for i in range(4):
        (x1, y1), (x2, y2) = pts[i], pts[(i + 1) % 4]
        if (y1 > 0) != (y2 > 0) and 0 < (x2 - x1) * (0 - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def edge_distance_m(e: DtmEntry, lat: float, lon: float) -> float:
    """Distance from (lat, lon) to the nearest footprint edge (m)."""
    pts = [_local_xy(c[0], c[1], lat, lon) for c in e.corners]
    best = math.inf
    for i in range(4):
        (x1, y1), (x2, y2) = pts[i], pts[(i + 1) % 4]
        dx, dy = x2 - x1, y2 - y1
        t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, -(x1 * dx + y1 * dy) / (dx * dx + dy * dy)))
        best = min(best, math.hypot(x1 + t * dx, y1 + t * dy))
    return best


def supported(e: DtmEntry) -> tuple[bool, str]:
    """Can a Base be planned on this DTM today? (decision, plain-language reason when not)"""
    if e.projection != "EQUIRECTANGULAR":
        return False, "polar terrain (polar stereographic) is not supported yet"
    if e.scale_m > MAX_SCALE_M:
        return False, f"{e.scale_m:g} m terrain is too coarse for walking routes (1 m needed)"
    lons = [c[1] for c in e.corners]
    if max(lons) - min(lons) > 180.0:
        return False, "terrain that crosses the 180 degree meridian is not supported yet"
    if "RED_C" not in e.orthos:
        return False, "this terrain has no 1 m photo in the archive"
    return True, ""


@dataclass
class Candidate:
    entry: DtmEntry
    edge_m: float


def choose(entries: list[DtmEntry], lat: float, lon: float) -> list[Candidate]:
    """Supported DTMs that contain the point, best first: finest scale, then the point farthest from the strip edge
    (so the 2 km walk ring fits), then the newest version."""
    lon = _wrap(lon)
    cands = [Candidate(e, edge_distance_m(e, lat, lon)) for e in entries if supported(e)[0] and contains(e, lat, lon)]
    cands.sort(key=lambda c: c.entry.version, reverse=True)             # stable sorts: last key applied wins first
    cands.sort(key=lambda c: (round(c.entry.scale_m, 1), -c.edge_m))
    return cands


def ti_tile(lat: float, lon: float) -> str | None:
    """THEMIS quantitative TI mosaic tile name for a point, e.g. Gale -> "30S120E". None poleward of +-60."""
    lat_lo = math.floor(lat / 30.0) * 30
    if lat_lo < -60 or lat_lo > 30:
        return None
    lon_lo = int(math.floor((lon % 360.0) / 60.0) * 60) % 360
    return f"{abs(lat_lo):02d}{'S' if lat_lo < 0 else 'N'}{lon_lo:03d}E"


def base_bbox(lat: float, lon: float, entry: DtmEntry | None = None, half_m: float = BASE_HALF_M) -> dict:
    """The analysis window: the Base +- half_m, clipped to the DTM footprint's bounding box."""
    dlat = math.degrees(half_m / R_MARS)
    dlon = dlat / max(math.cos(math.radians(lat)), 1e-6)
    lon = _wrap(lon)
    box = {"lat_min": lat - dlat, "lat_max": lat + dlat, "lon_min": lon - dlon, "lon_max": lon + dlon}
    if entry is not None:
        lats = [c[0] for c in entry.corners]
        lons = [lon + _wrap(c[1] - lon) for c in entry.corners]
        box = {"lat_min": max(box["lat_min"], min(lats)), "lat_max": min(box["lat_max"], max(lats)),
               "lon_min": max(box["lon_min"], min(lons)), "lon_max": min(box["lon_max"], max(lons))}
    return {k: round(v, 6) for k, v in box.items()}


def estimate_bytes(bbox: dict, scale_m: float) -> int:
    """Rough disk use of one Base: DTM + ortho GeoTIFF windows (float32, deflate), the ortho JP2, overlay PNGs."""
    k = math.pi / 180.0 * R_MARS
    lat = (bbox["lat_min"] + bbox["lat_max"]) / 2
    h = (bbox["lat_max"] - bbox["lat_min"]) * k
    w = (bbox["lon_max"] - bbox["lon_min"]) * k * math.cos(math.radians(lat))
    px = (h / scale_m + 200) * (w / scale_m + 200)
    return int(px * 4 * 0.7 + px * 4 * 0.5 + 45e6 + 50e6)


def footprints_geojson(entries: list[DtmEntry]) -> dict:
    """Every DTM footprint as a GeoJSON polygon (lon/lat), with whether a Base can be set there."""
    feats = []
    for e in entries:
        ok, why = supported(e)
        lon0 = e.corners[0][1]
        ring = [[round(lon0 + _wrap(c[1] - lon0), 5), round(c[0], 5)] for c in e.corners]
        feats.append({"type": "Feature", "id": e.product_id,
                      "properties": {"product_id": e.product_id, "scale_m": e.scale_m, "supported": ok, "reason": why,
                                     "name": e.rationale},
                      "geometry": {"type": "Polygon", "coordinates": [ring + [ring[0]]]}})
    return {"type": "FeatureCollection", "features": feats}
