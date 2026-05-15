# Slicer Setting Fixes by Failure Type

Specific recommended values for PrusaSlicer, Cura, and OrcaSlicer.
Settings listed are starting points — dial from there based on results.

---

## Stringing

### PrusaSlicer
- Retraction length: 2–4 mm (direct drive: 0.5–1.5 mm)
- Retraction speed: 45–60 mm/s
- Minimum travel after retraction: 2 mm
- Wipe before retract: enabled
- Nozzle temperature: reduce by 5–10°C (try 200→190°C for PLA)

### Cura
- Retraction distance: 5–7 mm (Bowden) / 1–2 mm (direct drive)
- Retraction speed: 45–55 mm/s
- Minimum retraction travel: 1.5–2 mm
- Combing mode: All (avoids crossing open areas)
- Travel speed: increase to 150–200 mm/s

### OrcaSlicer
- Retraction length: 1–2 mm (direct drive) / 4–6 mm (Bowden)
- Retraction speed: 35–60 mm/s
- Travel distance threshold: 2 mm
- Wipe on loops: enabled
- Temperature: reduce 5°C and test

---

## Warping

### PrusaSlicer
- First layer bed temp: +5–10°C above normal (PLA: 60–65°C, ABS: 100–110°C, PETG: 75–85°C)
- Brim width: 8–12 mm, brim offset: 0 mm
- Draft shield: enable for ABS/ASA
- Fan speed for first 3 layers: 0%

### Cura
- Build plate adhesion: Brim, width: 8–12 mm
- Initial layer temperature: +5°C above print temp
- Build plate temperature: PLA 60–65°C, ABS 100–110°C, PETG 80°C
- Fan speed first layer: 0%
- Enable draft shield for ABS

### OrcaSlicer
- Brim: Mouse ear or outer brim only, width: 8 mm
- First layer bed temp: PLA 65°C, PETG 80°C, ABS 110°C
- Slow first layer: 20 mm/s
- Chamber temp (ABS/ASA): 40–50°C if enclosure available

---

## Layer Adhesion

### PrusaSlicer
- Nozzle temperature: increase by 5–10°C
- Layer height: max 75% of nozzle diameter (0.4 mm nozzle → max 0.3 mm layers)
- Print speed: reduce to 40–50 mm/s
- Fan speed: reduce by 20–30% (less cooling = better bonding)

### Cura
- Print temperature: increase 5–10°C
- Layer height: reduce to 0.2 mm for 0.4 mm nozzle
- Print speed: 40 mm/s
- Fan speed: reduce to 30–50% for PLA; 0–20% for ABS/PETG

### OrcaSlicer
- Nozzle temp: increase 5–10°C
- Max layer height: 75% of nozzle diameter
- Speed: reduce perimeters to 40 mm/s
- Cooling: reduce fan by 20%

---

## Under-Extrusion

### PrusaSlicer
- Extrusion multiplier: increase from 1.00 → 1.05 (5% steps, max ~1.15)
- Temperature: increase 5°C
- Speed: reduce to 40 mm/s overall
- Extrude at layer change: enabled
- Check: extruder calibration (steps/mm) — 100 mm commanded = 100 mm extruded

### Cura
- Flow rate: increase to 105% (test up to 115%)
- Print temperature: increase 5°C
- Print speed: reduce to 40 mm/s
- Maximum resolution: reduce to 0.5 mm (prevents too-short moves)

### OrcaSlicer
- Filament flow ratio: increase 0.02–0.05
- Temperature: increase 5°C
- Speed: reduce outer walls to 35 mm/s
- Max volumetric speed: check not too high (PLA: ~11 mm³/s max typical)

---

## Over-Extrusion

### PrusaSlicer
- Extrusion multiplier: reduce from 1.00 → 0.95 (5% steps)
- Temperature: reduce 5°C
- Retraction: increase by 0.5 mm

### Cura
- Flow rate: reduce to 95%
- Print temperature: reduce 5°C

