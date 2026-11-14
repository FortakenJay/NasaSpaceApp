"""HTTP API: the single server layer. The frontend reaches data ONLY through these routes, and these
routes reach the database ONLY through marswalk.db.repo.

    GET  /api/health                         -> {ok, version, site}
    GET  /api/site                           -> site metadata + stops (stops from the DB)              [works]
    POST /api/stops                          -> save a stop added on the map {lat, lon, name?} (code U1, U2, ...)
    PATCH/DELETE /api/stops/{stop_id}        -> move, rename or remove a stop added on the map (403 for science stops)
    GET  /api/stops/{stop_id}/observations   -> field log for a stop, newest first                      [works]
    POST /api/stops/{stop_id}/observations   -> add {note, author?, sample_id?}                         [works]
    GET  /api/plans                          -> saved plans, newest first                               [works]
    POST /api/plans                          -> save a plan request {name?, cost, order, stop_ids}      [works]
    GET  /api/plans/{plan_id}                -> one saved plan                                          [works]
    POST /api/plan                           -> compute a route {cost?, order?, stop_ids? | points?}; plans over
                                                site stops are persisted (status "computed")             [works]
    GET  /api/walkback?lat&lon&elapsed_h     -> walk home from any point + whether consumables cover it [works]
    GET  /api/layers                         -> available overlays ([] until the terrain is fetched)    [works]
    GET  /api/layers/{name}.png              -> overlay PNG; safezone takes ?elapsed_h=                 [works]
    GET  /api/status                         -> space-weather GO / CAUTION / NO-GO (DONKI + RAD)        [works]
    GET  /api/sources                        -> external API use: per-feed state, cache savings, request budget
    POST /api/sources/refresh                -> ask NASA again now (ignores cache and back-off)

Terrain routes answer 409 until `marswalk fetch` has cached the DTM. Stages that aren't built yet answer
501 {"milestone": "Mx", "detail": ...}.
"""
from __future__ import annotations

import os
import threading
from collections.abc import Iterator
from typing import Annotated, Literal

import numpy as np
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from marswalk import __version__
from marswalk.config import PROJECT_ROOT, EVAConfig, SiteConfig, load_dotenv, load_eva, load_site
from marswalk.db import repo
from marswalk.db.engine import DEFAULT_URL, make_engine, make_session_factory
from marswalk.export.payload import plan_payload, site_payload

DEFAULT_SITE = "configs/sites/gale_boxwork.toml"
DEFAULT_EVA = "configs/eva/artemis_default.toml"
LAYER_NAMES = ("hillshade", "slope5", "roughness", "ti", "nogo", "safezone")

CostName = Literal["metabolic", "weighted"]
OrderName = Literal["fixed", "optimize"]


class PointIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-360, le=360)
    name: str = Field(default="", max_length=100)
    work_time_min: float | None = Field(default=None, ge=0, le=600)


class StopIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-360, le=360)
    name: str = Field(default="", max_length=200)
    work_time_min: float | None = Field(default=None, ge=0, le=600)


class StopPatch(BaseModel):
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-360, le=360)
    name: str | None = Field(default=None, max_length=200)
    work_time_min: float | None = Field(default=None, ge=0, le=600)


class PlanRequest(BaseModel):
    cost: CostName | None = None
    order: OrderName | None = None
    stop_ids: list[str] | None = None   # subset / custom order; default = all site stops
    points: list[PointIn] | None = Field(default=None, max_length=8)   # click-to-plan: ad-hoc stops instead of stop_ids


class SavePlanRequest(BaseModel):
    name: str = Field(default="", max_length=200)
    cost: CostName
    order: OrderName
    stop_ids: list[str] = Field(min_length=1)


class ObservationIn(BaseModel):
    note: str = Field(min_length=1, max_length=4000)
    author: str = Field(default="crew", min_length=1, max_length=100)
    sample_id: str | None = Field(default=None, max_length=64)


def _not_built(milestone: str, err: Exception) -> JSONResponse:
    return JSONResponse(status_code=501, content={"milestone": milestone, "detail": str(err)})


def get_session(request: Request) -> Iterator[Session]:
    with request.app.state.sessions() as session:
        yield session


DB = Annotated[Session, Depends(get_session)]


