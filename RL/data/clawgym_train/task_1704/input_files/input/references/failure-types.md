# 3D Print Failure Types

Reference for `diagnose.py`. Each entry includes symptom keywords for matching.

---

## 1. Stringing / Oozing
**Keywords:** stringing, oozing, hair, cobweb, wisp, thread, spider

**Description:** Thin strands of filament left between parts of the print during travel moves.

**Visual Symptoms:**
- Fine hair-like strands between parts of the model
- Webbing or cobweb appearance across gaps
- Thin blobs at travel start/end points

**Common Causes:**
- Retraction distance too short
- Retraction speed too slow
- Print temperature too high
- Travel speed too slow
- Wet filament (especially PETG/Nylon)

**Slicer Fix Cross-Reference:** See `slicer-fixes.md` → Stringing

---

## 2. Warping / Bed Adhesion Failure
**Keywords:** warping, warp, lifting, corner lift, peel, adhesion, detach, pop off, unstuck

**Description:** Print corners or edges lift from the bed during printing.

**Visual Symptoms:**
- Corners curled upward
- Part detaching mid-print
- Gaps between first layer and bed
- Elephant-foot-free first layer but raised edges

**Common Causes:**
- Bed not level or too far from nozzle
- Bed temperature too low
- Chamber not warm enough (ABS/ASA)
- No brim or skirt
- Cooling too aggressive for first layers
- Wrong bed surface for material

**Slicer Fix Cross-Reference:** See `slicer-fixes.md` → Warping

---

## 3. Layer Adhesion / Delamination
**Keywords:** layer adhesion, delamination, layer split, layer separation, weak layers, splitting, cracking, fracture

**Description:** Layers don't bond properly and separate or crack.

**Visual Symptoms:**
- Visible horizontal cracks between layers
- Layers peeling apart under light stress
- Rough, grainy layer surfaces
- Print snaps cleanly at layer boundaries

**Common Causes:**
- Print temperature too low
- Layer height too tall for nozzle diameter
- Print speed too fast
- Cooling too aggressive
- Old or wet filament

**Slicer Fix Cross-Reference:** See `slicer-fixes.md` → Layer Adhesion

---

## 4. Under-Extrusion
**Keywords:** under extrusion, underextrusion, gaps, sparse, weak, thin layers, missing material, incomplete, holes in walls

**Description:** Printer deposits less material than needed, leaving gaps or weak structures.

**Visual Symptoms:**
- Gaps between perimeters or infill
- Thin, translucent walls
- Incomplete top layers
- Holes or voids in the print surface
- Weak, fragile print

**Common Causes:**
- Extruder steps/mm not calibrated
- Nozzle partial clog
- Print speed too fast
- Temperature too low for filament
- Bowden tube gap or PTFE degradation
- Flow rate too low in slicer

**Slicer Fix Cross-Reference:** See `slicer-fixes.md` → Under-Extrusion

---

## 5. Over-Extrusion / Blobbing
**Keywords:** over extrusion, overextrusion, blob, bulge, ooze, zits, seam bump, rough surface, too much material, fat lines

**Description:** Too much filament is deposited, causing surface blemishes and dimensional inaccuracy.

**Visual Symptoms:**
- Rough, lumpy surface texture
- Blobs or zits on perimeters
- Seam area has a pronounced bump
- Walls thicker than intended
- Layer lines not distinct

**Common Causes:**
- Flow rate (extrusion multiplier) too high
- Extruder steps/mm miscalibrated
- Temperature too high (low viscosity)
- Retraction insufficient (pressure not released)

**Slicer Fix Cross-Reference:** See `slicer-fixes.md` → Over-Extrusion

---

## 6. Elephant Foot
**Keywords:** elephant foot, flared base, first layer squish, wide base, bottom flare, splayed

**Description:** The first few layers are squished outward, making the base wider than the rest of the print.

**Visual Symptoms:**
- Visible flare at the bottom of the print
- First layer oozes beyond model footprint
- Bottom edges not clean/sharp

**Common Causes:**
- Z offset too low (nozzle too close to bed)
- First layer flow rate too high
- Bed temperature too high
- First layer print speed too slow