### OrcaSlicer
- Flow ratio: reduce by 0.03–0.05
- Temperature: reduce 5°C
- Enable pressure advance tuning

---

## Elephant Foot

### PrusaSlicer
- Elephant foot compensation: 0.1–0.3 mm (under Print Settings → Advanced)
- First layer height: 0.2 mm (not lower)
- First layer extrusion width: 100% (not higher than 120%)
- Z offset: raise by 0.05 mm increments until flare disappears

### Cura
- Initial layer horizontal expansion: -0.1 to -0.2 mm
- First layer flow: reduce to 95%
- Z offset: raise nozzle slightly

### OrcaSlicer
- Elephant foot compensation: 0.1–0.2 mm
- First layer: reduce flow to 95%
- Z offset: increase by 0.05 mm and observe

---

## Layer Shifting

### PrusaSlicer
- Print speed: reduce to 60 mm/s (from 80–100)
- Acceleration: reduce to 500–800 mm/s² (from 1000–2000)
- Check belt tension (not a slicer fix, but required)
- Avoid fan hitting model (fan duct collision)

### Cura
- Print speed: reduce to 50–60 mm/s
- Acceleration: reduce to 500 mm/s²
- Jerk control: enable, set to 8 mm/s (X/Y)

### OrcaSlicer
- Speed: reduce to 60 mm/s
- Acceleration: reduce to 500 mm/s²
- Jerk: reduce to 8 mm/s

---

## Bridging

### PrusaSlicer
- Bridging speed: 20–30 mm/s
- Bridging fan speed: 100%
- Bridging flow: 0.9–0.95 (reduce slightly to avoid sag)
- Enable "detect bridging perimeters"

### Cura
- Bridge speed: 20–30 mm/s
- Bridge fan speed: 100%
- Bridge wall speed: 30 mm/s
- Bridge wall flow: 90%
- Minimum bridge length: 5 mm

### OrcaSlicer
- Bridge speed: 25 mm/s
- Bridge fan speed: 100%
- Bridge flow ratio: 0.90

---

## Overhang

### PrusaSlicer
- Fan speed: 100% for overhangs (if PLA)
- Overhang speed: reduce to 15–25 mm/s for steep overhangs
- Extra perimeters if needed: enabled
- Threshold for supports: 45–50° for PLA, 40° for PETG/ABS

### Cura
- Fan speed: 100% on overhangs
- Overhang speed: set speed for 50–89% overhang: 20 mm/s
- Print cooling: 100% if PLA
- Support angle threshold: 50° (PLA), 45° (PETG)

### OrcaSlicer
- Overhang speed: reduce to 20 mm/s at 50%+ overhang
- Cooling: 100% fan for overhangs
- Support threshold: 40–50°

---

## Clogged Nozzle

Primarily a hardware fix, but slicer can help prevent recurrence.

### PrusaSlicer
- Temperature: ensure adequate (PLA ≥ 200°C, PETG ≥ 230°C, ABS ≥ 240°C)
- Max volumetric speed: reduce to 8 mm³/s for PLA (prevent cold jams)
- Enable "Detect thin walls" to avoid pushing too much filament into tight gaps

### Cura
- Print temperature: ensure at minimum (PLA 200°C, PETG 235°C)
- Max flow rate: reduce by 10–15%
- Cold pull at end of print (manual procedure)

### OrcaSlicer
- Nozzle temperature: at minimum for material
- Reduce max volumetric speed by 10%
- Use nozzle purge before print start for material changes

---

## Pillowing

### PrusaSlicer
- Top solid layers: 5–7 (was 3 → increase)
- Top surface pattern: Monotonic or Concentric
- Top infill speed: reduce to 30–40 mm/s
- Fan speed on top layer: 100% (PLA)
- Infill: increase to 20–25% minimum for support

