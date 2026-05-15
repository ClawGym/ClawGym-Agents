# Native Desktop App — Performance Profiling Scope

## Scope
- Create a text-only, environment-agnostic plan to profile a native desktop application.
- Focus on sampling-based performance measurement during key user flows (launch, open project, run compute-heavy task, navigate UI, and quit).
- Produce a clear approach for symbol resolution without naming specific tools or vendors.
- Provide a hotspot ranking strategy and guidance for prioritizing fixes.

## Assumptions
- The application can be executed locally with representative inputs and test data.
- Sampling-based profiling is possible without modifying the app binary.
- Build artifacts with symbol information are available for symbol resolution.
- Profiling sessions will be short (60–90 seconds) and targeted to specific flows.
- No external services or environment-specific tool names will be mentioned in the deliverable.

## Acceptance Criteria
- The plan contains the sections: "Profiling Steps", "Symbolication Strategy", "Hotspot Ranking", and "Risks & Assumptions".
- Steps are generic and avoid referencing any tool or vendor by name.
- The hotspot ranking approach explains how to aggregate samples and identify top functions or code regions.
- Risks and mitigations are documented, including assumptions about symbol availability.
- A generic adapter spec for a "native profiler" capability is provided separately and referenced in the alignment plan.

## Out of Scope
- Running profiling sessions or providing actual traces.
- Detailed OS-, IDE-, or vendor-specific instructions.
- Automating the profiling and analysis workflow.

## Risks
- Symbols may be missing or incomplete, reducing the quality of insights.
- Short profiling windows may not capture intermittent hotspots.
- Test data may not reflect real-world usage patterns.

## Notes
- Keep all language generic and portable across host environments.
- The plan should be readable and actionable for engineers without prescribing specific tools.