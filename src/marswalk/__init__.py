"""MarsWalk: suited-astronaut traverse planner for Mars surface EVAs.

Pipeline (each stage is a module; see docs/ARCHITECTURE.md):

    config -> sources (fetch) -> layers (terrain, thermal, hazards)
           -> cost (metabolic | weighted) -> route (A*, stop order, plan)
           -> constraints (EVA limits) -> spaceweather (go/no-go) -> export (GeoJSON, Leaflet)
"""

__version__ = "1.2.0"