**Slicer Fix Cross-Reference:** See `slicer-fixes.md` → Elephant Foot

---

## 7. Layer Shifting / Skipping
**Keywords:** layer shift, layer skip, offset, misaligned layers, shifted, staircase, x shift, y shift, axis skip

**Description:** Layers are printed offset from each other, creating a staircase effect.

**Visual Symptoms:**
- Layers suddenly shifted horizontally in X or Y
- Staircase pattern on model sides
- Print looks like it "slipped" partway through

**Common Causes:**
- Print speed too fast for belt tension
- Loose belt (X or Y axis)
- Acceleration too high
- Print head collision with model
- Current too low for stepper motors
- Mechanical obstruction in gantry path

**Slicer Fix Cross-Reference:** See `slicer-fixes.md` → Layer Shifting

---

## 8. Poor Bridging
**Keywords:** bridging, bridge, sag, drooping, hanging, span, overhang droop, bridge failure

**Description:** Horizontal spans between two points sag or fail.

**Visual Symptoms:**
- Sagging filament strands on bridge sections
- Gaps or holes in bridge areas
- Rough underside on bridges

**Common Causes:**
- Bridge speed too slow (more heat time)
- Bridge cooling insufficient
- Temperature too high
- Bridge flow too high
- Bridging distance too long without supports

**Slicer Fix Cross-Reference:** See `slicer-fixes.md` → Bridging

---

## 9. Overhang Quality Issues
**Keywords:** overhang, drooping, curling, overhang failure, cantilever, curl up, overhang quality

**Description:** Overhanging sections droop, curl, or print poorly without support.

**Visual Symptoms:**
- Curled or drooping edges on overhanging sections
- Rough surface on overhang underside
- Filament strands dangling from overhangs

**Common Causes:**
- Overhang angle exceeds material capability (usually >45–50°)
- Cooling insufficient
- Temperature too high
- Print speed too high on overhangs

**Slicer Fix Cross-Reference:** See `slicer-fixes.md` → Overhang

---

## 10. Clogged Nozzle / Grinding
**Keywords:** clog, clogged, grinding, clicking, extruder skip, stripped filament, no extrusion, jam

**Description:** Filament can't flow through the nozzle properly; extruder may grind or click.

**Visual Symptoms:**
- No or sporadic filament extrusion
- Audible clicking from extruder
- Stripped/chewed filament at extruder drive gear
- Sudden under-extrusion after printing fine

**Common Causes:**
- Nozzle partially blocked by burnt filament or debris
- Temperature too low for material
- Print speed too fast for flow rate
- PTFE tube degraded/melted
- Previous material remnant (e.g., ABS after PLA)

**Slicer Fix Cross-Reference:** See `slicer-fixes.md` → Clogged Nozzle

---

## 11. Pillowing / Poor Top Surface
**Keywords:** pillowing, top surface, holes on top, bulging top, wavy top, pockmarks, top layer gap

**Description:** Top layers have holes, bumps, or uneven surfaces.

**Visual Symptoms:**
- Holes or voids visible on top surface
- Wavy, uneven top layer
- "Pillow" bumps between infill lines
- Top infill not fully covering the surface

**Common Causes:**
- Top solid layers count too low (need at least 4–6)
- Infill percentage too low (less support for top layers)
- Cooling insufficient on top layers
- Top layer speed too fast

**Slicer Fix Cross-Reference:** See `slicer-fixes.md` → Pillowing

---

## 12. Ringing / Ghosting / Vibration Artifacts
**Keywords:** ringing, ghosting, vibration, ripple, echo, resonance artifact, wave pattern, surface ripple

**Description:** Ripple or wave patterns appear on flat surfaces adjacent to sharp features.

**Visual Symptoms:**
- Wavy lines parallel to sharp features (corners, holes)
- "Ripple" effect radiating outward from features
- Most visible on tall, fast-printed parts

**Common Causes:**
- Print speed too high
- Acceleration/jerk settings too high
- Mechanical looseness (belts, gantry, print head)
- Heavy print head / poor frame rigidity

