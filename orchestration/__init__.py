"""Resource allocation primitives for trading and non-trading agents."""

__all__ = [
    "AllocationDecision",
    "AllocationMode",
    "AllocatorConfig",
    "AllocatorStore",
    "ArmStats",
    "ComplianceStatus",
    "DeliverabilityRisk",
    "EngineCapacityLimits",
    "EngineFamilyInput",
    "EngineFamilyRecommendation",
    "CandidateRecord",
    "ClosedTradeAttribution",
    "LifecycleState",
    "PerformanceObservation",
    "REVENUE_AUDIT_ENGINE",
    "RouteDecision",
    "ResourceAllocator",
    "ThesisFamily",
    "TradeLifecycleEvent",
]


def __getattr__(name: str):
    if name in {
        "AllocationDecision",
        "AllocationMode",
        "ArmStats",
        "CandidateRecord",
        "ClosedTradeAttribution",
        "ComplianceStatus",
        "DeliverabilityRisk",
        "EngineCapacityLimits",
        "EngineFamilyInput",
        "EngineFamilyRecommendation",
        "LifecycleState",
        "PerformanceObservation",
        "REVENUE_AUDIT_ENGINE",
        "RouteDecision",
        "ThesisFamily",
        "TradeLifecycleEvent",
    }:
        if name in {
            "CandidateRecord",
            "ClosedTradeAttribution",
            "LifecycleState",
            "RouteDecision",
            "ThesisFamily",
            "TradeLifecycleEvent",
        }:
            from . import candidate_contract

            return getattr(candidate_contract, name)
        from . import models

        return getattr(models, name)
    if name in {"AllocatorConfig", "ResourceAllocator"}:
        from . import resource_allocator

        return getattr(resource_allocator, name)
    if name == "AllocatorStore":
        from . import store

        return getattr(store, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
