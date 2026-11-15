# Models and math

Every number MarsWalk shows comes from one of the formulas below. Each has a source, and `marswalk audit`
recomputes it by a second, independent path (see [Audit](Audit.md)).

## The ground: slope, roughness, off-limits

The terrain is a 1 m elevation grid (HiRISE stereo DTM `DTEEC_019698_1750_019988_1750_U01`, optionally on top of
the USGS merged 1 m Gale DEM).

| Layer | How it is computed | Why this scale |
|---|---|---|
| Slope, 5 m | Mean elevation in 5 × 5 m blocks, then a central difference: `atan(√(∂z/∂x² + ∂z/∂y²))` | A suited stride is about 1 m, a few strides is the slope a walker feels |
| Slope, 1 m | Same on the 1 m grid | Catches ledges and steps the 5 m slope smooths over |
| Roughness | Height range left after removing the local trend in a 5 × 5 m window | Rocks and ledges that trip a walker but do not tilt the ground |
| Sand | THEMIS thermal inertia below 300 J m⁻² K⁻¹ s⁻½ (100 m blocks) | Loose fines heat and cool fast; bedrock holds heat |

**Off-limits** (`nogo`) is any cell where the 5 m slope is over 25°, the 1 m slope over 35°, the roughness over
0.8 m, or (with the merged DEM) where no trusted 1 m HiRISE terrain exists. A route never enters an off-limits cell,
and no single step may be steeper than 20° (`cost.metabolic.max_grade_deg`).

The grid is equirectangular with true scale at the equator. At Gale (4.8° S) an east-west pixel is
1.0117 m × cos 4.8° = 1.0082 m on the ground, so east-west slopes and distances are off by 0.35 % at most.

## Walking speed (Marquez, in Johnson et al. 2010)

Speed in m/s against grade θ in degrees, uphill positive:

| Grade | Speed |
|---|---|
| θ ≤ −20° | 0.05 |
| −20° < θ ≤ −10° | 0.095 θ + 1.95 |
| −10° < θ ≤ 0° | 0.06 θ + 1.6 |
| 0° < θ ≤ 6° | −0.2 θ + 1.6 |
| 6° < θ ≤ 15° | −0.039 θ + 0.634 |
| θ > 15° | 0.05 |

The pieces meet at every breakpoint (the audit checks this). Flat ground: 1.6 m/s.

## Walking power (Santee et al. 2001, as used by SEXTANT)

With m the mass of crew member plus suit (80 + 60 kg), g = 3.71 m/s², v in m/s:

- Level: `W_level = (3.28 · m · g/g_E + 71.1) · (0.661 · v · cos θ + 0.115)`
- Uphill: `W = W_level + 3.5 · m · g · v · sin θ`
- Downhill: `W = W_level + 2.4 · m · g · v · sin θ · 0.3^(|θ|/7.65)`

All coefficients match Johnson et al. 2010, Table 2. **One assumption is MarsWalk's own:** the mass term of the
level walking cost is scaled by g/g_E (Mars/Earth gravity). SEXTANT applies gravity only to the slope terms.
Without the scaling, level walking at 140 kg costs about twice as much power.

Power and speed together decide what a route costs. On a 10° climb the power is lower than on the flat (144 W
against 287 W), because the walker is 6.5× slower. Per metre it costs 3.3× more energy, which is why routes
bend around slopes.

## Route search

The search is A* over the 1 m grid with 8 neighbours. The cost of a step is its energy (metabolic model) or a weighted
time/slope/roughness score (weighted model). The same compiled core runs Dijkstra from the rover once, so the
walk home from every cell (time, energy, path) is known for the safe zone and the voice answers.

Distance, climb and grade are measured on the stride-scale walking surface (the DTM smoothed with a 2-pixel Gaussian, about 2 m). On the raw 1 m DTM, its ~0.2 m
of stereo noise would add length and phantom climbing. The [audit](Audit.md) caught that one.

