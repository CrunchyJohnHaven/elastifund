# Execute Instance #7 — JJ-N Non-Trading Worker Foundations

You are an autonomous Codex instance for the Elastifund trading system. Execute every step below without human intervention. Report findings, commit code, and produce the handoff artifact.

---

## STATE SNAPSHOT (Injected 2026-03-09 v2.8.0)

- JJ-N rollout phase: Phase 0 — Foundations (days 1-14), NOT STARTED
- Non-trading modules complete: 0
- Revenue lanes active: 0
- Five-engine model: defined in COMMAND_NODE.md (Account Intelligence, Outreach, Interaction, Proposal, Learning)
- Opportunity scoring framework: defined (7 criteria with weights)
- CRM schema: not created
- Telemetry: not wired for non-trading events
- nontrading/ directory: exists but may be empty/minimal
- Tests: 11 non-trading tests passing
- Vision docs: `research/elastic_vision_document.md`, `research/platform_vision_document.md`

### VISION CONTEXT (MANDATORY)

JJ-N is the non-trading worker — the "first-class front door" for Elastifund. The first wedge is a revenue-operations worker for a single high-ticket service business. Phase 0 goal: "Create a safe, measurable system."

Phase 0 deliverables: Opportunity registry, CRM schema, telemetry, dashboards, domain/auth setup, templates, approval classes, paper mode.

Success criterion: "prove one revenue loop that can be measured, improved, and explained."

---

## OBJECTIVE

Build the Phase 0 foundations for the JJ-N non-trading worker: CRM schema, opportunity registry, five-engine stubs, approval gates, telemetry events, and paper mode. Every module must be testable and produce Elastic-compatible telemetry events.

## YOU OWN

`nontrading/`, `tests/nontrading/`, `infra/` (non-trading index templates only)

## DO NOT TOUCH

`bot/`, `src/`, `deploy/`, `docs/` (prose), website files, `CLAUDE.md`, `COMMAND_NODE.md`, `PROJECT_INSTRUCTIONS.md`

## STEPS

1. Read `research/elastic_vision_document.md` Sections on non-trading architecture, five-engine model, opportunity scoring, and JJ-N rollout plan.

2. Read `research/platform_vision_document.md` for platform architecture that JJ-N must integrate with.

3. Read `COMMAND_NODE.md` Sections: "Non-Trading Architecture (Five-Engine Model)", "Non-Trading Opportunity Scoring Framework", "JJ-N Rollout Plan".

4. Read existing `nontrading/` directory:
   ```bash
   find nontrading/ -type f 2>/dev/null | sort
   ```

5. Read existing non-trading tests:
   ```bash
   find tests/nontrading/ -type f 2>/dev/null | sort
   ```

6. **Create the CRM schema** at `nontrading/crm_schema.py`:
   ```python
   """JJ-N CRM Schema — Phase 0 Foundations.

   Dataclass models for leads, contacts, opportunities, and interactions.
   All models produce structured telemetry events compatible with Elastic indexing.
   """
   from dataclasses import dataclass, field, asdict
   from datetime import datetime
   from enum import Enum
   from typing import Optional
   import json

   class LeadStatus(Enum):
       RESEARCH = "research"
       QUALIFIED = "qualified"
       OUTREACH = "outreach"
       RESPONDED = "responded"
       MEETING = "meeting"
       PROPOSAL = "proposal"
       WON = "won"
       LOST = "lost"
       DISQUALIFIED = "disqualified"

   class ApprovalClass(Enum):
       AUTO = "auto"           # No human approval needed
       REVIEW = "review"       # Human reviews before send
       ESCALATE = "escalate"   # Human must explicitly approve

   @dataclass
   class Lead:
       id: str
       company: str
       contact_name: str
       contact_email: str
       source: str
       status: LeadStatus = LeadStatus.RESEARCH
       fit_score: float = 0.0
       opportunity_score: float = 0.0
       created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
       updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
       notes: str = ""
       tags: list = field(default_factory=list)

       def to_event(self) -> dict:
           return {"event_type": "lead_update", "timestamp": datetime.utcnow().isoformat(), **asdict(self)}

   @dataclass
   class Opportunity:
       id: str
       lead_id: str
       service_type: str
       estimated_value_usd: float
       time_to_first_dollar_days: int
       gross_margin_pct: float
       automation_fraction: float
       data_exhaust_score: float  # 0-1
       compliance_simplicity: float  # 0-1
       capital_required_usd: float
       sales_cycle_days: int
       composite_score: float = 0.0
       status: str = "research"
       created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

       def compute_score(self) -> float:
           """Compute weighted opportunity score per the canonical framework."""
           self.composite_score = (
               (1.0 / max(self.time_to_first_dollar_days, 1)) * 25 +
               self.gross_margin_pct * 20 +
               self.automation_fraction * 20 +
               self.data_exhaust_score * 15 +
               self.compliance_simplicity * 10 +
               (1.0 / max(self.capital_required_usd, 1)) * 5 +
               (1.0 / max(self.sales_cycle_days, 1)) * 5
           )
           return self.composite_score

       def to_event(self) -> dict:
           return {"event_type": "opportunity_scored", "timestamp": datetime.utcnow().isoformat(), **asdict(self)}

   @dataclass
   class Interaction:
       id: str
       lead_id: str
       engine: str  # account_intelligence | outreach | interaction | proposal | learning
       action: str
       approval_class: ApprovalClass = ApprovalClass.REVIEW
       approved: bool = False
       result: str = ""
       timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

       def to_event(self) -> dict:
           d = asdict(self)
           d["event_type"] = "interaction"
           return d
   ```