**Slicer Fix Cross-Reference:** See `slicer-fixes.md` → Ringing

---

## 13. Z-Banding / Inconsistent Layer Height
**Keywords:** z banding, z wobble, inconsistent layers, screw artifact, vertical lines, banding, ribbing

**Description:** Periodic horizontal banding caused by Z-axis inconsistencies.

**Visual Symptoms:**
- Regular horizontal lines at consistent intervals
- Alternating thick/thin layer appearance
- Pattern repeats every N mm (related to lead screw pitch)

**Common Causes:**
- Z lead screw bent or misaligned
- Z coupler loose or eccentric
- Z steps/mm slightly off
- Print speed variation at layer change point

**Slicer Fix Cross-Reference:** See `slicer-fixes.md` → Z-Banding

---

## 14. Spaghetti / Print Detachment Mid-Print
**Keywords:** spaghetti, detached, fell off, mid print failure, tangled mess, complete failure, knocked off

**Description:** Print detaches from bed mid-print and is dragged around by the nozzle.

**Visual Symptoms:**
- Tangled mass of filament (spaghetti)
- Print separated from bed
- Base still on bed, rest is mess

**Common Causes:**
- Bed adhesion insufficient (see Warping)
- Print head collision
- First layer not adhered properly
- Vibration or external disturbance
- Filament runout without sensor

**Slicer Fix Cross-Reference:** See `slicer-fixes.md` → Warping, Layer Shifting

---

## 15. Wet Filament / Moisture Damage
**Keywords:** wet filament, moisture, bubbling, popping, hissing, crackling, steam, rough surface from moisture

**Description:** Absorbed moisture in filament causes bubbles and surface defects during printing.

**Visual Symptoms:**
- Audible popping or crackling during print
- Steam/vapor from nozzle
- Rough, bubbly surface texture
- Thin hair-like strands everywhere (worse than normal stringing)
- Inconsistent extrusion

**Common Causes:**
- Filament stored without desiccant
- Humidity above 40–50% RH during printing
- Hygroscopic materials (PETG, Nylon, TPU, PVA) especially vulnerable

**Slicer Fix Cross-Reference:** See `slicer-fixes.md` → Wet Filament

---

## 16. Seam / Zit Visibility
**Keywords:** seam, zit, seam line, visible seam, layer start, blob on seam, seam artifact

**Description:** The point where each layer begins/ends leaves a visible mark on the model.

**Visual Symptoms:**
- Vertical line running up the model
- Small blob or zit at a consistent location
- Dimple or depression at layer start

**Common Causes:**
- Seam placement not optimized
- Retraction settings not dialed in
- Pressure advance / linear advance not tuned
- Coasting not enabled

**Slicer Fix Cross-Reference:** See `slicer-fixes.md` → Seam

---

## 17. Support Issues (Over-Adhesion or Failure to Support)
**Keywords:** support stuck, support won't come off, support mark, support failure, support didn't work, support over-adhesion

**Description:** Supports either don't hold up overhangs properly or bond too strongly to the model.

**Visual Symptoms:**
- Support breaks during print (failure)
- Support tears model surface when removed (over-adhesion)
- Overhang surface quality poor despite supports

**Common Causes:**
- Support Z distance too small (over-adhesion) or too large (failure)
- Support interface layers missing
- Support density too low (failure) or too high (over-adhesion)
- Wrong support type for geometry

**Slicer Fix Cross-Reference:** See `slicer-fixes.md` → Supports

---

## 18. First Layer Issues
**Keywords:** first layer, adhesion problem, first layer gap, first layer too thick, first layer squish, bed level

**Description:** First layer is not printing correctly — too squished, too gapped, or not sticking.

**Visual Symptoms:**
- First layer not adhering (gap between filament and bed)
- First layer over-squished (no round profile, very flat)
- First layer gaps between lines
- First layer lines not bonded together

**Common Causes:**
- Z offset incorrect
- Bed not level (mesh or manual)
- Bed surface contaminated (oils from hands)
- First layer speed too high
- First layer height setting wrong

**Slicer Fix Cross-Reference:** See `slicer-fixes.md` → First Layer