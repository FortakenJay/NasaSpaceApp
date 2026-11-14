"""Repository: the ONLY way the rest of the app reads or writes the database.

Every function takes a Session and returns plain dicts (JSON-ready, no ORM objects leak out).
The API routes call these; the frontend reaches them only through /api.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from marswalk.config import SiteConfig
from marswalk.db.models import Observation, Plan, Site, Stop


class NotFound(LookupError):
    pass


def _iso_utc(t: dt.datetime) -> str:
    """SQLite stores datetimes without a zone; everything is written in UTC, so label it as such."""
    return (t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)).isoformat()


# --- seeding --------------------------------------------------------------------------------------

def seed_site(session: Session, site: SiteConfig) -> bool:
    """Insert the site and its stops from config files if the site is not in the DB yet.

    Idempotent: an existing site is left untouched, so stops edited in the DB are not overwritten.
    Returns True when it seeded.
    """
    if session.get(Site, site.id) is not None:
        return False
    row = Site(id=site.id, name=site.name)
    pts = [site.start, *site.stops]
    row.stops = [Stop(code=s.id, seq=i, kind=s.kind, name=s.name, lat=s.lat, lon=s.lon, dtm_z_m=s.dtm_z_m,
                      science=s.science, work_time_min=s.work_time_min) for i, s in enumerate(pts)]
    session.add(row)
    session.commit()
    return True


# --- sites & stops --------------------------------------------------------------------------------

def _stop_dict(s: Stop) -> dict:
    return {"id": s.code, "name": s.name, "lat": s.lat, "lon": s.lon, "kind": s.kind,
            "science": s.science, "work_time_min": s.work_time_min, "dtm_z_m": s.dtm_z_m}


def list_stops(session: Session, site_id: str) -> list[dict]:
    rows = session.scalars(select(Stop).where(Stop.site_id == site_id).order_by(Stop.seq)).all()
    if not rows and session.get(Site, site_id) is None:
        raise NotFound(f"site {site_id!r}")
    return [_stop_dict(s) for s in rows]


def stop_codes(session: Session, site_id: str) -> set[str]:
    return set(session.scalars(select(Stop.code).where(Stop.site_id == site_id)).all())


# --- plans ----------------------------------------------------------------------------------------

def _plan_dict(p: Plan) -> dict:
    return {"id": p.id, "site_id": p.site_id, "created_at": _iso_utc(p.created_at), "name": p.name,
            "cost_model": p.cost_model, "stop_order": p.stop_order, "stop_ids": list(p.stop_codes),
            "status": p.status, "result": p.result}


def create_plan(session: Session, site_id: str, *, cost_model: str, stop_order: str,
                stop_ids: list[str], name: str = "", result: dict | None = None) -> dict:
    unknown = set(stop_ids) - stop_codes(session, site_id)
    if unknown:
        raise NotFound(f"unknown stops {sorted(unknown)}")
    p = Plan(site_id=site_id, cost_model=cost_model, stop_order=stop_order, stop_codes=list(stop_ids),
             name=name, status="computed" if result else "requested", result=result)
    session.add(p)
    session.commit()
    return _plan_dict(p)


def list_plans(session: Session, site_id: str, limit: int = 50) -> list[dict]:
    rows = session.scalars(select(Plan).where(Plan.site_id == site_id)
                           .order_by(Plan.created_at.desc()).limit(limit)).all()
    return [_plan_dict(p) for p in rows]


def get_plan(session: Session, plan_id: str) -> dict:
    p = session.get(Plan, plan_id)
    if p is None:
        raise NotFound(f"plan {plan_id!r}")
    return _plan_dict(p)


# --- observations ---------------------------------------------------------------------------------

def _obs_dict(o: Observation) -> dict:
    return {"id": o.id, "stop_id": o.stop_code, "created_at": _iso_utc(o.created_at),
            "author": o.author, "note": o.note, "sample_id": o.sample_id}


def add_observation(session: Session, site_id: str, stop_id: str, *, note: str, author: str = "crew",
                    sample_id: str | None = None) -> dict:
    if stop_id not in stop_codes(session, site_id):
        raise NotFound(f"stop {stop_id!r}")
    o = Observation(site_id=site_id, stop_code=stop_id, note=note, author=author, sample_id=sample_id)
    session.add(o)
    session.commit()
    return _obs_dict(o)


def list_observations(session: Session, site_id: str, stop_id: str) -> list[dict]:
    if stop_id not in stop_codes(session, site_id):
        raise NotFound(f"stop {stop_id!r}")
    rows = session.scalars(select(Observation).where(Observation.site_id == site_id,
                                                     Observation.stop_code == stop_id)
                           .order_by(Observation.created_at.desc(), Observation.id.desc())).all()
    return [_obs_dict(o) for o in rows]
