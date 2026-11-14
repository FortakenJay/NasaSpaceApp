"""HTTP API: the single server layer. The frontend reaches data ONLY through these routes, and these
routes reach the database ONLY through marswalk.db.repo.

    GET  /api/health                         -> {ok, version, site}
    GET  /api/site                           -> site metadata + stops (stops from the DB)              [works]
    GET  /api/stops/{stop_id}/observations   -> field log for a stop, newest first                      [works]
    POST /api/stops/{stop_id}/observations   -> add {note, author?, sample_id?}                         [works]
    GET  /api/plans                          -> saved plans, newest first                               [works]
    POST /api/plans                          -> save a plan request {name?, cost, order, stop_ids}      [works]
    GET  /api/plans/{plan_id}                -> one saved plan                                          [works]
    POST /api/plan                           -> compute a route {cost?, order?, stop_ids?} and persist it
                                                via repo.create_plan(result=...) (status "computed")     [501 M4]
    GET  /api/layers                         -> available overlays                                      [[] until M2]
    GET  /api/layers/{name}.png              -> overlay PNG                                             [501 M2]
    GET  /api/status                         -> space-weather GO / CAUTION / NO-GO                      [501 M5]

Stages that aren't built yet answer 501 {"milestone": "Mx", "detail": ...}.
"""
from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from marswalk import __version__
from marswalk.config import EVAConfig, SiteConfig, load_eva, load_site
from marswalk.db import repo
from marswalk.db.engine import DEFAULT_URL, make_engine, make_session_factory
from marswalk.export.payload import site_payload

DEFAULT_SITE = "configs/sites/gale_boxwork.toml"
DEFAULT_EVA = "configs/eva/artemis_default.toml"
LAYER_NAMES = ("hillshade", "slope5", "roughness", "ti", "nogo")

CostName = Literal["metabolic", "weighted"]
OrderName = Literal["fixed", "optimize"]


class PlanRequest(BaseModel):
    cost: CostName | None = None
    order: OrderName | None = None
    stop_ids: list[str] | None = None   # subset / custom order; default = all stops in DB order


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


def create_app(site_path: str = DEFAULT_SITE, eva_path: str = DEFAULT_EVA, db_url: str = DEFAULT_URL) -> FastAPI:
    site: SiteConfig = load_site(site_path)
    eva: EVAConfig = load_eva(eva_path)
    app = FastAPI(title="MarsWalk Traverse Planner API", version=__version__)
    app.state.sessions = make_session_factory(make_engine(db_url))
    with app.state.sessions() as s:
        repo.seed_site(s, site)
    app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
                       allow_methods=["GET", "POST"], allow_headers=["*"])

    @app.exception_handler(repo.NotFound)
    def _not_found(_: Request, exc: repo.NotFound):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.get("/api/health")
    def health():
        return {"ok": True, "version": __version__, "site": site.id}

    # --- site & stops (DB) ------------------------------------------------------------------------
    @app.get("/api/site")
    def get_site(db: DB):
        return site_payload(site, repo.list_stops(db, site.id))

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

    # --- pipeline stages --------------------------------------------------------------------------
    @app.post("/api/plan")
    def compute_plan(req: PlanRequest):
        try:
            from marswalk.layers.stack import build_stack
            from marswalk.route.plan import build_plan
            build_plan(site, eva, build_stack(site, eva), cost_model_name=req.cost)
        except NotImplementedError as e:
            return _not_built("M4", e)
        raise HTTPException(500, "plan export not wired yet")

    @app.get("/api/layers")
    def list_layers():
        return []  # M2: list cached overlays with their lat/lon bounds

    @app.get("/api/layers/{name}.png")
    def get_layer(name: str):
        if name not in LAYER_NAMES:
            raise HTTPException(404, f"unknown layer {name!r}")
        try:
            from marswalk.layers.stack import build_stack
            build_stack(site, eva)
        except NotImplementedError as e:
            return _not_built("M2", e)
        raise HTTPException(500, "layer rendering not wired yet")

    @app.get("/api/status")
    def get_status():
        try:
            import datetime as dt
            from marswalk.spaceweather.status import fetch_sep_events
            today = dt.date.today()
            fetch_sep_events(today - dt.timedelta(days=7), today, site.spaceweather["donki_base_url"], "DEMO_KEY")
        except NotImplementedError as e:
            return _not_built("M5", e)
        raise HTTPException(500, "status not wired yet")

    return app