def create_app(site_path: str = DEFAULT_SITE, eva_path: str = DEFAULT_EVA, db_url: str = DEFAULT_URL,
               warm: bool = False) -> FastAPI:
    load_dotenv()
    site: SiteConfig = load_site(site_path)
    eva: EVAConfig = load_eva(eva_path)
    app = FastAPI(title="MarsWalk Traverse Planner API", version=__version__)
    app.state.sessions = make_session_factory(make_engine(db_url))
    with app.state.sessions() as s:
        repo.seed_site(s, site)
    app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
                       allow_methods=["GET", "POST", "PATCH", "DELETE"], allow_headers=["*"])

    @app.exception_handler(repo.NotFound)
    def _not_found(_: Request, exc: repo.NotFound):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(repo.NotAllowed)
    def _not_allowed(_: Request, exc: repo.NotAllowed):
        return JSONResponse(status_code=403, content={"detail": str(exc)})

    @app.get("/api/health")
    def health():
        return {"ok": True, "version": __version__, "site": site.id, "project_root": str(PROJECT_ROOT)}

    # --- site & stops (DB) ------------------------------------------------------------------------
    @app.get("/api/site")
    def get_site(db: DB):
        from marswalk.route.plan import usable_budgets
        limits = {"usable_h": round(usable_budgets(eva)["time_s"] / 3600.0, 2),
                  "max_duration_h": float(eva.eva["max_duration_h"]),
                  "reserve_frac": float(eva.eva["walkback_reserve_frac"]),
                  "time_margin_factor": float(eva.eva.get("time_margin_factor", 1.0)),
                  "max_distance_from_rover_m": float(eva.eva["max_distance_from_rover_m"])}
        return {**site_payload(site, repo.list_stops(db, site.id)), "eva": limits,
                "api_version": __version__, "project_root": str(PROJECT_ROOT)}

    def _ground(lat: float, lon: float) -> float | None:
        """Elevation at a point the crew wants to stop at. 422 if the spot is off the mapped terrain or
        off limits; None if the terrain is not fetched yet (the stop is then saved unchecked)."""
        from marswalk.layers.stack import build_stack
        from marswalk.route.astar import snap
        try:
            with lock:
                stack = build_stack(site, eva)
        except FileNotFoundError:
            return None
        rc = snap(stack, stack.grid.latlon_to_rc(lat, lon))
        if rc is None:
            raise HTTPException(422, "That spot is off limits (too steep or too rough) or outside the terrain that has trusted 1 m data. "
                                     "Turn on “Off limits” to see where walking is allowed.")
        return float(stack.elevation_m[rc])

    @app.post("/api/stops", status_code=201)
    def add_stop(body: StopIn, db: DB):
        work = body.work_time_min if body.work_time_min is not None else float(eva.eva.get("default_work_time_min", 0))
        return repo.add_stop(db, site.id, lat=body.lat, lon=body.lon, name=body.name.strip(), work_time_min=work,
                             dtm_z_m=_ground(body.lat, body.lon))

    @app.patch("/api/stops/{stop_id}")
    def update_stop(stop_id: str, body: StopPatch, db: DB):
        moved = body.lat is not None and body.lon is not None
        return repo.update_stop(db, site.id, stop_id, lat=body.lat if moved else None, lon=body.lon if moved else None,
                                name=(body.name or "").strip() or None, work_time_min=body.work_time_min,
                                dtm_z_m=_ground(body.lat, body.lon) if moved else None)

    @app.delete("/api/stops/{stop_id}")
    def delete_stop(stop_id: str, db: DB):
        repo.delete_stop(db, site.id, stop_id)
        return {"deleted": stop_id}

    @app.get("/api/stops/{stop_id}/observations")
    def list_observations(stop_id: str, db: DB):
        return repo.list_observations(db, site.id, stop_id)

    @app.post("/api/stops/{stop_id}/observations", status_code=201)
    def add_observation(stop_id: str, body: ObservationIn, db: DB):
        return repo.add_observation(db, site.id, stop_id, note=body.note.strip(), author=body.author.strip(),
                                    sample_id=(body.sample_id or "").strip() or None)

    # --- saved plans (DB) -------------------------------------------------------------------------
    @app.get("/api/plans")
    def list_plans(db: DB):
        return repo.list_plans(db, site.id)

    @app.post("/api/plans", status_code=201)
    def save_plan(body: SavePlanRequest, db: DB):
        return repo.create_plan(db, site.id, cost_model=body.cost, stop_order=body.order,
                                stop_ids=body.stop_ids, name=body.name.strip())

    @app.get("/api/plans/{plan_id}")
    def get_plan(plan_id: str, db: DB):
        return repo.get_plan(db, plan_id)

    # --- terrain pipeline -------------------------------------------------------------------------
    lock = threading.RLock()
    fields: dict[tuple, object] = {}

    def terrain():
        """The LayerStack, or 409 when `marswalk fetch` has not cached the DTM yet."""
        from marswalk.layers.stack import build_stack
        try:
            with lock:
                return build_stack(site, eva)
        except FileNotFoundError as e:
            raise HTTPException(409, str(e)) from e

    def walkback(stack, cost: str):
        """Reverse cost field from the rover for one cost model (cached; a few seconds on first use)."""
        from marswalk.route.astar import snap
        from marswalk.route.plan import walkback_field
        key = (id(stack), cost)
        with lock:
            if key not in fields:
                rc = snap(stack, stack.grid.latlon_to_rc(site.start.lat, site.start.lon))
                if rc is None:
                    raise HTTPException(409, "the EVA start is outside the terrain window or in a no-go area")
                fields.clear()
                fields[key] = walkback_field(stack, eva, rc, cost)
            return fields[key]

    @app.post("/api/plan")
    def compute_plan(req: PlanRequest, db: DB):
        from marswalk.config import Stop
        from marswalk.route.plan import PlanError, build_plan
        stack = terrain()
        cost = req.cost or eva.cost_model
        points = None
        if req.points:
            points = [Stop(id=f"P{i + 1}", name=pt.name or f"Point {i + 1}", lat=pt.lat, lon=pt.lon,
                           work_time_min=pt.work_time_min if pt.work_time_min is not None
                           else float(eva.eva.get("default_work_time_min", 0))) for i, pt in enumerate(req.points)]
        adhoc = points is not None
        if not adhoc:
            # Stops come from the DB, so stops the crew added on the map plan exactly like the science stops.
            saved = {s["id"]: s for s in repo.list_stops(db, site.id) if s["kind"] != "start"}
            ids = req.stop_ids if req.stop_ids is not None else list(saved)
            unknown = [i for i in ids if i not in saved]
            if unknown:
                raise HTTPException(422, f"unknown stops {unknown}")
            if not ids:
                raise HTTPException(422, "Choose at least one stop to visit.")
            points = [Stop(id=i, name=saved[i]["name"], lat=saved[i]["lat"], lon=saved[i]["lon"],
                           dtm_z_m=saved[i]["dtm_z_m"], work_time_min=saved[i]["work_time_min"],
                           science=saved[i]["science"]) for i in ids]
        try:
            plan = build_plan(site, eva, stack, cost, points=points, order=req.order, back=walkback(stack, cost))
        except PlanError as e:
            raise HTTPException(422, str(e)) from e
        result = plan_payload(plan, stack)
        if not adhoc:           # plans over saved stops are stored; ad-hoc points are not
            saved = repo.create_plan(db, site.id, cost_model=cost, stop_order=req.order or eva.route.get("stop_order", "fixed"),
                                     stop_ids=plan.order or [p.id for p in points], result=result)
            result = {**result, "plan_id": saved["id"]}
        return result

    @app.get("/api/walkback")
    def get_walkback(lat: float, lon: float, cost: CostName | None = None, elapsed_h: float = 0.0):
        """Click-to-check: the walk home from any point, and whether the remaining consumables cover it."""
        from marswalk.route.astar import snap
        from marswalk.route.plan import usable_budgets
        stack = terrain()
        back = walkback(stack, cost or eva.cost_model)
        rc = snap(stack, stack.grid.latlon_to_rc(lat, lon))
        if rc is None or not back.reached(rc):
            return {"reachable": False, "safe": False, "route": None}
        cells = back.trace(rc)
        lats, lons = stack.grid.rc_to_latlon_many([c[0] for c in cells], [c[1] for c in cells])
        margin = float(eva.eva.get("time_margin_factor", 1.0))
        t_min = float(back.time_s[rc]) * margin / 60.0
        left_min = usable_budgets(eva)["time_s"] / 60.0 - elapsed_h * 60.0
        return {"reachable": True, "safe": t_min <= left_min, "walkback_min": round(t_min, 1),
                "walkback_kj": round(float(back.energy_kj[rc]) * margin, 1), "margin_min": round(left_min - t_min, 1),
                "route": {"type": "Feature", "properties": {"kind": "walkback"},
                          "geometry": {"type": "LineString",
                                       "coordinates": [[round(float(lo), 7), round(float(la), 7)] for la, lo in zip(lats, lons)]}}}

    @app.get("/api/layers")
    def list_layers():
        from marswalk.layers import render
        try:
            stack = terrain()
        except HTTPException:
            return []   # terrain not fetched yet: the app shows the basemap only
        return render.layer_list(stack, has_ti=bool(np.isfinite(stack.ti).any()))

    @app.get("/api/layers/{name}.png")
    def get_layer(name: str, elapsed_h: float = 0.0, cost: CostName | None = None):
        from marswalk.layers import render
        from marswalk.layers.stack import raw_stamp
        from marswalk.sources.fetch import cache_dir
        if name not in LAYER_NAMES:
            raise HTTPException(404, f"unknown layer {name!r}")
        stack = terrain()
        if name == "safezone":
            back = walkback(stack, cost or eva.cost_model)
            return Response(render.safezone_png(render.safezone_fraction(back, eva, elapsed_h,
                                                                            step=render.overlay_step(stack.shape))), media_type="image/png",
                            headers={"Cache-Control": "max-age=600"})
        stamp = raw_stamp(site)
        png = cache_dir(site) / f"{name}-{stamp}.png"
        if not png.exists():
            png.parent.mkdir(parents=True, exist_ok=True)
            png.write_bytes(render.layer_png(stack, name))
        return Response(png.read_bytes(), media_type="image/png", headers={"Cache-Control": "max-age=300"})

    # --- external APIs (all through sources.api_client.ApiClient) -----------------------------------
    key_env = site.spaceweather.get("api_key_env", "NASA_API_KEY")

    def _api_key() -> str:
        return os.environ.get(key_env) or "DEMO_KEY"

    def _client():
        from marswalk.sources.api_client import get_client
        from marswalk.sources.fetch import data_root
        return get_client(data_root() / "cache" / "api")

    def _status(force: bool = False) -> dict:
        from marswalk.spaceweather.status import current_status
        st = current_status(site.spaceweather, float(eva.eva["max_duration_h"]), _api_key(), client=_client(), force=force)
        return {**st.as_dict(), "eva_duration_h": float(eva.eva["max_duration_h"]),
                "dose_equiv_msv_per_day": site.spaceweather.get("rad_dose_equivalent_msv_per_day")}

    def _sources() -> dict:
        """What MarsWalk asked NASA for, what it is reusing, and how many requests that saved."""
        from marswalk.spaceweather.status import FEEDS
        snap = _client().snapshot()
        for f in snap["feeds"]:
            f["label"] = FEEDS.get(f["name"], {}).get("label", f["name"])
            f["required"] = bool(FEEDS.get(f["name"], {}).get("required"))
        return {**snap, "key": "personal" if os.environ.get(key_env) else "demo", "key_env": key_env}

    @app.get("/api/status")
    def get_status():
        """Space-weather go/no-go (DONKI + RAD baseline). Answers within about 10 s with what it has."""
        return _status()

    @app.get("/api/sources")
    def get_sources():
        return _sources()

    @app.post("/api/sources/refresh")
    def refresh_sources():
        """Ask NASA again now, ignoring the cache and any back-off (the "Ask NASA again" button)."""
        return {"status": _status(force=True), "sources": _sources()}

    if warm:
        # Build the terrain stack and the walk-home field in the background, so the first click is not the slow one.
        def _warm():
            try:
                walkback(terrain(), eva.cost_model)
            except Exception:  # noqa: BLE001 - e.g. terrain not fetched yet; the routes report it when asked
                pass
        threading.Thread(target=_warm, name="marswalk-warmup", daemon=True).start()

    return app
