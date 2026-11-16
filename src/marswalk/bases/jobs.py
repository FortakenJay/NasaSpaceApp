"""The background job that creates a Base: find the terrain, download it, line it up, place the rover.

One job runs at a time (a local, single-user server). Its state is kept in memory for the progress bar and written to
the Base's base.json after every step, so a restart shows it as "interrupted" with a Resume button.

Steps (weights are the share of the progress bar):
  lookup    the HiRISE catalog: which 1 m stereo DTM covers the point (catalog.choose)
  probe     the DTM's exact grid from its own header, and elevation data at the point itself (strips have ragged
            no-data edges that the index footprint cannot show)
  dtm       the DTM window (the Base +- 3 km), strip by strip
  ti        THEMIS thermal inertia (optional: none poleward of +-60 deg)
  ortho     the HiRISE 1 m photo of the same strip, cropped onto the DTM grid
  align     how far the terrain sits from the map photo (layers.align); weak -> the file's own coordinates + a warning
  place     elevation, radiation estimate, and the rover moved onto walkable ground within 100 m
"""
from __future__ import annotations

import json
import shutil
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from marswalk.bases import tomlw
from marswalk.bases.registry import BaseRegistry, bases_dir, new_id, now_iso
from marswalk.config import EVAConfig, SiteConfig, load_site
from marswalk.sources import catalog

STEPS: list[tuple[str, str, float]] = [
    ("lookup", "Find HiRISE stereo terrain", 0.02),
    ("probe", "Check the terrain at the Base", 0.03),
    ("dtm", "Download the 1 m terrain", 0.45),
    ("ti", "Download thermal inertia", 0.03),
    ("ortho", "Download the 1 m photo", 0.30),
    ("align", "Line the terrain up with the map photo", 0.12),
    ("place", "Place the rover and save", 0.05),
]
PLACE_RADIUS_M = 100.0       # the rover may move this far to reach walkable ground
GALE_UNCERTAINTY = {"vertical_sigma_m": 0.3, "registration_sigma_m": 0.5, "draws": 20, "noise_corr_px": 1.0}


class JobError(Exception):
    """A plain-language reason the Base could not be created."""


class Busy(Exception):
    pass


@dataclass
class JobState:
    base_id: str
    name: str
    lat: float
    lon: float
    status: str = "running"          # running | ready | failed | cancelled
    step: str = "lookup"
    steps: list[dict] = field(default_factory=lambda: [{"key": k, "label": lb, "state": "pending", "detail": ""}
                                                       for k, lb, _ in STEPS])
    fraction: float = 0.0
    started_at: float = field(default_factory=time.time)
    error: str | None = None

    def as_dict(self) -> dict:
        return {"base_id": self.base_id, "name": self.name, "lat": self.lat, "lon": self.lon, "status": self.status,
                "step": self.step, "steps": self.steps, "fraction": round(self.fraction, 3),
                "elapsed_s": round(time.time() - self.started_at, 1), "error": self.error}


def _weights() -> dict[str, tuple[float, float]]:
    out, acc = {}, 0.0
    for k, _, w in STEPS:
        out[k] = (acc, w)
        acc += w
    return out


