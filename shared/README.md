# shared

Shared reusable code and helpers.

- Type: code-bearing shared-library lane.
- Package map:
  - `shared/__init__.py`: package marker.
  - `shared/python/`: shared helper modules and utility code.
- Scope: cross-lane utilities intended for reuse across services/scripts.
- Rule: keep interfaces stable and avoid coupling to runtime artifact directories.