### Cura
- Top layers: 5–7
- Top surface skin layers: 1–2 additional
- Top/bottom speed: 30–40 mm/s
- Infill density: 20% minimum

### OrcaSlicer
- Top shell layers: 5–7
- Top surface pattern: Monotonic
- Top speed: 30 mm/s
- Ironing: enable for smooth top surfaces

---

## Ringing / Ghosting

### PrusaSlicer
- Perimeter speed: reduce to 40–60 mm/s
- Max print speed: 60 mm/s
- Acceleration: reduce to 500–700 mm/s²
- Input shaper: enable if using Klipper firmware (hardware-level fix)
- Avoid printing thin tall structures fast

### Cura
- Print speed: reduce to 50 mm/s
- Acceleration: 500 mm/s² (requires "Enable Acceleration Control")
- Jerk: 8 mm/s (requires "Enable Jerk Control")

### OrcaSlicer
- Speed: reduce outer walls to 40 mm/s
- Acceleration: 500 mm/s²
- Jerk: 8 mm/s
- Input shaper calibration: run if printer supports it

---

## Z-Banding

Primarily mechanical but slicer can mitigate.

### PrusaSlicer
- Z speed: reduce to 10 mm/s
- Layer height: use values that are multiples of lead screw step (e.g., 0.1, 0.15, 0.2, 0.25, 0.3 mm for 2 mm pitch / 16 microstep)
- Avoid layer heights that don't align with step resolution

### Cura
- Z speed: reduce
- Use layer heights aligned with step resolution

### OrcaSlicer
- Same as above — use step-aligned layer heights
- Reduce Z hop speed to 5–8 mm/s

---

## Seam

### PrusaSlicer
- Seam position: Aligned (predictable) or Rear (hidden on back)
- Seam painting: manually paint seam to back or concave feature
- Wipe: enabled, wipe length: 1.5–2 mm
- Pressure advance (Klipper): tune for clean seam

### Cura
- Seam corner preference: Smart hiding or Sharpest corner
- Z seam alignment: Back
- Coasting: enable, coasting volume: 0.064 mm³ (0.4 mm nozzle, 0.2 mm layer)

### OrcaSlicer
- Seam: Aligned or Back
- Wipe on loops: enabled
- Scarf seam: enable (OrcaSlicer-specific, blends seam over a distance)
- Pressure advance: tune

---

## Supports

### PrusaSlicer
- Support Z distance: 0.15–0.2 mm (smaller = tighter = harder to remove)
- Support interface layers: 2–3
- Support interface density: 80–100%
- Horizontal expansion: 0 mm (avoid touching model sides)
- Pattern: Rectilinear or Gyroid for easier removal

### Cura
- Support Z distance: 0.15 mm (over-adhesion) → increase to 0.2 mm
- Support interface: enable, thickness: 0.6–1.0 mm
- Interface density: 33–50% for easy removal
- Support type: Tree for organic shapes, Normal for flat overhangs

### OrcaSlicer
- Support top Z distance: 0.2 mm
- Support interface: 2 layers
- Interface density: 50%
- Tree supports: enable for complex geometry

---

## First Layer

### PrusaSlicer
- First layer height: 0.2 mm (or 50–75% of normal layer height)
- First layer speed: 15–25 mm/s
- First layer extrusion width: 120–150%
- Z offset: adjust via Live Adjust Z (paper test: slight drag)
- Bed temp: PLA 60°C, PETG 80°C, ABS 100°C

### Cura
- Initial layer height: 0.2–0.3 mm
- Initial layer speed: 20 mm/s
- Initial layer flow: 100% (don't exceed for elephant foot)
- Skirt/brim: enable for priming
- Bed temp: same as above

### OrcaSlicer
- First layer height: 0.2 mm
- First layer speed: 20 mm/s
- First layer flow: 100%
- Z offset: adjust in 0.05 mm increments until lines just touch with slight sheen
- Bed temp: PLA 60–65°C, PETG 80°C, ABS 100–110°C