## Time, energy, oxygen

| Quantity | Formula | Value for the Gale demo plan |
|---|---|---|
| Leg time | Σ step length ÷ speed × **1.3** (time margin) | |
| Time outside | legs + 30 min of work per stop | 3 h 31 min |
| Usable oxygen time | 8 h tank × (1 − 0.3 reserve) | 5 h 36 min |
| Energy | Σ step energy × 1.3 + 250 W × time at stops | 2,962 kJ |
| Usable energy | 12,000 kJ × 0.7 | 8,400 kJ (35 % used) |
| Oxygen breathed | energy ÷ 14,127 kJ per kg O₂ | 0.21 kg per person |
| Walk-home margin | usable time − (time now + walk home) | 2 h 05 min at the tightest point |

**Oxygen per joule.** The body burns 4.825 kcal per litre of O₂ at a respiratory quotient of 0.82, a mixed diet
(Lusk/Weir), which is 20.19 kJ per litre. One litre of O₂ weighs 1.429 g at 0 °C and 1 atm, so
1 kg of O₂ = 20.19 / 1.429 × 1000 = 14,127 kJ.

The **reserve** is never planned into. The plan must be able to walk home from every point while keeping 30 % of
the oxygen. The "spare time" on screen is how much longer the crew could stay at the tightest point and still do that.

## The walk-back safe zone

For every cell, the reverse Dijkstra field gives the walk home (time and energy, with the margin). At elapsed
time t, a cell is inside the safe zone when

`max( t_home × 1.3 / (usable time − t), E_home × 1.3 / (usable energy − E_used) ) ≤ 1`

The map colours that fraction green (plenty), then yellow, then orange (barely). As t grows the zone shrinks. On the
demo plan, at 5 h 18 min it still reaches every stop, but only just: 18 minutes of usable oxygen are left, and the
walk home from S5 takes 15.

## Radiation

Curiosity's RAD measured, on the ground in Gale, an absorbed dose of **0.21 ± 0.04 mGy/day** and a dose equivalent
of **0.64 ± 0.12 mSv/day** (Hassler et al. 2014, *Science* 343). MarsWalk scales those by the time outside:
3 h 31 min → 0.031 mGy (0.094 mSv). That is the galactic cosmic ray background. A solar particle event would add to
it, which is what the space-weather check is for.

## Space weather go/no-go

From NASA DONKI (via the central API client, cached 30 min). Times are relative to now:

- **NO-GO** if a direct CME shock is predicted at Mars (WSA-ENLIL) between 24 h ago and 48 h ahead, or a solar
  energetic particle event was reported in the last 48 h
- **CAUTION** if only a glancing CME blow is predicted in that window, a CME arrival is predicted 2 to 7 days
  ahead, an SEP event was reported in the last 7 days, an X-class flare was seen in the last 24 h, or the CME or
  particle feeds did not answer
- **GO** otherwise

Flares are seen from Earth's side of the Sun, so they are only a hint for Mars: an X-class flare raises CAUTION, but
a flare list that fails to download does not.

## Registration: putting HiRISE on the map

The HiRISE DTM's own coordinates sit **33.5 m south and 30.5 m east** of the USGS/MSL Gale base map. That base map
is the one shared by the Mars Trek photo mosaic, the merged DEM and Curiosity's waypoints. Two independent
measurements found the same shift:

| Pair compared | Correlation before | Correlation after shifting (33 m N, 30 m W) |
|---|---|---|
| HiRISE DTM vs USGS merged DEM (4 m blocks, plane removed) | 0.935 | 0.9998 |
| HiRISE orthophoto vs Mars Trek photo tiles | 0.47 | 0.93 |

`products.dtm.basemap_offset_m` applies the shift at load time. With the merged DEM present, the remaining offset is
measured again at every build (512 m patch, ±60 m search, sub-metre peak fit) and applied when r ≥ 0.9.

## Gait limit (optional)

