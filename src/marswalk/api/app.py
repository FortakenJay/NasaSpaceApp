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
    GET  /api/sim/terrain?step=              -> heights, off-limits mask and suit physics for the 3D simulator
    GET  /api/sim/texture.png?kind=&step=    -> ground texture for the simulator (photo | hazard)
    GET  /api/sim/fine.bin                   -> 1 m walk surface, roughness, sand, off-limits (gzip) for its physics
    GET  /api/sim/sun?start_utc=&hours=      -> Sun azimuth/elevation through the walk (Mars24)
    GET  /api/eink.png|.bin?...&lat&lon...   -> suit display; live position, walked_m, energy_kj, visited
    GET  /api/sources                        -> external API use: per-feed state, cache savings, request budget
    POST /api/sources/refresh                -> ask NASA again now (ignores cache and back-off)
    GET  /api/bases                          -> {focused, bases: [...], job}: every Base (Gale built in)
    POST /api/bases {lat, lon, name?, product_id?} -> 202: start downloading a new Base (one job at a time)
    GET  /api/bases/job                      -> the running or last job: steps, fraction, error
    POST /api/bases/{id}/cancel | /resume    -> stop the download / restart an interrupted or failed one
    POST /api/bases/focus {id}               -> make a ready Base the one the planner works on
    DELETE /api/bases/{id}                   -> delete a Base, its data and its database rows (403 for Gale)
    GET  /api/catalog/footprints             -> every HiRISE stereo DTM footprint (GeoJSON, gzip)
    GET  /api/catalog/lookup?lat&lon         -> what a Base there would use: terrain, window, size, warnings

Every route works on the focused Base. Its caches live on one Focus object that is replaced when the focus moves,
so nothing computed for one Base is served for another.

