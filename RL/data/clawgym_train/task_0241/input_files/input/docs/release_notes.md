# Gen2 Spatial Audio SDK 2.3.0 — Release Notes

## Highlights
- Improved HRTF precision and reduced CPU overhead for gaming headsets.

## Baseline configuration for gaming headsets
- Sample rate: 48 kHz
- Bit depth: 24-bit
- HRTF profiles: gen2_standard (default), gen2_wide
- Spatializer plugin: AuralX version 2.3.0 or newer
- Default enabled features: dynamic_occlusion, head_tracking
- Optional features: room_sim
- Supported latency modes: low, standard
- Deprecation: All features with prefix "legacy_" are deprecated.

## Notes
- Projects targeting competitive FPS should prefer latency_mode: low.
- Projects may include room_sim on capable hardware.