People switch from walking to running near a fixed Froude number Fr = v² / (g L) (Kram, Domingo & Ferris 1997). With
`walk_run_froude` set, walking speed is capped at

\[ v_{max} = \sqrt{Fr \, g \, L} = \sqrt{0.56 \times 3.71 \times 0.89} = 1.36 \text{ m/s} \]

(Fr and L from Kram's 0.4 g condition, Table 1: 1.39 ± 0.06 m/s measured). Off by default; the audit reports the
uncapped 1.6 m/s as a finding.

## Radio line of sight

From the rover's antenna (ground + `rover_antenna_m`) a ray per azimuth keeps the steepest angle the ground has
reached, with the ground lowered by Mars's curvature, d² / 2R. A cell is in contact when the suit antenna on it
(ground + `suit_antenna_m`) is at or above that angle. No relay; no diffraction over ridges.

## Storm shelter

The walk home from a cell is the walk-back field's time × `time_margin_factor`. The cell is out of shelter reach when
that exceeds `sep_warning_lead_min` = 30 min (Löwe et al. 2025: RAD-based nowcasting gave at least 30 min before the
peak and 90 % of the dose for every SEP event at Gale since 2012).

## Terrain uncertainty

Each of 20 draws adds noise n = G_σc * w to the elevations (white noise w smoothed with a Gaussian of
`noise_corr_px`, rescaled to standard deviation `vertical_sigma_m` = 0.3 m) and, with probability
`registration_sigma_m` / pixel, shifts the terrain by one pixel per axis; then slope (1 m, 5 m), roughness and the same
hazard limits. Off-limits frequency f = (draws off limits) / 20: always f ≥ 0.95, sometimes 0.05 < f < 0.95.

## Consumables

Per kJ of metabolic energy E: cooling water E / 2 454 kJ/kg (latent heat of vaporisation at 20 °C); CO₂
(E / 20.19 kJ/L) × 0.82 × 1.977 g/L; oxygen stays time-based. Each consumable keeps the 30 % reserve; the one with
the least time left at the current mean power is shown and drives "turn back within".

## Sound in the simulator

Rover hum: gain ∝ 1/d (full within 6 m), delay d / 240 m/s, low-pass at the frequency f where Martian air has absorbed
20 dB: e^(−α(f) d) = 0.1, with α = 0.21, 0.34, 0.43 m⁻¹ at 4.5, 8.5, 13 kHz (Maurice et al. 2022) and linear to zero
below.

## Sources

- Johnson, A. W., Hoffman, J. A., Newman, D. J., et al. (2010). *An Integrated Traverse Planner and Analysis Tool for
  Planetary Exploration.* AIAA SPACE 2010. Tables 1 (speed) and 2 (metabolic rate).
- Santee, W. R., et al. (2001). *A proposed model for load carriage on sloped terrain.* Aviation, Space, and
  Environmental Medicine 72(6).
- Hassler, D. M., et al. (2014). *Mars' surface radiation environment measured with the Mars Science Laboratory's
  Curiosity rover.* Science 343(6169).
- Parker, T. J., & Calef, F. J. (2016). USGS Astrogeology: *Mars MSL Gale Merged DEM 1m* (v3).
- Caloric equivalent of oxygen: 4.825 kcal/L at RQ 0.82 (Lusk table; Weir equation).
- Kram, R., Domingo, A., & Ferris, D. P. (1997). *Effect of reduced gravity on the preferred walk-run transition
  speed.* Journal of Experimental Biology 200: 821–826.
- Löwe, J. L., et al. (2025). *Nowcasting Solar Energetic Particle Events for Mars Missions.* Space Weather,
  doi:10.1029/2025SW004372.
- Sutton, S. S., et al. (2022). *Revealing Active Mars with HiRISE Digital Terrain Models.* Remote Sensing 14: 2403.
- Maurice, S., et al. (2022). *In situ recording of Mars soundscape.* Nature 605: 653–658.