Terrain routes answer 409 until `marswalk fetch` has cached the DTM. Stages that aren't built yet answer
501 {"milestone": "Mx", "detail": ...}.
"""
from __future__ import annotations

import os
import threading
from collections.abc import Iterator
from typing import Annotated, Literal

import numpy as np
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from marswalk import __version__
from marswalk.config import (
    PROJECT_ROOT,
    EVAConfig,
    SiteConfig,
    load_dotenv,
    load_eva,
    load_site,
)
from marswalk.db import repo
from marswalk.db.engine import DEFAULT_URL, make_engine, make_session_factory
from marswalk.export.payload import plan_payload, site_payload

DEFAULT_SITE = "configs/sites/gale_boxwork.toml"
DEFAULT_EVA = "configs/eva/artemis_default.toml"
LAYER_NAMES = ("hillshade", "slope5", "roughness", "ti", "nogo", "safezone", "radio", "shelter", "uncertain")

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


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    plan_id: str | None = None                 # the plan on screen (POST /api/plan returns its id)
    selected_stop_id: str | None = None        # "here", if a stop is selected on the map
    elapsed_h: float = Field(default=0.0, ge=0, le=24)   # "here" along the plan otherwise (step 4 slider)
    here_lat: float | None = None              # a walker's actual position (the simulator): overrides both
    here_lon: float | None = None
    visited: list[str] | None = None


class BaseIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-360, le=360)
    name: str = Field(default="", max_length=100)
    product_id: str | None = Field(default=None, max_length=80)


class FocusIn(BaseModel):
    id: str = Field(min_length=1, max_length=64)


class ObservationIn(BaseModel):
    note: str = Field(min_length=1, max_length=4000)
    author: str = Field(default="crew", min_length=1, max_length=100)
    sample_id: str | None = Field(default=None, max_length=64)


def get_session(request: Request) -> Iterator[Session]:
    with request.app.state.sessions() as session:
        yield session


DB = Annotated[Session, Depends(get_session)]


def create_app(site_path: str = DEFAULT_SITE, eva_path: str = DEFAULT_EVA, db_url: str = DEFAULT_URL,
               warm: bool = False) -> FastAPI:
    load_dotenv()
    builtin: SiteConfig = load_site(site_path)
    eva: EVAConfig = load_eva(eva_path)
    app = FastAPI(title="MarsWalk Traverse Planner API", version=__version__)
    app.state.sessions = make_session_factory(make_engine(db_url))
    with app.state.sessions() as s:
        repo.seed_site(s, builtin)
        # The file database (local serve, and a fresh /tmp on Vercel) gets the stored Gale route.
        # Tests pass sqlite:// and keep an empty plans table.
        if db_url == DEFAULT_URL:
            repo.seed_preview_plan(s, builtin.id)
    app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
                       allow_methods=["GET", "POST", "PATCH", "DELETE"], allow_headers=["*"])

    # --- Bases: one focused at a time; its caches live on its Focus object and go when the focus moves ----------------
    from marswalk.bases.jobs import Busy, JobRunner
    from marswalk.bases.registry import BaseRegistry

    class Focus:
        def __init__(self, site: SiteConfig):
            self.site = site
            self.fields: dict[tuple, object] = {}     # walk-home fields, radio, off-limits certainty
            self.sim_cache: dict = {}                 # simulator packages

    registry = BaseRegistry(builtin, app.state.sessions)
    registry.startup()
    try:
        focus = {"b": Focus(registry.site(registry.focused_id()))}
    except Exception:  # noqa: BLE001 - a broken Base falls back to the built-in one
        focus = {"b": Focus(builtin)}
    runner = JobRunner(registry, eva)
    app.state.registry, app.state.runner = registry, runner

    def F() -> Focus:
        return focus["b"]

    @app.exception_handler(repo.NotFound)
    def _not_found(_: Request, exc: repo.NotFound):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(repo.NotAllowed)
    def _not_allowed(_: Request, exc: repo.NotAllowed):
        return JSONResponse(status_code=403, content={"detail": str(exc)})

    @app.get("/api/health")
    def health():
        site = F().site
        return {"ok": True, "version": __version__, "site": site.id, "project_root": str(PROJECT_ROOT)}

    # --- site & stops (DB) ------------------------------------------------------------------------
    @app.get("/api/site")
    def get_site(db: DB):
        site = F().site
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
        site = F().site
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
        site = F().site
        work = body.work_time_min if body.work_time_min is not None else float(eva.eva.get("default_work_time_min", 0))
        return repo.add_stop(db, site.id, lat=body.lat, lon=body.lon, name=body.name.strip(), work_time_min=work,
                             dtm_z_m=_ground(body.lat, body.lon))

    @app.patch("/api/stops/{stop_id}")
    def update_stop(stop_id: str, body: StopPatch, db: DB):
        site = F().site
        moved = body.lat is not None and body.lon is not None
        return repo.update_stop(db, site.id, stop_id, lat=body.lat if moved else None, lon=body.lon if moved else None,
                                name=(body.name or "").strip() or None, work_time_min=body.work_time_min,
                                dtm_z_m=_ground(body.lat, body.lon) if moved else None)

    @app.delete("/api/stops/{stop_id}")
    def delete_stop(stop_id: str, db: DB):
        site = F().site
        repo.delete_stop(db, site.id, stop_id)
        return {"deleted": stop_id}

    @app.get("/api/stops/{stop_id}/observations")
    def list_observations(stop_id: str, db: DB):
        site = F().site
        return repo.list_observations(db, site.id, stop_id)

    @app.post("/api/stops/{stop_id}/observations", status_code=201)
    def add_observation(stop_id: str, body: ObservationIn, db: DB):
        site = F().site
        return repo.add_observation(db, site.id, stop_id, note=body.note.strip(), author=body.author.strip(),
                                    sample_id=(body.sample_id or "").strip() or None)

    # --- saved plans (DB) -------------------------------------------------------------------------
    @app.get("/api/plans")
    def list_plans(db: DB):
        site = F().site
        return repo.list_plans(db, site.id)

    @app.post("/api/plans", status_code=201)
    def save_plan(body: SavePlanRequest, db: DB):
        site = F().site
        return repo.create_plan(db, site.id, cost_model=body.cost, stop_order=body.order,
                                stop_ids=body.stop_ids, name=body.name.strip())

    @app.get("/api/plans/{plan_id}")
    def get_plan(plan_id: str, db: DB):
        return repo.get_plan(db, plan_id)

    # --- terrain pipeline -------------------------------------------------------------------------
    lock = threading.RLock()

    def terrain():
        """The LayerStack, or 409 when `marswalk fetch` has not cached the DTM yet."""
        site = F().site
        from marswalk.layers.stack import build_stack
        try:
            with lock:
                return build_stack(site, eva)
        except FileNotFoundError as e:
            raise HTTPException(409, str(e)) from e

    def walkback(stack, cost: str):
        """Reverse cost field from the rover for one cost model (cached; a few seconds on first use)."""
        site = F().site
        fields = F().fields
        from marswalk.route.astar import snap
        from marswalk.route.plan import walkback_field
        key = (id(stack), cost)
        with lock:
            if key not in fields:
                rc = snap(stack, stack.grid.latlon_to_rc(site.start.lat, site.start.lon))
                if rc is None:
                    raise HTTPException(409, "the EVA start is outside the terrain window or in a no-go area")
                for k in [k for k in fields if k[0] != id(stack) or k[1] not in ("radio", "uncertain")]:
                    del fields[k]
                fields[key] = walkback_field(stack, eva, rc, cost)
            return fields[key]

    def radio(stack):
        """Radio line of sight to the rover over the walk range (cached; under a second)."""
        site = F().site
        fields = F().fields
        from marswalk.route.astar import snap
        from marswalk.route.plan import radio_field
        key = (id(stack), "radio")
        with lock:
            if key not in fields:
                rc = snap(stack, stack.grid.latlon_to_rc(site.start.lat, site.start.lon))
                if rc is None:
                    raise HTTPException(409, "the EVA start is outside the terrain window or in a no-go area")
                for k in [k for k in fields if k[0] != id(stack)]:
                    del fields[k]
                fields[key] = radio_field(stack, eva, rc, float(site.body["radius_m"]))
            return fields[key]

    def uncertain(stack):
        """(off-limits frequency, window) over the walk area from perturbed terrain (cached; about 2 s)."""
        site = F().site
        fields = F().fields
        from marswalk.layers import uncertainty
        key = (id(stack), "uncertain")
        with lock:
            if key not in fields:
                win = uncertainty.walk_window(site, stack)
                fields[key] = (uncertainty.offlimits_frequency(stack, eva.hazards, win, site.dtm.get("uncertainty")), win)
            return fields[key]

    @app.post("/api/plan")
    def compute_plan(req: PlanRequest, db: DB):
        site = F().site
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
            plan = build_plan(site, eva, stack, cost, points=points, order=req.order, back=walkback(stack, cost),
                              radio=radio(stack), offlimits=uncertain(stack))
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
        site = F().site
        from marswalk.layers import render
        try:
            stack = terrain()
        except HTTPException:
            return []   # terrain not fetched yet: the app shows the basemap only
        from marswalk.layers import uncertainty
        layers = render.layer_list(stack, has_ti=bool(np.isfinite(stack.ti).any()),
                                   shelter_lead_min=float(eva.eva.get("sep_warning_lead_min", 30.0)))
        r0, r1, c0, c1 = uncertainty.walk_window(site, stack)
        lat_min, lon_min, lat_max, lon_max = stack.grid.window(r0, c0, r1 - r0, c1 - c0).bounds_latlon()
        sigma = float((site.dtm.get("uncertainty") or {}).get("vertical_sigma_m", 0.3))
        layers.append({"name": "Off-limits certainty", "key": "uncertain", "url": "/api/layers/uncertain.png",
                       "bounds": [lon_min, lat_min, lon_max, lat_max], "opacity": 0.6,
                       "note": (f"The off-limits test rerun on {int((site.dtm.get('uncertainty') or {}).get('draws', 20))} "
                                f"versions of the terrain, each within its {sigma:g} m stereo precision. Amber: off limits "
                                "in some versions only, so the map cannot be sure; red: in nearly all. Walk area only.")})
        # The Base and the data version go in every URL, so the browser never shows another Base's cached image.
        from marswalk.layers.stack import raw_stamp
        tag = f"b={site.id}&v={raw_stamp(site)}"
        return [{**ly, "url": f"{ly['url']}{'&' if '?' in ly['url'] else '?'}{tag}"} for ly in layers]

    @app.get("/api/layers/{name}.png")
    def get_layer(name: str, elapsed_h: float = 0.0, cost: CostName | None = None):
        site = F().site
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
        if name == "radio":
            return Response(render.radio_png(radio(stack)), media_type="image/png", headers={"Cache-Control": "max-age=600"})
        if name == "uncertain":
            from marswalk.layers import uncertainty
            return Response(uncertainty.png(uncertain(stack)[0]), media_type="image/png", headers={"Cache-Control": "max-age=600"})
        if name == "shelter":
            return Response(render.shelter_png(walkback(stack, cost or eva.cost_model), eva), media_type="image/png",
                            headers={"Cache-Control": "max-age=600"})
        stamp = raw_stamp(site)
        png = cache_dir(site) / f"{name}-{stamp}.png"
        if not png.exists():
            png.parent.mkdir(parents=True, exist_ok=True)
            png.write_bytes(render.layer_png(stack, name))
        return Response(png.read_bytes(), media_type="image/png", headers={"Cache-Control": "max-age=300"})

    # --- external APIs (all through sources.api_client.ApiClient) -----------------------------------
    key_env = builtin.spaceweather.get("api_key_env", "NASA_API_KEY")

    def _api_key() -> str:
        return os.environ.get(key_env) or "DEMO_KEY"

    def _client():
        from marswalk.sources.api_client import get_client
        from marswalk.sources.fetch import data_root
        return get_client(data_root() / "cache" / "api")

    def _status(force: bool = False) -> dict:
        site = F().site
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

    @app.post("/api/ask")
    def ask(body: AskIn, db: DB):
        """A question in plain words ("how far is S3 from here?", "how much oxygen?"), answered from the plan on screen,
        the terrain and the space-weather check. Returns the answer as text, as text for speech, and map highlights."""
        site = F().site
        from marswalk.ask import AskContext, answer
        plan, cost = None, eva.cost_model
        if body.plan_id:
            try:
                saved = repo.get_plan(db, body.plan_id)
                plan, cost = saved.get("result"), saved.get("cost_model") or cost
            except repo.NotFound:
                plan = None

        def stack():
            try:
                return terrain()
            except HTTPException:
                return None
        ctx = AskContext(site=site, eva=eva, stops=repo.list_stops(db, site.id), plan=plan, cost=cost,
                         selected_stop_id=body.selected_stop_id, elapsed_h=body.elapsed_h, stack=stack,
                         live=(body.here_lat, body.here_lon) if body.here_lat is not None and body.here_lon is not None else None,
                         visited=body.visited,
                         walkback=lambda st: walkback(st, cost), status=_status)
        return answer(body.question, ctx)

    # --- 3-D walk simulator ---------------------------------------------------------------------------

    def _sim_points(db) -> tuple[tuple[float, float], list[tuple[float, float]]]:
        site = F().site
        stops = repo.list_stops(db, site.id)
        start = next(s for s in stops if s["kind"] == "start")
        return (start["lat"], start["lon"]), [(s["lat"], s["lon"]) for s in stops if s["kind"] != "start"]

    @app.get("/api/sim/terrain")
    def sim_terrain(db: DB, step: int = Query(3, ge=1, le=10)):
        """The walk area as a height grid in local metres around the rover (x east, z south), for the simulator."""
        site = F().site
        sim_cache = F().sim_cache
        from marswalk import sim
        from marswalk.layers.stack import raw_stamp
        stack = terrain()
        (lat0, lon0), pts = _sim_points(db)
        key = ("terrain", raw_stamp(site), step, lat0, lon0, tuple(pts))
        if key not in sim_cache:
            sim_cache[key] = sim.terrain_package(site, eva, stack, lat0, lon0, pts, step=step, stamp=raw_stamp(site))
        return JSONResponse(sim_cache[key], headers={"Cache-Control": "no-cache"})

    @app.get("/api/sim/terrain.bin")
    def sim_terrain_bin(db: DB, step: int = Query(3, ge=1, le=10), v: str = ""):
        """The 3 m mesh's heights and off-limits bits (layout and frame in /api/sim/terrain). Sent gzip-compressed."""
        site = F().site
        sim_cache = F().sim_cache
        import gzip

        from marswalk import sim
        from marswalk.layers.stack import raw_stamp
        stack = terrain()
        (lat0, lon0), pts = _sim_points(db)
        key = ("terrain.bin", raw_stamp(site), step, lat0, lon0, tuple(pts))
        if key not in sim_cache:
            sim_cache[key] = gzip.compress(sim.terrain_bytes(stack, lat0, lon0, pts, step=step), compresslevel=5)
        return Response(sim_cache[key], media_type="application/octet-stream",
                        headers={"Content-Encoding": "gzip", "Cache-Control": "max-age=3600"})

    @app.get("/api/sim/fine.bin")
    def sim_fine(db: DB, v: str = ""):
        """The 1 m walking grid (walk surface, terrain, roughness, sand, off-limits, radio shadow) the simulator's
        physics reads; layout in /api/sim/terrain -> fine. Sent gzip-compressed."""
        site = F().site
        sim_cache = F().sim_cache
        import gzip

        from marswalk import sim
        from marswalk.layers.stack import raw_stamp
        stack = terrain()
        (lat0, lon0), pts = _sim_points(db)
        key = ("fine", raw_stamp(site), lat0, lon0, tuple(pts))
        if key not in sim_cache:
            sim_cache[key] = gzip.compress(sim.fine_bytes(stack, lat0, lon0, pts, radio=radio(stack)), compresslevel=5)
        return Response(sim_cache[key], media_type="application/octet-stream",
                        headers={"Content-Encoding": "gzip", "Cache-Control": "max-age=3600"})

    @app.get("/api/sim/sun")
    def sim_sun(db: DB, start_utc: str | None = None, hours: float = Query(10.0, gt=0, le=24)):
        """The Sun's azimuth and elevation through a walk at the rover, every 2 minutes (Mars24 algorithm). Without
        `start_utc` the walk starts at the next local mean solar time `start_lmst_h` (configs/eva) after now."""
        import datetime as dt

        from marswalk import sun
        (lat0, lon0), _ = _sim_points(db)
        if start_utc:
            try:
                start = dt.datetime.fromisoformat(start_utc)
            except ValueError as e:
                raise HTTPException(422, f"start_utc is not an ISO time: {start_utc!r}") from e
        else:
            start = sun.next_lmst(dt.datetime.now(dt.UTC), lon0, float(eva.eva.get("start_lmst_h", 9.0)))
        return sun.track(start, lat0, lon0, hours * 60.0)

    @app.get("/api/sim/texture.png")
    def sim_texture(db: DB, kind: str = Query("photo", pattern="^(photo|hazard)$"), step: int = Query(3, ge=1, le=10)):
        """The simulator's ground texture: the HiRISE photo in Mars colours, or the off-limits overlay."""
        site = F().site
        sim_cache = F().sim_cache
        from marswalk import sim
        from marswalk.layers.stack import raw_stamp
        stack = terrain()
        (lat0, lon0), pts = _sim_points(db)
        key = ("texture", kind, raw_stamp(site), step, lat0, lon0, tuple(pts))
        if key not in sim_cache:
            sim_cache[key] = sim.texture_png(site, stack, lat0, lon0, pts, kind=kind, step=step)
        return Response(sim_cache[key], media_type="image/png", headers={"Cache-Control": "max-age=3600"})

    # --- suit display (e-ink) -----------------------------------------------------------------------
    def _eink(plan_id: str | None, elapsed_h: float, db, live: dict | None = None):
        site = F().site
        from marswalk import eink
        if plan_id:
            try:
                saved = repo.get_plan(db, plan_id)
            except repo.NotFound as e:
                raise HTTPException(404, f"no plan {plan_id!r}") from e
        else:
            plans = [p for p in repo.list_plans(db, site.id, limit=5) if p.get("result")]
            if not plans:
                raise HTTPException(404, "No walk is planned yet. Plan one in the app (step 2) first.")
            saved = plans[0]
        cost = saved.get("cost_model") or eva.cost_model
        try:
            stack = terrain()
        except HTTPException:
            stack = None
        try:
            weather = _status()
        except Exception:  # noqa: BLE001 - the screen still draws without it
            weather = None
        return eink.render(saved["result"], site, eva, elapsed_h * 60.0, stack, lambda st: walkback(st, cost), weather, live)

    def _live(lat, lon, walked_m, energy_kj, visited):
        if lat is None or lon is None:
            return None
        return {"lat": lat, "lon": lon, "walked_m": walked_m, "energy_kj": energy_kj,
                "visited": [v for v in (visited or "").split(",") if v]}

    @app.get("/api/eink.png")
    def eink_png(db: DB, elapsed_h: float = Query(0.0, ge=0, le=24), plan_id: str | None = None,
             lat: float | None = None, lon: float | None = None, walked_m: float = 0.0, energy_kj: float = 0.0,
             visited: str | None = None):
        """The suit display (800 x 480, black and white) at `elapsed_h` into the plan (default: the latest plan)."""
        from marswalk import eink
        return Response(eink.to_png(_eink(plan_id, elapsed_h, db, _live(lat, lon, walked_m, energy_kj, visited))), media_type="image/png",
                        headers={"Cache-Control": "no-store"})

    @app.get("/api/eink.bin")
    def eink_bin(db: DB, elapsed_h: float = Query(0.0, ge=0, le=24), plan_id: str | None = None,
             lat: float | None = None, lon: float | None = None, walked_m: float = 0.0, energy_kj: float = 0.0,
             visited: str | None = None):
        """The same screen packed for an e-paper driver: 48 000 bytes, 1 bit per pixel, MSB first, 1 = black."""
        from marswalk import eink
        return Response(eink.to_bin(_eink(plan_id, elapsed_h, db, _live(lat, lon, walked_m, energy_kj, visited))), media_type="application/octet-stream",
                        headers={"Cache-Control": "no-store", "X-Width": str(eink.W), "X-Height": str(eink.H)})

    # Build the terrain stack and the walk-home field in the background, so the first click is not the slow one.
    def _warm():
        try:
            stack = terrain()
            radio(stack)
            uncertain(stack)
            walkback(stack, eva.cost_model)
        except Exception:  # noqa: BLE001 - e.g. terrain not fetched yet; the routes report it when asked
            pass

    def start_warm() -> None:
        threading.Thread(target=_warm, name="marswalk-warmup", daemon=True).start()

    if warm:
        start_warm()

    # --- Bases and the HiRISE catalog ---------------------------------------------------------------
    def _focus(base_id: str) -> None:
        with lock:
            site = registry.set_focus(base_id)          # raises 404 / 403 (not ready)
            focus["b"] = Focus(site)
        if warm:
            start_warm()

    def _bases() -> dict:
        out = registry.list()
        for b in out:
            if b.get("kind") == "user":
                b["size_bytes"] = b.get("size_bytes") or registry.size_bytes(b["id"])
        return {"focused": F().site.id, "bases": out, "job": runner.snapshot()}

    def _catalog():
        from marswalk.sources import catalog
        try:
            return catalog.ensure_index()
        except Exception as e:  # noqa: BLE001
            raise HTTPException(503, f"The HiRISE terrain catalog could not be downloaded yet ({e}). Try again shortly.") from e

    @app.get("/api/bases")
    def list_bases():
        return _bases()

    @app.get("/api/bases/job")
    def base_job():
        return runner.snapshot()

    @app.post("/api/bases", status_code=202)
    def create_base(body: BaseIn):
        import shutil

        from marswalk.sources import catalog
        from marswalk.sources.fetch import data_root
        cands = catalog.choose(_catalog(), body.lat, body.lon)
        if body.product_id:
            cands = [c for c in cands if c.entry.product_id == body.product_id]
        if not cands:
            raise HTTPException(422, "No 1 m HiRISE stereo terrain covers this point. Click inside one of the outlined areas.")
        need = catalog.estimate_bytes(catalog.base_bbox(body.lat, body.lon, cands[0].entry), cands[0].entry.scale_m)
        root = data_root()
        root.mkdir(parents=True, exist_ok=True)
        free = shutil.disk_usage(root).free
        if free < 2 * need + 1_000_000_000:
            raise HTTPException(507, f"Not enough free disk space: this Base needs about {need / 1e9:.1f} GB "
                                     f"and {free / 1e9:.1f} GB is free (keeping 1 GB spare).")
        try:
            return runner.start(body.lat, body.lon, body.name, cands[0].entry.product_id)
        except Busy as e:
            raise HTTPException(409, str(e)) from e

    @app.post("/api/bases/{base_id}/cancel")
    def cancel_base(base_id: str):
        return {"cancelled": runner.cancel(base_id)}

    @app.post("/api/bases/{base_id}/resume", status_code=202)
    def resume_base(base_id: str):
        info = registry.info(base_id)
        if info.get("status") not in ("interrupted", "failed"):
            raise HTTPException(409, f"This Base is {info.get('status')}, nothing to resume.")
        try:
            return runner.start(info["lat"], info["lon"], resume_id=base_id)
        except Busy as e:
            raise HTTPException(409, str(e)) from e

    @app.post("/api/bases/focus")
    def focus_base(body: FocusIn):
        _focus(body.id)
        return _bases()

    @app.delete("/api/bases/{base_id}")
    def delete_base(base_id: str):
        snap = runner.snapshot()
        if runner.running() and snap and snap["base_id"] == base_id:
            raise HTTPException(409, "This Base is still downloading. Cancel it first.")
        was_focused = F().site.id == base_id
        registry.delete(base_id)                      # 403 for the built-in Base, 404 if unknown
        runner.forget(base_id)
        if was_focused:
            _focus(builtin.id)
        return _bases()

    @app.get("/api/catalog/footprints")
    def footprints():
        """Every HiRISE stereo DTM footprint (GeoJSON, gzip), with whether a Base can be set there."""
        import gzip
        import json as _json

        from marswalk.sources import catalog
        body = gzip.compress(_json.dumps(catalog.footprints_geojson(_catalog()), separators=(",", ":")).encode(), 6)
        return Response(body, media_type="application/json",
                        headers={"Content-Encoding": "gzip", "Cache-Control": "max-age=86400"})

    @app.get("/api/catalog/lookup")
    def catalog_lookup(lat: float = Query(ge=-90, le=90), lon: float = Query(ge=-360, le=360)):
        """What a Base at (lat, lon) would use: the terrain, its window, the download size and what is missing."""
        import shutil

        from marswalk.sources import catalog
        from marswalk.sources.fetch import data_root
        cands = catalog.choose(_catalog(), lat, lon)
        if not cands:
            raise HTTPException(422, "No 1 m HiRISE stereo terrain covers this point. Click inside one of the outlined areas.")
        best = cands[0].entry
        bbox = catalog.base_bbox(lat, lon, best)
        tile = catalog.ti_tile(lat, lon)
        warnings = [] if tile else ["No thermal inertia here (THEMIS covers +-60 deg latitude): no sand flag."]
        if cands[0].edge_m < 2000:
            warnings.append(f"The stereo strip's edge is {cands[0].edge_m:.0f} m away, so part of the 2 km walk ring "
                            "has no 1 m terrain.")
        root = data_root()
        return {"lat": lat, "lon": lon, "bbox": bbox, "ti_tile": tile, "warnings": warnings,
                "est_bytes": catalog.estimate_bytes(bbox, best.scale_m),
                "free_bytes": shutil.disk_usage(root if root.exists() else root.parent).free,
                "candidates": [{"product_id": c.entry.product_id, "name": c.entry.rationale, "scale_m": c.entry.scale_m,
                                "edge_m": round(c.edge_m)} for c in cands]}

    return app
