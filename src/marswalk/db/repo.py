"""Repository: the ONLY way the rest of the app reads or writes the database.

Every function takes a Session and returns plain dicts (JSON-ready, no ORM objects leak out).
The API routes call these; the frontend reaches them only through /api.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from marswalk.config import SiteConfig
from marswalk.db.models import Observation, Plan, Setting, Site, Stop

USER_KIND = "user"   # stops added on the map (the others, "start" and "stop", are seeded from the site config)


class NotFound(LookupError):
    pass


class NotAllowed(PermissionError):
    """The request is understood but the row may not be changed (e.g. a science stop from the site config)."""


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
        _sync_config_stops(session, site)
        return False
    row = Site(id=site.id, name=site.name)
    pts = [site.start, *site.stops]
    row.stops = [Stop(code=s.id, seq=i, kind=s.kind, name=s.name, lat=s.lat, lon=s.lon, dtm_z_m=s.dtm_z_m,
                      science=s.science, work_time_min=s.work_time_min) for i, s in enumerate(pts)]
    session.add(row)
    session.commit()
    return True


def _sync_config_stops(session: Session, site: SiteConfig) -> None:
    """Config stops (start and science stops) cannot be edited in the app, so the config files stay their source of
    truth: refresh their position and details when the files change (e.g. a stop moved onto the base-map frame)."""
    rows = {r.code: r for r in session.scalars(select(Stop).where(Stop.site_id == site.id, Stop.kind != USER_KIND))}
    changed = False
    for s in (site.start, *site.stops):
        r = rows.get(s.id)
        if r is None:
            continue
        new = {"lat": s.lat, "lon": s.lon, "name": s.name, "dtm_z_m": s.dtm_z_m, "science": s.science,
               "work_time_min": s.work_time_min}
        for k, v in new.items():
            if getattr(r, k) != v:
                setattr(r, k, v)
                changed = True
    if changed:
        session.commit()


def delete_site(session: Session, site_id: str) -> bool:
    """Remove a site and everything recorded at it (observations, plans, stops). Returns False if it was not there.
    Order matters: plans and observations have no cascade, and SQLite enforces the foreign keys."""
    from sqlalchemy import delete
    session.execute(delete(Observation).where(Observation.site_id == site_id))
    session.execute(delete(Plan).where(Plan.site_id == site_id))
    row = session.get(Site, site_id)
    if row is not None:
        session.delete(row)          # stops go with it (relationship cascade)
    session.commit()
    return row is not None


# --- settings -------------------------------------------------------------------------------------

def get_setting(session: Session, key: str) -> str | None:
    row = session.get(Setting, key)
    return row.value if row else None


def set_setting(session: Session, key: str, value: str | None) -> None:
    row = session.get(Setting, key)
    if value is None:
        if row is not None:
            session.delete(row)
    elif row is None:
        session.add(Setting(key=key, value=value))
    else:
        row.value = value
    session.commit()


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


def _user_stop(session: Session, site_id: str, code: str) -> Stop:
    s = session.scalars(select(Stop).where(Stop.site_id == site_id, Stop.code == code)).first()
    if s is None:
        raise NotFound(f"stop {code!r}")
    if s.kind != USER_KIND:
        raise NotAllowed(f"{code} comes from the site's science plan and cannot be changed here")
    return s


def add_stop(session: Session, site_id: str, *, lat: float, lon: float, name: str = "", work_time_min: float = 0.0,
             dtm_z_m: float | None = None) -> dict:
    """Save a stop the crew added on the map. Codes run U1, U2, ...; it joins the end of the visiting order."""
    rows = session.scalars(select(Stop).where(Stop.site_id == site_id)).all()
    if not rows and session.get(Site, site_id) is None:
        raise NotFound(f"site {site_id!r}")
    n = 1 + max((int(r.code[1:]) for r in rows if r.kind == USER_KIND and r.code[1:].isdigit()), default=0)
    s = Stop(site_id=site_id, code=f"U{n}", seq=1 + max((r.seq for r in rows), default=0), kind=USER_KIND,
             name=name or f"My stop {n}", lat=lat, lon=lon, dtm_z_m=dtm_z_m, science="", work_time_min=work_time_min)
    session.add(s)
    session.commit()
    return _stop_dict(s)


def update_stop(session: Session, site_id: str, code: str, *, lat: float | None = None, lon: float | None = None,
                name: str | None = None, work_time_min: float | None = None, dtm_z_m: float | None = None) -> dict:
    s = _user_stop(session, site_id, code)
    if lat is not None and lon is not None:
        s.lat, s.lon, s.dtm_z_m = lat, lon, dtm_z_m
    if name:
        s.name = name
    if work_time_min is not None:
        s.work_time_min = work_time_min
    session.commit()
    return _stop_dict(s)


def delete_stop(session: Session, site_id: str, code: str) -> None:
    session.delete(_user_stop(session, site_id, code))
    session.commit()


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
