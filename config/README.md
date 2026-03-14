# config

Configuration contracts for runtime behavior.

- Type: code-bearing configuration lane.
- Core modules: `config/runtime_profile.py`, `config/runtime_profiles/`.
- Package map:
  - `config/runtime_profile.py`: runtime profile loader/contract.
  - `config/runtime_profiles/`: named profile definitions.
  - `config/*`: environment templates and defaults.
- Rule: behavior-affecting config changes need matching tests and artifact evidence.