class JobRunner:
    def __init__(self, registry: BaseRegistry, eva: EVAConfig, on_ready: Callable[[str], None] | None = None,
                 log: Callable[[str], None] | None = None):
        self.registry, self.eva, self.on_ready = registry, eva, on_ready
        self.log = log or (lambda _m: None)
        self._lock = threading.Lock()
        self._state: JobState | None = None
        self._thread: threading.Thread | None = None
        self._cancel = threading.Event()

    # --- control ---------------------------------------------------------------------------------
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def snapshot(self) -> dict | None:
        with self._lock:
            return self._state.as_dict() if self._state else None

    def forget(self, base_id: str) -> None:
        """Drop a finished job's report once its Base is deleted (so no one is offered to focus a Base that is gone)."""
        with self._lock:
            if self._state is not None and self._state.base_id == base_id and not self.running():
                self._state = None

    def start(self, lat: float, lon: float, name: str = "", product_id: str | None = None,
              resume_id: str | None = None, background: bool = True) -> dict:
        with self._lock:
            if self.running():
                raise Busy("another Base is being created; wait for it or cancel it")
            if resume_id:
                info = self.registry.info(resume_id)
                lat, lon, name, product_id = info["lat"], info["lon"], info["name"], info.get("product_id")
                base_id = resume_id
            else:
                name = (name or "").strip() or "New Base"
                base_id = new_id(name)
            self._cancel = threading.Event()
            self._state = JobState(base_id=base_id, name=name, lat=float(lat), lon=float(lon))
            if background:
                self._thread = threading.Thread(target=self._run, args=(product_id,), name="marswalk-base-job", daemon=True)
                self._thread.start()
        if not background:
            self._run(product_id)
        return self.snapshot() or {}

    def cancel(self, base_id: str | None = None) -> bool:
        st = self._state
        if st is None or not self.running() or (base_id and st.base_id != base_id):
            return False
        self._cancel.set()
        return True

    # --- progress --------------------------------------------------------------------------------
    def _set(self, key: str, state: str, detail: str = "", frac: float = 0.0) -> None:
        w = _weights()
        with self._lock:
            st = self._state
            if st is None:
                return
            for s in st.steps:
                if s["key"] == key:
                    s["state"], s["detail"] = state, detail or s["detail"]
            if state == "running":
                st.step = key
            start, weight = w[key]
            st.fraction = max(st.fraction, start + weight * (1.0 if state in ("done", "skipped", "warning") else frac))

    def _progress(self, key: str):
        return lambda f: self._set(key, "running", frac=float(f))

    # --- the job ---------------------------------------------------------------------------------
    def _run(self, product_id: str | None) -> None:
        st = self._state
        assert st is not None
        info = {"id": st.base_id, "name": st.name, "kind": "user", "status": "creating", "lat": st.lat, "lon": st.lon,
                "created_at": now_iso(), "warnings": [], "error": None}
        try:
            self._create(st, info, product_id)
            with self._lock:
                st.status, st.fraction = "ready", 1.0
            if self.on_ready:
                self.on_ready(st.base_id)
        except Exception as e:  # noqa: BLE001 - every failure becomes a message for the user
            from marswalk.sources.raster import Cancelled
            if isinstance(e, Cancelled) or self._cancel.is_set():
                self._discard(st.base_id)
                with self._lock:
                    st.status, st.error = "cancelled", "cancelled"
                return
            msg = str(e) if isinstance(e, JobError) else f"{type(e).__name__}: {e}"
            with self._lock:
                st.status, st.error = "failed", msg
                for s in st.steps:
                    if s["state"] == "running":
                        s["state"] = "failed"
            info.update(status="failed", error=msg)
            if (bases_dir() / st.base_id).exists() or info.get("product_id"):
                self.registry.write_info(info)

    def _discard(self, base_id: str) -> None:
        from marswalk.sources.fetch import data_root
        for d in (bases_dir() / base_id, data_root() / "raw" / base_id, data_root() / "cache" / base_id):
            shutil.rmtree(d, ignore_errors=True)

    def _check(self) -> None:
        if self._cancel.is_set():
            from marswalk.sources.raster import Cancelled
            raise Cancelled("cancelled")

    def _create(self, st: JobState, info: dict, product_id: str | None) -> None:
        from marswalk.sources import raster as rs
        from marswalk.sources.fetch import fetch_site, raw_dir

        # 1. lookup
        self._set("lookup", "running")
        entries = catalog.ensure_index(log=self.log)
        cands = catalog.choose(entries, st.lat, st.lon)
        if product_id:
            cands = [c for c in cands if c.entry.product_id == product_id] or cands
        if not cands:
            raise JobError("No 1 m HiRISE stereo terrain covers this point. Click inside one of the outlined areas.")
        entry = cands[0].entry
        info.update(product_id=entry.product_id, scale_m=entry.scale_m, terrain_name=entry.rationale,
                    bbox=catalog.base_bbox(st.lat, st.lon, entry))
        self.registry.write_info(info)
        self._set("lookup", "done", entry.product_id)
        self._check()

        # 2. probe: exact grid + data at the point
        self._set("probe", "running")
        grid = rs.open_grid(entry.url)
        vals, _ = rs.read_point_window(entry.url, st.lat, st.lon, half_px=24)
        if np.isfinite(vals).mean() < 0.5:
            raise JobError("This spot is on the empty edge of the stereo strip. Pick a point further inside the outline.")
        self._set("probe", "done", f"{grid.width} x {grid.height} px at {grid.pixel_m:.2f} m")
        self._check()

        site = self._site(st, info, entry, grid, offset=None, alignment=None, spaceweather={})

        # 3-5. dtm, ti, ortho (fetch_site reports progress per product)
        steps_seen: set[str] = set()

        def prog(name: str, f: float) -> None:
            if name not in steps_seen:
                steps_seen.add(name)
            self._set(name, "running", frac=f)
        self._set("dtm", "running")
        fetch_site(site, log=self.log, progress=prog, cancel=self._cancel)
        manifest = json.loads((raw_dir(site) / "manifest.json").read_text())["products"]
        self._set("dtm", "done")
        ti_err = (manifest.get("thermal_inertia") or {}).get("error")
        if "thermal_inertia" not in site.products:
            self._set("ti", "skipped", "no THEMIS coverage poleward of 60 deg")
            info["warnings"].append("No thermal inertia here (THEMIS covers +-60 deg latitude): no sand flag.")
        elif ti_err:
            self._set("ti", "warning", "failed")
            info["warnings"].append("Thermal inertia could not be downloaded: no sand flag.")
        else:
            self._set("ti", "done")
        ortho_err = (manifest.get("ortho_1m") or {}).get("error")
        self._set("ortho", "warning" if ortho_err else "done", "failed" if ortho_err else "")
        if ortho_err:
            info["warnings"].append("The 1 m photo could not be downloaded; the map still shows the global HiRISE mosaic.")
        self._check()

        # 6. align
        self._set("align", "running")
        alignment = self._align(site, raw_dir(site), info)
        self._set("align", "done" if alignment["quality"] in ("good", "fair") else "warning",
                  f"{alignment['quality']}: {alignment['north_m']:+.1f} m N, {alignment['east_m']:+.1f} m E"
                  if alignment["source"] != "file" else "using the file's own coordinates")
        self._check()

        # 7. place the rover, elevation, radiation
        self._set("place", "running")
        lat, lon, z, moved_m, elev = self._place(raw_dir(site), alignment, st.lat, st.lon)
        if moved_m > 0.5:
            info["warnings"].append(f"The rover was moved {moved_m:.0f} m to the nearest walkable ground.")
        from marswalk.spaceweather.radiation import estimate
        rad = estimate(elev)
        sw = {**rad, "donki_base_url": "https://api.nasa.gov/DONKI", "api_key_env": "NASA_API_KEY"}
        site = self._site(st, info, entry, grid, offset={"east": alignment["east_m"], "north": alignment["north_m"]},
                          alignment=alignment, spaceweather=sw, start=(lat, lon, z))
        info.update(status="ready", base_lat=lat, base_lon=lon, elevation_m=round(elev, 1), alignment=alignment,
                    radiation={"gcr_mgy_per_day": rad["rad_gcr_dose_mgy_per_day"],
                               "dose_eq_msv_per_day": rad["rad_dose_equivalent_msv_per_day"], "estimate": True,
                               "note": rad["rad_estimate"]["note"]},
                    size_bytes=self.registry.size_bytes(st.base_id), error=None)
        self.registry.write_info(info)
        self.registry.seed(st.base_id)
        self._set("place", "done", f"{lat:.5f}, {lon:.5f}")

    def realign(self, base_id: str) -> dict:
        """Measure a ready Base's alignment again (e.g. after a failed or weak first try) and re-place its rover.
        Runs in the caller's thread; no download."""
        from marswalk.geo import GeoGrid
        from marswalk.sources.fetch import raw_dir
        info = self.registry.info(base_id)
        site = self.registry.site(base_id)
        entry = next((e for e in catalog.ensure_index(log=self.log) if e.product_id == info.get("product_id")), None)
        if entry is None:
            raise JobError(f"terrain {info.get('product_id')} is no longer in the catalog")
        st = JobState(base_id=base_id, name=info["name"], lat=float(info["lat"]), lon=float(info["lon"]))
        self._state = st
        info["warnings"] = [w for w in info.get("warnings", []) if "lined up" not in w and "rover was moved" not in w]
        # measure around the clicked point with the terrain unshifted (the stops file still holds the old rover spot)
        site_click = self._site(st, info, entry, GeoGrid.from_product(site.dtm), offset=None, alignment=None,
                                spaceweather=site.spaceweather)
        alignment = self._align(site_click, raw_dir(site), info)
        lat, lon, z, moved_m, _ = self._place(raw_dir(site), alignment, st.lat, st.lon)
        if moved_m > 0.5:
            info["warnings"].append(f"The rover was moved {moved_m:.0f} m to the nearest walkable ground.")
        self._site(st, info, entry, GeoGrid.from_product(site.dtm),
                   offset={"east": alignment["east_m"], "north": alignment["north_m"]}, alignment=alignment,
                   spaceweather=site.spaceweather, start=(lat, lon, z))
        info.update(base_lat=lat, base_lon=lon, alignment=alignment)
        self.registry.write_info(info)
        self.registry.seed(base_id)
        return alignment

    # --- pieces ------------------------------------------------------------------------------------
    def _site(self, st: JobState, info: dict, entry, grid, offset: dict | None, alignment: dict | None,
              spaceweather: dict, start: tuple[float, float, float] | None = None) -> SiteConfig:
        """Write the Base's site.toml + stops.json and load them (so the job runs exactly what the app will run)."""
        d = bases_dir() / st.base_id
        d.mkdir(parents=True, exist_ok=True)
        lat, lon, z = start if start else (st.lat, st.lon, None)
        stops = {"site": st.base_id, "crs": "Mars 2000 planetocentric, east-positive",
                 "start": {"id": "H1", "name": "Rover (EVA start and finish)", "lat": round(lat, 7), "lon": round(lon, 7),
                           "dtm_z_m": None if z is None else round(z, 1), "kind": "start"}, "stops": []}
        (d / "stops.json").write_text(json.dumps(stops, indent=1), encoding="utf-8")
        t = grid.transform
        dtm = {"id": entry.product_id, "url": entry.url, "format": "pds_img", "crs": grid.crs.to_wkt(),
               "transform": [t.a, t.b, t.c, t.d, t.e, t.f], "width": grid.width, "height": grid.height,
               "uncertainty": dict(GALE_UNCERTAINTY)}
        if offset and (offset["east"] or offset["north"]):
            dtm["basemap_offset_m"] = {"east": round(float(offset["east"]), 2), "north": round(float(offset["north"]), 2)}
        if alignment:
            dtm["alignment"] = {k: v for k, v in alignment.items() if v is not None}
            dtm["uncertainty"]["registration_sigma_m"] = max(0.5, float(alignment.get("spread_m") or 0.5))
        products: dict = {"dtm": dtm,
                          "ortho_1m": {"id": entry.orthos["RED_C"].rsplit("/", 1)[-1].removesuffix(".JP2"),
                                       "url": entry.orthos["RED_C"], "format": "jp2", "same_grid_as": "dtm"},
                          "basemap_tiles": {"url_template": catalog.HIRISE_GLOBAL_TILES, "max_zoom": 17, "tile_size": 512},
                          "context_tiles": [
                              {"name": "THEMIS daytime infrared (global, 100 m)", "url_template": catalog.THEMIS_DAYIR_TILES,
                               "max_zoom": 9, "tile_size": 256},
                              {"name": "CTX mosaic (global, about 20 m)", "url_template": catalog.CTX_GLOBAL_TILES,
                               "max_zoom": 11, "tile_size": 512}]}
        tile = catalog.ti_tile(st.lat, st.lon)
        if tile:
            products["thermal_inertia"] = {"id": f"THEMIS_TI_Mosaic_Quant_{tile}_100mpp",
                                           "url": catalog.THEMIS_TI_URL.format(tile=tile), "format": "isis3",
                                           "sand_ti_threshold": 300.0}
        cfg = {"site": {"id": st.base_id, "name": st.name, "stops_file": str((d / "stops.json").resolve()),
                        "bbox": info["bbox"]},
               "body": {"radius_m": 3396190.0, "gravity_mps2": 3.71},
               "products": products}
        if spaceweather:
            cfg["spaceweather"] = spaceweather
        (d / "site.toml").write_text(tomlw.dumps(cfg, f"Generated by MarsWalk for Base {st.name!r} ({now_iso()}).\n"
                                                      f"Terrain: {entry.product_id} ({entry.rationale})"),
                                     encoding="utf-8")
        return load_site(d / "site.toml")

    def _align(self, site: SiteConfig, raw, info: dict) -> dict:
        """Offset of the terrain from the map photo. Falls back to the file's own coordinates with a warning."""
        try:
            from marswalk.layers import align
            res = align.auto(site, raw, cancel=self._cancel, progress=self._progress("align"))
        except Exception as e:  # noqa: BLE001 - alignment is best effort
            from marswalk.sources.raster import Cancelled
            if isinstance(e, Cancelled):
                raise
            res = {"source": "file", "quality": "none", "east_m": 0.0, "north_m": 0.0, "error": f"{type(e).__name__}: {e}"}
        if res.get("quality") not in ("good", "fair", "coarse"):
            res.update(source="file", east_m=0.0, north_m=0.0)
            info["warnings"].append("The terrain could not be lined up with the map photo, so it uses the HiRISE file's "
                                    "own coordinates: routes and overlays may sit tens of metres off the photo.")
        elif res["quality"] == "coarse":
            info["warnings"].append("The terrain was lined up against 20 m CTX imagery only (about +-10-20 m).")
        res.setdefault("measured_at", now_iso())
        return res

    def _place(self, raw, alignment: dict, lat: float, lon: float) -> tuple[float, float, float, float, float]:
        """(lat, lon, elevation) of the nearest walkable cell within PLACE_RADIUS_M of the click (photo frame), how far
        the rover moved, and the median elevation within 200 m (for radiation)."""
        from marswalk.geo import Raster, ground_distance_m
        from marswalk.layers import coverage, terrain
        from marswalk.layers.stack import nogo_mask
        from marswalk.sources.raster import read_geotiff
        dem = coverage.shifted(read_geotiff(raw / "dtm.tif"),
                               {"east": alignment.get("east_m", 0.0), "north": alignment.get("north_m", 0.0)})
        r, c = dem.grid.latlon_to_rc(lat, lon)
        k = int(400 / dem.grid.pixel_m)
        r0, c0 = max(r - k, 0), max(c - k, 0)
        r1, c1 = min(r + k + 1, dem.shape[0]), min(c + k + 1, dem.shape[1])
        if r1 <= r0 or c1 <= c0:
            raise JobError("The Base point is outside the downloaded terrain.")
        sub = Raster(np.ascontiguousarray(dem.data[r0:r1, c0:c1]), dem.grid.window(r0, c0, r1 - r0, c1 - c0))
        s1, s5, rough = terrain.slope(sub, 1.0).data, terrain.slope(sub, 5.0).data, terrain.roughness(sub).data
        nogo = nogo_mask(s1, s5, rough, sub.data, self.eva.hazards)
        rr, cc = r - r0, c - c0
        ok_r, ok_c = np.nonzero(~nogo)
        if ok_r.size == 0:
            raise JobError("There is no walkable ground near this point. Pick a flatter spot.")
        d2 = (ok_r - rr) ** 2 + (ok_c - cc) ** 2
        i = int(np.argmin(d2))
        if float(np.sqrt(d2[i])) * sub.grid.pixel_m > PLACE_RADIUS_M:
            raise JobError(f"No walkable ground within {PLACE_RADIUS_M:.0f} m of this point (too steep or rough). "
                           "Pick a flatter spot.")
        pr, pc = int(ok_r[i]), int(ok_c[i])
        plat, plon = sub.grid.rc_to_latlon(pr, pc)
        moved = ground_distance_m(lat, lon, plat, plon, 3396190.0)
        kk = int(200 / sub.grid.pixel_m)
        near = sub.data[max(pr - kk, 0):pr + kk + 1, max(pc - kk, 0):pc + kk + 1]
        elev = float(np.nanmedian(near)) if np.isfinite(near).any() else float(sub.data[pr, pc])
        return plat, plon, float(sub.data[pr, pc]), moved, elev
