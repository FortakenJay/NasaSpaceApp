"""ORM models (SQLAlchemy 2.0, typed).

Tables:
  sites         one row per configured site (seeded from configs/sites/*.toml)
  stops         EVA start + science stops per site (seeded from data/sites/<site>/stops.json)
  plans         saved plan requests and, from M4, their computed results (JSON)
  observations  field notes / sample IDs logged at a stop (the "sample & observation log" idea)
"""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Base(DeclarativeBase):
    pass


class Site(Base):
    __tablename__ = "sites"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    stops: Mapped[list["Stop"]] = relationship(back_populates="site", order_by="Stop.seq",
                                               cascade="all, delete-orphan")


class Stop(Base):
    __tablename__ = "stops"
    __table_args__ = (UniqueConstraint("site_id", "code"),)
    pk: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    site_id: Mapped[str] = mapped_column(ForeignKey("sites.id"))
    code: Mapped[str] = mapped_column(String(16))          # "H1", "S1", ...
    seq: Mapped[int] = mapped_column(Integer)              # visiting order in the science plan (start = 0)
    kind: Mapped[str] = mapped_column(String(8))           # "start" | "stop"
    name: Mapped[str] = mapped_column(String(200))
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    dtm_z_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    science: Mapped[str] = mapped_column(Text, default="")
    work_time_min: Mapped[float] = mapped_column(Float, default=0.0)
    site: Mapped[Site] = relationship(back_populates="stops")


class Plan(Base):
    __tablename__ = "plans"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    site_id: Mapped[str] = mapped_column(ForeignKey("sites.id"))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)
    name: Mapped[str] = mapped_column(String(200), default="")
    cost_model: Mapped[str] = mapped_column(String(16))
    stop_order: Mapped[str] = mapped_column(String(16))
    stop_codes: Mapped[list] = mapped_column(JSON)          # requested stops in order
    status: Mapped[str] = mapped_column(String(16), default="requested")  # requested | computed | failed
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)       # PlanResponse once M4 lands


class Observation(Base):
    __tablename__ = "observations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    site_id: Mapped[str] = mapped_column(ForeignKey("sites.id"))
    stop_code: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)
    author: Mapped[str] = mapped_column(String(100), default="crew")
    note: Mapped[str] = mapped_column(Text)
    sample_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
