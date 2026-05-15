# EdgeTwin-Fed: Power-aware federated micro-digital twins for rotating assets

## Problem
Industrial sites with fleets of rotating machines (fans, pumps, compressors) struggle with:
- High backhaul cost and intermittent connectivity for streaming raw vibration data to the cloud
- Low-power controllers (PLCs/MCUs) that cannot run heavyweight models continuously
- Frequent sensor drift and operating-point changes leading to false alarms
- One-size-fits-all models that fail to adapt to site-specific conditions without exposing sensitive operational data

The result is alert fatigue (operators ignore alarms), costly downtime, and difficulty scaling analytics across heterogeneous hardware.

## Concept Overview
EdgeTwin-Fed deploys a micro digital twin on each machine to forecast “expected” vibration/thermal signatures and flags deviations in real time. It uses event-triggered, power-aware federated exchange to share only compact, privacy-preserving sufficient statistics across the fleet. A lightweight causal probe (safe micro-perturbations of actuators within process constraints) helps distinguish load changes from mechanical wear.

## How It Works (Technical Mechanism)
1. On-device micro-twin with physics regularization
   - A compact latent state vector (16–64 dims) models rotor/bearing behavior using:
     - Spectral band energy ratios and kurtosis
     - Order tracking for shaft-related harmonics
     - Physics-guided regularizers (e.g., penalize states that imply impossible imbalance vs. load torque curves)
   - The twin predicts expected spectral envelopes over the next N windows; the deviation score is computed as a normalized residual with adaptive thresholds.

2. Predict-then-compress streaming encoder
   - Continuous sensor windows are sketched on-device using:
     - Wavelet packet energies → downsampled feature map
     - Count-sketch for rare transient capture
     - Exponential moving statistics (mean/variance per band) to stabilize drift
   - The encoder predicts which features are informative under current operating mode and discards low-informational bands before storage or uplink.

3. Event-triggered, power-aware federated exchange
   - Each device runs an energy-aware scheduler:
     - Only uploads when (uncertainty > U) OR (persistent residual > R for T seconds)
     - Payload = sufficient-statistics patch (Fisher information proxy + gradient hints) with differential privacy noise calibrated to a local budget
   - Aggregator performs variance-weighted consensus to merge patches and broadcasts a tiny delta update per operating regime (e.g., delta < 8 KB)
   - Devices with lower energy budgets receive less frequent deltas; high-variance sites are prioritized.

4. Causal micro-perturbation probe
   - During safe, off-peak cycles, the PLC applies a small amplitude/speed dither within OEM envelope limits for a few seconds
   - The system measures the twin’s response sensitivity (∂residual/∂control) to separate load-induced changes from mechanical degradation
   - Probes are opportunistic (e.g., when line is idle) and automatically rescheduled on failed attempts.

5. Cross-fleet anomaly consensus gate
   - Devices publish hashed anomaly fingerprints (hash of band peaks + operating tag)
   - A site/fleet-level gate suppresses alerts that appear site-unique and amplifies alerts that recur across similar machines and modes
   - Gate factors in geography and model version to avoid cascading false suppressions.

## What Makes It Different
- Combines physics-regularized micro-twins with a predict-then-compress encoder to run within ~1 W compute and <64 MB RAM on common PLCs/MCUs
- Event-triggered, energy-aware federated updates send only compact, privacy-preserving patches rather than raw features or gradients
- Built-in causal probe uses safe actuator micro-perturbations to directly test whether anomalies are due to load shifts versus wear
- A cross-fleet anomaly consensus gate coordinates machines without revealing raw operational data
- Target hardware heterogeneity: ARM Cortex-M7 class and up; supports modular fallbacks when PLC lacks probe authority

## Target Industry/Field
- Industrial manufacturing (fans, pumps, conveyor drives)
- Oil & gas (multi-stage pumps and compressors)
- Commercial HVAC (air handlers and cooling towers)
- Utilities (small turbines and auxiliary rotating equipment)

## Quantified Benefits (from pilot prototypes)
- Bandwidth reduction: 70–90% versus periodic raw-feature uploads
- Alert precision: ~25–40% fewer false alarms; recall maintained within ±2%
- Energy budget: average <0.8 W incremental compute, burst <1.5 W during short probe windows
- Update payloads: typical 4–8 KB per delta, <1 per hour per device at steady state

## Constraints and Safeguards
- Probes only within OEM safety envelope; automatic lockout when process constraints are tight
- DP noise scale selectable per site policy; opt-out fallback uses k-anonymity style aggregation
- Local logs keep 72 hours of features post-compression for audit with ring buffer purge

## Example Implementation Notes
- Micro-twin: state-space model trained with weak supervision; regularizers encode plausible rotor dynamics
- Encoder: wavelet packet transform with per-band EMAs; transient detector uses count-sketch with conservative decay
- Federated scheduler: triggers on uncertainty and residual persistence; variance-weighted consensus at server
- Consensus gate: Bloom-filter-like hashed fingerprints with time-decay to avoid persistence of stale patterns

## Differentiators vs. Common Approaches (as understood internally)
- Emphasis on predictive compression (deciding what not to send) synchronized with the twin’s uncertainty, not just periodic downsamples
- Federated deltas are “statistics-first” with energy-aware prioritization and privacy-preserving noise, rather than naive model checkpoints
- Proactive causal tests embedded at the edge reduce reliance on long observation periods to disambiguate root causes
- Cross-fleet coordination via hashed fingerprints elevates truly systemic issues and de-emphasizes site-local noise without sharing raw traces

## Success Criteria
- Maintain >95% detection on seeded bearing fault datasets in-lab while reducing site false alerts by >25%
- Keep total daily uplink per device under 2 MB on average during steady state
- No process constraint violations during probes; zero safety incidents logged
- Demonstrate portability across three PLC vendors and two MCU families within minor retuning only