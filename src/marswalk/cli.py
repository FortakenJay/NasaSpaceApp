"""Command-line entry point: `python -m marswalk <command>` (or `marswalk` once pip-installed).

  info      site, products, stops, straight-line distances, EVA limits    [works]
  serve     run the FastAPI backend for the frontend                       [works; stages report milestones]
  export    write the static site JSON for backend-less demos              [works]
  fetch     cache data windows as GeoTIFFs in data/raw/<site>/             [works; needs NASA hosts]
  layers    build the LayerStack (slope, roughness, TI, no-go)             [works]
  plan      route H1 -> stops -> H1 with the chosen cost model             [works]
  status    space-weather go/no-go (DONKI + RAD baseline)                  [works; needs api.nasa.gov]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from marswalk.config import PROJECT_ROOT, load_dotenv, load_eva, load_site
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
        if not isinstance(p, dict):       # e.g. the list of context tile layers
            print(f"  {key:16s} {len(p)} layers")
            continue
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
    uvicorn.run(create_app(args.site, args.eva, warm=True), host=args.host, port=args.port, log_level="info")
    return 0


def _run_fetch(site, eva, args):
    from marswalk.sources.fetch import fetch_site
    out = fetch_site(site, include_optional=getattr(args, "optional", False))
    print(f"data cached in {out}")


def _run_layers(site, eva, args):
    import numpy as np
    from marswalk.layers import render
    from marswalk.layers.stack import build_stack
    from marswalk.sources.fetch import cache_dir
    st = build_stack(site, eva)
    print(f"stack {st.shape[0]} x {st.shape[1]} px at {st.grid.pixel_m:.2f} m; no-go {st.nogo.mean():.1%} of cells")
    ck = st.terrain_check
    if st.terrain_source == "merged":
        print(f"terrain: USGS merged 1 m DEM everywhere; trusted 1 m HiRISE terrain on {1 - st.coarse.mean():.0%} of the window "
              f"(planning allowed only there)")
        print(f"  merged vs HiRISE where both exist: median slope difference {ck.get('median_slope_diff_deg', float('nan')):.2f} deg, "
              f"elevation offset {ck.get('median_dz_m', float('nan')):+.1f} m, "
              f"roughness ratio {ck.get('median_roughness_ratio', float('nan')):.2f}")
    elif st.terrain_note:
        print(f"terrain: HiRISE strip alone ({st.terrain_note})")
    else:
        print("terrain: HiRISE strip alone (no merged DEM cached; run `marswalk fetch`)")
    off, reg = ck.get("basemap_offset_m"), ck.get("registration")
    if off:
        print(f"  HiRISE DTM moved {off.get('north', 0):+.1f} m north, {off.get('east', 0):+.1f} m east onto the base-map frame"
              + (f"; measured residual {reg['north_m']:+.1f} m N, {reg['east_m']:+.1f} m E (correlation {reg['corr']:.3f})"
                 if reg else ""))
    print("  id   slope1  slope5  rough_m   TI   no-go")
    for s in (site.start, *site.stops):
        r, c = st.grid.latlon_to_rc(s.lat, s.lon)
        if not (0 <= r < st.shape[0] and 0 <= c < st.shape[1]):
            print(f"  {s.id:4s} outside the terrain window")
            continue
        w = (slice(max(r - 12, 0), r + 13), slice(max(c - 12, 0), c + 13))     # 25 m box mean around the stop
        print(f"  {s.id:4s} {np.nanmean(st.slope_1m_deg[w]):6.1f} {np.nanmean(st.slope_5m_deg[w]):7.1f} "
              f"{np.nanmean(st.roughness_m[w]):8.2f} {np.nanmean(st.ti[w]) if np.isfinite(st.ti[w]).any() else float('nan'):5.0f}   {'YES' if st.nogo[r, c] else 'no'}")
    out = cache_dir(site)
    out.mkdir(parents=True, exist_ok=True)
    for name in ("hillshade", "slope5", "roughness", "nogo"):
        (out / f"{name}.png").write_bytes(render.layer_png(st, name))
    print(f"overlay PNGs written to {out}")


def _run_plan(site, eva, args):
    import json
    from marswalk.export.payload import plan_payload
    from marswalk.layers.stack import build_stack
    from marswalk.route.plan import build_plan
    st = build_stack(site, eva)
    plan = build_plan(site, eva, st, cost_model_name=args.cost, order=args.order)
    p = plan_payload(plan, st)
    print("Summary: " + ", ".join(f"{k}={v}" for k, v in p["summary"].items()))
    print("Timeline (min):")
    for w in p["timeline"]:
        print(f"  {w['id']:4s} arrive {w['arrive_min']:6.1f}  depart {w['depart_min']:6.1f}  walk-back {w['walkback_min']:5.1f}  {w['name']}")
    print("Violations:" if p["violations"] else "Violations: none")
    for v in p["violations"]:
        print(f"  [{v['severity']}] {v['rule']} {v['where']}: {v['detail']}")
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(p), encoding="utf-8")
        print(f"wrote {args.out}")


def _run_status(site, eva, args):
    import os
    from marswalk.sources.api_client import get_client
    from marswalk.sources.fetch import data_root
    from marswalk.spaceweather.status import current_status
    key = os.environ.get(site.spaceweather.get("api_key_env", "NASA_API_KEY")) or "DEMO_KEY"
    client = get_client(data_root() / "cache" / "api")
    st = current_status(site.spaceweather, float(eva.eva["max_duration_h"]), key, client=client)
    print(f"{st.level}: {st.reason}")
    print(f"  EVA dose at the RAD baseline: {st.eva_dose_mgy} mGy over {eva.eva['max_duration_h']} h ({st.baseline_dose_mgy_per_day} mGy/day)")
    for a in st.mars_arrivals:
        print(f"  CME at Mars {a['arrival']} ({'glancing' if a['glancing'] else 'direct'}, {a['hours_from_now']:+.0f} h)")
    print(f"  SEP events (7 d): {st.recent_sep_events}   strongest flare (3 d): {st.strongest_flare or 'none'}")
    for n in st.notes:
        print(f"  note: {n}")
    snap = client.snapshot()
    print(f"  key: {'NASA_API_KEY' if key != 'DEMO_KEY' else 'DEMO_KEY (set NASA_API_KEY in .env)'}   requests left this hour: {snap['rate_limit']['remaining']}")
    for f in snap["feeds"]:
        print(f"  feed {f['name']:6s} {f['state']:8s} {f['error']}")


def _run_audit(site, eva, args):
    from marswalk import audit
    from marswalk.layers.stack import build_stack
    try:
        st = build_stack(site, eva)
    except FileNotFoundError as e:
        print(f"{e}\nChecking the constants only.")
        st = None
    checks = audit.run(site, eva, st, cost=args.cost)
    width = max(len(c.name) for c in checks)
    for c in checks:
        mark = "ok  " if c.ok else ("NOTE" if c.finding else "FAIL")
        print(f"  {mark} {c.name:<{width}}  expected {c.expected!s:>12}  got {c.got!s:>12}")
    bad = [c for c in checks if not c.ok and not c.finding]
    real = [c for c in checks if not c.finding]
    notes = [c for c in checks if c.finding and not c.ok]
    print(f"{len(real) - len(bad)} of {len(real)} checks pass."
          + (f" {len(notes)} model assumption{'s' if len(notes) > 1 else ''} differ{'' if len(notes) > 1 else 's'} from "
             f"published data (NOTE)." if notes else ""))
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(audit.markdown(checks), encoding="utf-8")
        print(f"wrote {args.out}")
    if bad:
        raise SystemExit(1)


def _stub(milestone: str, fn):
    """Run a pipeline stage; report unimplemented milestones instead of crashing."""
    def run(args) -> int:
        try:
            fn(load_site(args.site), load_eva(args.eva), args)
        except NotImplementedError as e:
            print(f"[{milestone}] not implemented yet: {e}", file=sys.stderr)
            return 2
        except FileNotFoundError as e:
            print(e, file=sys.stderr)
            return 3
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
    fe = sub.add_parser("fetch", help="cache data windows (DTM, thermal inertia, ortho)")
    fe.add_argument("--optional", action="store_true", help="also fetch the 25 cm and colour orthos")
    fe.set_defaults(func=_stub("M1", _run_fetch))
    sub.add_parser("layers", help="build the layer stack, print values at the stops").set_defaults(func=_stub("M2", _run_layers))
    pl = sub.add_parser("plan", help="plan the traverse")
    pl.add_argument("--out", help="also write the plan JSON here (e.g. out/plan.json)")
    pl.add_argument("--cost", choices=["metabolic", "weighted"], help="override eva.cost.model")
    pl.add_argument("--order", choices=["fixed", "optimize"], help="override eva.route.stop_order")
    pl.set_defaults(func=_stub("M4", _run_plan))
    sub.add_parser("status", help="[M5] space-weather go/no-go").set_defaults(func=_stub("M5", _run_status))
    au = sub.add_parser("audit", help="recompute every number the app shows and compare")
    au.add_argument("--out", help="also write the results as markdown (e.g. docs/wiki/Audit-results.md)")
    au.add_argument("--cost", choices=["metabolic", "weighted"], help="cost model of the plan to check")
    au.set_defaults(func=_stub("audit", _run_audit))
    return p


def _warn_if_other_checkout() -> None:
    """A moved or copied project folder keeps an editable install that points at the OLD folder, so the
    commands silently run old code and look for data in the wrong place. Say so loudly."""
    cwd = Path.cwd().resolve()
    if (cwd / "src" / "marswalk" / "cli.py").exists() and cwd != PROJECT_ROOT.resolve():
        print(f"WARNING: this Python environment runs MarsWalk from\n    {PROJECT_ROOT}\n"
              f"not from the folder you are in\n    {cwd}\n"
              'so you are running a different copy of the code and data. Fix: python -m pip install -e ".[dev]"\n',
              file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    _warn_if_other_checkout()
    load_dotenv()
    args = build_parser().parse_args(argv)
    return args.func(args)
