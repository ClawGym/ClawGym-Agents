# Software Bill of Materials (SBOM)

This project includes an SBOM generated via CycloneDX during CI.

- Format: CycloneDX JSON v1.5
- Components: 58 direct + transitive dependencies
- Generation step: `npm run sbom` + `pip cyclonedx-bom`
- Intended use: External distribution and vulnerability management

Key artifacts:
- cyclonedx-npm.json (web frontend dependencies)
- cyclonedx-pip.json (API dependencies)

Compliance notes:
- License scanning performed; no forbidden licenses detected
- SBOM artifacts stored with release candidates

Contact: Security Engineering for access and validation procedures.

Generated: 2026-04-15