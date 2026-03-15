"""Configuration helpers for checked-in control-plane surfaces."""

__all__ = [
    "DEFAULT_PROFILE_NAME",
    "RuntimeProfile",
    "RuntimeProfileError",
    "available_runtime_profiles",
    "load_runtime_profile",
    "write_effective_runtime_profile",
]


def __getattr__(name: str):
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    from . import runtime_profile as runtime_profile_module

    return getattr(runtime_profile_module, name)
