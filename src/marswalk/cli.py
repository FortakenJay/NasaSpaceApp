"""Command-line entry point: `python -m marswalk <command>` (or `marswalk` once pip-installed).

  info      site, products, stops, straight-line distances, EVA limits    [works]
  serve     run the FastAPI backend for the frontend                       [works; stages report milestones]
  export    write the static site JSON for backend-less demos              [works]
  fetch     cache data windows as GeoTIFFs in data/raw/<site>/             [M1]
  layers    build the LayerStack (slope, roughness, TI, no-go)             [M2]
  plan      route H1 -> stops -> H1 with the chosen cost model             [M3/M4]
  status    space-weather go/no-go                                         [M5]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from marswalk.config import PROJECT_ROOT, load_eva, load_site
from marswalk.constraints.eva import check_distance_from_rover
from marswalk.geo import ground_distance_m

DEFAULT_SITE = "configs/sites/gale_boxwork.toml"
DEFAULT_EVA = "configs/eva/artemis_default.toml"


def cmd_info(args) -> int:
    site, eva = load_site(args.site), load_eva(args.eva)
    R = site.body["radius_m"]
    print(f"Site: {site.name} ({site.id})")
    print(f"  bbox lat {site.bbox['lat_min']}..{site.bbox['lat_max']}, lon {site.bbox['lon_min']}..{site.bbox['lon_max']}")
    print("Products:")
    for key, p in site.products.items():
        print(f"  {key:16s} {p.get('id', p.get('url_template', ''))}{'  (optional)' if p.get('optional') else ''}")
    print(f"Cost model: {eva.cost_model}   stop order: {eva.route['stop_order']}")
    print(f"EVA limits: {eva.eva['max_duration_h']} h, reserve {eva.eva['walkback_reserve_frac']:.0%}, "
          f"max {eva.eva['max_distance_from_rover_m']:.0f} m from rover, crew {eva.eva['crew_size']}")
    print("\nStops (straight-line; real route is longer):")
    prev, total, dists = site.start, 0.0, {}
    print(f"  {site.start.id}  {site.start.name}  ({site.start.lat:.6f}, {site.start.lon:.6f})")
    for s in site.stops:
        leg = ground_distance_m(prev.lat, prev.lon, s.lat, s.lon, R)
        total += leg
        dists[s.id] = ground_distance_m(site.start.lat, site.start.lon, s.lat, s.lon, R)
        print(f"  {s.id}  {s.name:42s} leg {leg:6.0f} m   from rover {dists[s.id]:5.0f} m   work {s.work_time_min:.0f} min")
        prev = s
    back = ground_distance_m(prev.lat, prev.lon, site.start.lat, site.start.lon, R)
    print(f"  back to {site.start.id}: {back:.0f} m   ->  total {total + back:.0f} m straight-line")
    v = check_distance_from_rover(dists, eva)
    print("\nDistance-from-rover check:", "OK" if not v else "; ".join(f"{x.where}: {x.detail}" for x in v))
    return 0


def cmd_export(args) -> int:
    from marswalk.export.payload import site_payload, write_json
    out = Path(args.out) if args.out else PROJECT_ROOT / "frontend" / "public" / "sample-site.json"
    write_json(site_payload(load_site(args.site)), out)
    print(f"wrote {out}")
    return 0


def cmd_serve(args) -> int:
    import uvicorn
    from marswalk.api.app import create_app
    uvicorn.run(create_app(args.site, args.eva), host=args.host, port=args.port, log_level="info")
    return 0


def _run_fetch(site, eva, args):
    from marswalk.sources.fetch import fetch_site
    fetch_site(site, include_optional=False)


def _run_layers(site, eva, args):
    from marswalk.layers.stack import build_stack
    build_stack(site, eva)


def _run_plan(site, eva, args):
    from marswalk.layers.stack import build_stack
    from marswalk.route.plan import build_plan
    if args.order:
        eva.route["stop_order"] = args.order
    build_plan(site, eva, build_stack(site, eva), cost_model_name=args.cost)


def _run_status(site, eva, args):
    import datetime as dt
    from marswalk.spaceweather.status import fetch_sep_events
    today = dt.date.today()
    fetch_sep_events(today - dt.timedelta(days=7), today, site.spaceweather["donki_base_url"], "DEMO_KEY")


def _stub(milestone: str, fn):
    """Run a pipeline stage; report unimplemented milestones instead of crashing."""
    def run(args) -> int:
        try:
            fn(load_site(args.site), load_eva(args.eva), args)
        except NotImplementedError as e:
            print(f"[{milestone}] not implemented yet: {e}", file=sys.stderr)
            return 2
        return 0
    return run


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="marswalk", description="Suited-astronaut traverse planner for Mars EVAs")
    p.add_argument("--site", default=DEFAULT_SITE, help="site TOML (default: Gale boxwork)")
    p.add_argument("--eva", default=DEFAULT_EVA, help="EVA limits / cost TOML")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("info", help="show site, products, stops, limits").set_defaults(func=cmd_info)
    sv = sub.add_parser("serve", help="run the API for the frontend")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8000)
    sv.set_defaults(func=cmd_serve)
    ex = sub.add_parser("export", help="write static site JSON (backend-less demo)")
    ex.add_argument("--out", help="default frontend/public/sample-site.json")
    ex.set_defaults(func=cmd_export)
    sub.add_parser("fetch", help="[M1] cache data windows").set_defaults(func=_stub("M1", _run_fetch))
    sub.add_parser("layers", help="[M2] build layer stack").set_defaults(func=_stub("M2", _run_layers))
    pl = sub.add_parser("plan", help="[M3/M4] plan the traverse")
    pl.add_argument("--cost", choices=["metabolic", "weighted"], help="override eva.cost.model")
    pl.add_argument("--order", choices=["fixed", "optimize"], help="override eva.route.stop_order")
    pl.set_defaults(func=_stub("M4", _run_plan))
    sub.add_parser("status", help="[M5] space-weather go/no-go").set_defaults(func=_stub("M5", _run_status))
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)
