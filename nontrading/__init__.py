"""JJ-N non-trading worker package."""

from nontrading.approval_gate import ApprovalDecision, ApprovalGate
from nontrading.crm_schema import (
    ApprovalClass,
    Contact as CRMContact,
    Interaction as CRMInteraction,
    Lead as CRMLead,
    LeadStatus,
    Opportunity as CRMOpportunity,
)
from nontrading.engines import (
    AccountIntelligenceEngine,
    InteractionEngine,
    LearningEngine,
    OutreachEngine,
    ProposalEngine,
)
from nontrading.opportunity_registry import OpportunityAssessment, OpportunityRegistry, OpportunityScoreInput
from nontrading.telemetry import NonTradingTelemetry, TelemetryBridge

__version__ = "0.2.0"

__all__ = [
    "__version__",
    "ApprovalClass",
    "ApprovalDecision",
    "ApprovalGate",
    "CRMContact",
    "CRMInteraction",
    "CRMLead",
    "CRMOpportunity",
    "LeadStatus",
    "OpportunityAssessment",
    "OpportunityRegistry",
    "OpportunityScoreInput",
    "NonTradingTelemetry",
    "TelemetryBridge",
    "AccountIntelligenceEngine",
    "OutreachEngine",
    "InteractionEngine",
    "ProposalEngine",
    "LearningEngine",
]
