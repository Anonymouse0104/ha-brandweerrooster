# v1.3.3 - Public release preparation

Version 1.3.3 is the first release intended for public HACS distribution.

## Changes

- Added a GitHub issue tracker to the integration manifest.
- Added local Home Assistant brand assets (`icon.png` and `logo.png`).
- Added a dedicated HACS validation workflow.
- Removed the deprecated config-entry update listener/reload pattern. Configuration changes are now handled without the deprecated listener that will become an error in Home Assistant Core 2026.12.
- Removed generated Python cache files from the release package.
- Kept all 1.3.2 incident enrichment, personnel, event entity, coordinate, statistics and configurable Facebook-message functionality unchanged.

## Compatibility

This release keeps the existing configuration-entry format and is intended as a backwards-compatible maintenance release from 1.3.2.

## Validation

The repository includes separate validation workflows for:

- HACS validation
- Home Assistant Hassfest validation
- Python bytecode compilation

## Branding

Custom integrations can ship local brand images in the integration `brand/` directory on supported Home Assistant versions. The package includes both an icon and a logo.