7. **Create the opportunity registry** at `nontrading/opportunity_registry.py`:
   ```python
   """JJ-N Opportunity Registry — Phase 0.

   In-memory registry (SQLite backing in Phase 1) for tracking and scoring opportunities.
   """
   from typing import List, Optional
   from nontrading.crm_schema import Opportunity, Lead, LeadStatus

   class OpportunityRegistry:
       def __init__(self):
           self.leads: dict[str, Lead] = {}
           self.opportunities: dict[str, Opportunity] = {}
           self.events: list[dict] = []

       def add_lead(self, lead: Lead) -> Lead:
           self.leads[lead.id] = lead
           self.events.append(lead.to_event())
           return lead

       def add_opportunity(self, opp: Opportunity) -> Opportunity:
           opp.compute_score()
           self.opportunities[opp.id] = opp
           self.events.append(opp.to_event())
           return opp

       def rank_opportunities(self) -> List[Opportunity]:
           return sorted(self.opportunities.values(), key=lambda o: o.composite_score, reverse=True)

       def get_lead(self, lead_id: str) -> Optional[Lead]:
           return self.leads.get(lead_id)

       def update_lead_status(self, lead_id: str, status: LeadStatus) -> Optional[Lead]:
           lead = self.leads.get(lead_id)
           if lead:
               lead.status = status
               from datetime import datetime
               lead.updated_at = datetime.utcnow().isoformat()
               self.events.append(lead.to_event())
           return lead

       def flush_events(self) -> list[dict]:
           events = self.events.copy()
           self.events.clear()
           return events
   ```

8. **Create engine stubs** at `nontrading/engines/`:
   ```bash
   mkdir -p nontrading/engines
   ```
   Create five files: `account_intelligence.py`, `outreach.py`, `interaction.py`, `proposal.py`, `learning.py`. Each should:
   - Import from `crm_schema`
   - Define a class with `process()` and `to_event()` methods
   - Include docstrings describing Phase 0 vs Phase 1 scope
   - Be importable and testable

9. **Create approval gate** at `nontrading/approval_gate.py`:
   - Implement approval routing based on `ApprovalClass`
   - AUTO: execute immediately, log event
   - REVIEW: queue for human review, log event
   - ESCALATE: block until explicit approval, log event
   - Paper mode: all actions logged but never executed externally

10. **Create telemetry bridge** at `nontrading/telemetry.py`:
    - Accept events from any engine
    - Format as ECS-compatible JSON
    - In Phase 0: write to `nontrading/events.jsonl`
    - In Phase 1: forward to Elastic via `bot/elastic_client.py`

11. **Create `nontrading/__init__.py`** with version and imports.

12. **Write tests** in `tests/nontrading/`:
    - `test_crm_schema.py` — Lead, Opportunity, Interaction creation and serialization
    - `test_opportunity_registry.py` — Add, score, rank, flush events
    - `test_approval_gate.py` — AUTO/REVIEW/ESCALATE routing
    - `test_engines.py` — All five engines importable and produce valid events
    - `test_telemetry.py` — Events written to JSONL, ECS-compatible format
    Target: >= 25 new tests

13. Run all tests:
    ```bash
    python3 -m pytest tests/nontrading/ -v --tb=short
    python3 -m pytest tests/ -x -q --tb=short  # Ensure nothing else broke
    ```

14. Produce handoff artifact at `reports/jjn_phase0_<timestamp>.json`:
    ```json
    {
      "timestamp": "<ISO>",
      "instance_version": "2.8.0",
      "phase": "0 — Foundations",
      "modules_created": ["crm_schema", "opportunity_registry", "approval_gate", "telemetry", "engines/account_intelligence", "engines/outreach", "engines/interaction", "engines/proposal", "engines/learning"],
      "tests_added": N,
      "tests_passing": N,
      "events_schema_valid": true,
      "approval_classes_implemented": ["auto", "review", "escalate"],
      "paper_mode": true,
      "phase_0_checklist": {
        "opportunity_registry": true,
        "crm_schema": true,
        "telemetry": true,
        "dashboards": false,
        "domain_auth": false,
        "templates": false,
        "approval_classes": true,
        "paper_mode": true
      },
      "next_phase_1_prerequisites": ["SQLite backing for registry", "Elastic index templates", "Kibana dashboard", "First curated lead list"]
    }
    ```

## VERIFICATION

```bash
python3 -m pytest tests/nontrading/ -v --tb=short
python3 -m pytest tests/ -x -q --tb=short
python3 -c "from nontrading.crm_schema import Lead, Opportunity, Interaction; print('CRM imports OK')"
python3 -c "from nontrading.opportunity_registry import OpportunityRegistry; print('Registry imports OK')"
python3 -c "from nontrading.engines.account_intelligence import AccountIntelligenceEngine; print('Engine imports OK')"
python3 -c "from nontrading.approval_gate import ApprovalGate; print('Approval imports OK')"
```

## HANDOFF

```
INSTANCE #7 HANDOFF
---
Files created: [list all new files]
Tests added: N new tests
Tests passing: N/N
Modules importable: [yes/no per module]
Phase 0 checklist: [X items complete out of 8]
Events schema: [valid/invalid]
Paper mode: [enforced/not enforced]
Unverified: [anything next cycle should check]
Next instance can edit these files: [yes/no per file]
```
