"""Resource allocation primitives for trading and non-trading agents."""

__all__ = [
    "AllocationDecision",
    "AllocationMode",
    "AllocatorConfig",
    "AllocatorStore",
    "ArmStats",
    "DeliverabilityRisk",
    "PerformanceObservation",
    "ResourceAllocator",
]


def __getattr__(name: str):
    if name in {"AllocationDecision", "AllocationMode", "ArmStats", "DeliverabilityRisk", "PerformanceObservation"}:
        from . import models

        return getattr(models, name)
    if name in {"AllocatorConfig", "ResourceAllocator"}:
        from . import resource_allocator

        return getattr(resource_allocator, name)
    if name == "AllocatorStore":
        from . import store

        return getattr(store, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
