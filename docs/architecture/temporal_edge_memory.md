# Temporal Edge Memory Graph (TEMG) -- Architecture Specification

**Version:** 1.0.0
**Date:** 2026-03-22
**Author:** JJ (autonomous)
**Status:** Design specification. Not yet implemented.

---

## 1. Problem Statement

Elastifund has 110 research dispatches, 131 tracked strategies, 50+ closed trades, 18 architectural modules, and a reflexion memory system (`bot/reflexion_memory.py`) that stores per-trade reflections with TF-IDF retrieval. None of these systems answer the question that actually matters: **"What kind of edge worked, when, under which regime, and why?"**

The reflexion memory is flat. It stores individual trade critiques but cannot represent causal chains (dispatch led to thesis, thesis was promoted, promotion succeeded under regime X but failed under regime Y). The dispatches are markdown files with no machine-queryable structure. The regime detector (`bot/regime_detector.py`) identifies changepoints but does not record what doctrine was active when the changepoint hit.

TEMG solves this by layering a temporal knowledge graph over the existing infrastructure. Every node carries temporal bounds. Every edge carries causal semantics. The graph accumulates facts that can be true for a period and then become false, without losing the historical record.

---

## 2. Node Types

All nodes share a common temporal envelope:

```python
@dataclass
class TemporalEnvelope:
    node_id: str                    # UUID
    node_type: str                  # Discriminator
    valid_from: float               # Unix timestamp -- when this fact became true
    valid_to: float | None          # Unix timestamp -- when invalidated (None = still active)
    confidence_at_creation: float   # 0.0-1.0 at insertion time
    confidence_current: float       # 0.0-1.0 updated by decay or new evidence
    source_ref: str                 # File path, dispatch ID, or trade ID that created this node
    superseded_by: str | None       # node_id of the node that replaced this one
```

### 2.1 Observation

A raw empirical fact extracted from trading data, market scans, or external research.

```python
@dataclass
class Observation(TemporalEnvelope):
    node_type: str = "observation"
    content: str                    # Natural language summary
    data_points: dict               # Structured payload (e.g., {"win_rate": 0.514, "n": 243})
    observation_class: str          # "performance_stat" | "market_anomaly" | "fill_behavior" | "api_behavior"
    tags: list[str]                 # ["btc5", "down_bias", "hour_03_06"]
```

Examples:
- "BTC5 DOWN trades profitable 03-06 ET, losing 00-02 ET" (from DISPATCH_102 CSV analysis)
- "skip_delta_too_large accounts for 54% of local BTC5 entries" (from VPS DB scan)
- "All 47 BTC closed trades resolved profitably on March 11" (from wallet reconciliation)

### 2.2 MarketCondition

A characterization of the environment at a point or period in time.

```python
@dataclass
class MarketCondition(TemporalEnvelope):
    node_type: str = "market_condition"
    condition_type: str             # "volatility_regime" | "liquidity_state" | "time_of_day" | "orderbook_shape"
    parameters: dict                # {"btc_5m_volatility": 0.023, "spread_bps": 12, "hour_et": 4}
    regime_label: str | None        # "high_vol" | "low_vol" | "transition" (from regime_detector)
    bocpd_run_length: int | None    # Current run length from RegimeDetector at this timestamp
```

### 2.3 ThesisPacket

A testable hypothesis about an edge, with explicit promotion criteria.

```python
@dataclass
class ThesisPacket(TemporalEnvelope):
    node_type: str = "thesis_packet"
    thesis_id: str                  # e.g., "hyp_down_up0.49_down0.51_hour_et_11"
    thesis_family: str              # "btc5_directional" | "structural_alpha" | "time_of_day_filter"
    description: str                # Human-readable thesis statement
    promotion_criteria: dict        # {"min_win_rate": 0.53, "min_profit_factor": 1.10, "min_trades": 100}
    current_evidence: dict          # {"win_rate": 0.514, "profit_factor": 1.01, "trades": 243}
    status: str                     # "hypothesis" | "testing" | "promoted" | "demoted" | "killed"
    dispatch_refs: list[str]        # ["DISPATCH_102", "DISPATCH_106"]
```

### 2.4 PromotionDecision

A record of a gate evaluation -- did a thesis pass or fail its promotion criteria?

```python
@dataclass
class PromotionDecision(TemporalEnvelope):
    node_type: str = "promotion_decision"
    thesis_id: str                  # Links to ThesisPacket
    decision: str                   # "promote" | "hold" | "demote" | "kill"
    gate_results: dict              # {"win_rate": {"required": 0.53, "actual": 0.514, "pass": False}, ...}
    capital_before: float           # Position size before decision
    capital_after: float            # Position size after decision
    rationale: str                  # Natural language explanation
```

### 2.5 LiveOutcome

An aggregated trading result over a defined period, linked to the thesis and conditions active at the time.

```python
@dataclass
class LiveOutcome(TemporalEnvelope):
    node_type: str = "live_outcome"
    period_start: float             # Unix timestamp
    period_end: float               # Unix timestamp
    thesis_id: str                  # Which thesis was active
    trade_count: int
    win_count: int
    gross_pnl: float
    net_pnl: float
    max_drawdown: float
    sharpe_estimate: float | None   # None if insufficient data
    hour_breakdown: dict | None     # {"03": +12.50, "04": +8.20, "08": -6.10}
```

### 2.6 DoctrineCandidate

A consolidated operating rule derived from accumulated evidence. Doctrine is what the system believes it should do right now.

```python
@dataclass
class DoctrineCandidate(TemporalEnvelope):
    node_type: str = "doctrine_candidate"
    doctrine_id: str                # e.g., "btc5_down_only_0306et_v2"
    rule_text: str                  # "Trade BTC5 DOWN only, hours 03-06 ET, $5/trade, maker only"
    parameters: dict                # {"direction": "DOWN", "hours_et": [3,4,5,6], "size_usd": 5}
    supporting_outcomes: list[str]  # List of LiveOutcome node_ids
    contradicting_outcomes: list[str]
    strength: float                 # 0.0-1.0, computed from evidence balance
    active: bool                    # Is this doctrine currently deployed?
```

### 2.7 RegimeState

A snapshot of the regime detector output, stored as a graph node so it can be joined to everything else.

```python
@dataclass
class RegimeState(TemporalEnvelope):
    node_type: str = "regime_state"
    regime: str                     # "stable" | "transition" | "warmup"
    run_length: int
    changepoint_prob: float
    regime_mean: float
    regime_var: float
    bocpd_params: dict              # Hazard rate, NIG hyperparams at this snapshot
```

---

## 3. Edge Types

Edges are first-class objects with their own temporal bounds. An edge that was true in March may be invalidated in April.

```python
@dataclass
class TemporalEdge:
    edge_id: str                    # UUID
    edge_type: str                  # Discriminator
    source_node_id: str
    target_node_id: str
    valid_from: float
    valid_to: float | None          # None = still active
    confidence: float               # 0.0-1.0
    metadata: dict                  # Edge-type-specific payload
```

### 3.1 Edge Type Catalog

| Edge Type | Source Node | Target Node | Semantics |
|-----------|-----------|------------|-----------|
| `caused_by` | Observation | Observation / MarketCondition | "This observation was caused by this condition" |
| `motivated` | Observation | ThesisPacket | "This observation led to this thesis being created" |
| `tested_under` | ThesisPacket | MarketCondition | "This thesis was tested during this market condition" |
| `succeeded_under` | LiveOutcome | MarketCondition | "This outcome was profitable under these conditions" |
| `failed_under` | LiveOutcome | MarketCondition | "This outcome lost money under these conditions" |
| `promoted_by` | ThesisPacket | PromotionDecision | "This thesis was promoted/demoted by this gate evaluation" |
| `produced` | ThesisPacket | LiveOutcome | "This thesis, when deployed, produced this outcome" |
| `invalidated_by` | Observation / DoctrineCandidate | Observation / LiveOutcome | "This fact/rule was proven false by new evidence" |
| `evolved_into` | ThesisPacket / DoctrineCandidate | ThesisPacket / DoctrineCandidate | "This earlier version became this newer version" |
| `preceded` | RegimeState | RegimeState | "This regime state came immediately before this one" |
| `active_during` | DoctrineCandidate | RegimeState | "This doctrine was active during this regime" |
| `sourced_from` | ThesisPacket | str (dispatch path) | "This thesis originated from this research dispatch" |
| `contradicts` | Observation | Observation | "These two observations cannot both be true" |

---

## 4. Storage Layer

### 4.1 SQLite Implementation

TEMG uses SQLite for the same reason everything else in this system does: zero-dependency, single-file, WAL-mode, crash-safe. The graph lives in `data/temg.db`.

```sql
-- Nodes table (polymorphic via node_type + payload JSON)
CREATE TABLE IF NOT EXISTS nodes (
    node_id         TEXT PRIMARY KEY,
    node_type       TEXT NOT NULL,
    valid_from      REAL NOT NULL,
    valid_to        REAL,
    confidence_at_creation REAL NOT NULL DEFAULT 1.0,
    confidence_current     REAL NOT NULL DEFAULT 1.0,
    source_ref      TEXT NOT NULL,
    superseded_by   TEXT,
    payload         TEXT NOT NULL,  -- JSON blob with type-specific fields
    created_at      REAL NOT NULL DEFAULT (strftime('%s', 'now')),
    FOREIGN KEY (superseded_by) REFERENCES nodes(node_id)
);

CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(node_type);
CREATE INDEX IF NOT EXISTS idx_nodes_valid_from ON nodes(valid_from);
CREATE INDEX IF NOT EXISTS idx_nodes_valid_to ON nodes(valid_to);
CREATE INDEX IF NOT EXISTS idx_nodes_type_active
    ON nodes(node_type) WHERE valid_to IS NULL;

-- Edges table
CREATE TABLE IF NOT EXISTS edges (
    edge_id         TEXT PRIMARY KEY,
    edge_type       TEXT NOT NULL,
    source_node_id  TEXT NOT NULL,
    target_node_id  TEXT NOT NULL,
    valid_from      REAL NOT NULL,
    valid_to        REAL,
    confidence      REAL NOT NULL DEFAULT 1.0,
    metadata        TEXT NOT NULL DEFAULT '{}',
    created_at      REAL NOT NULL DEFAULT (strftime('%s', 'now')),
    FOREIGN KEY (source_node_id) REFERENCES nodes(node_id),
    FOREIGN KEY (target_node_id) REFERENCES nodes(node_id)
);

CREATE INDEX IF NOT EXISTS idx_edges_type ON edges(edge_type);
CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_node_id);
CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_node_id);
CREATE INDEX IF NOT EXISTS idx_edges_active
    ON edges(edge_type) WHERE valid_to IS NULL;

-- Full-text search on node payloads for natural language queries
CREATE VIRTUAL TABLE IF NOT EXISTS nodes_fts
    USING fts5(node_id, content, tokenize='porter unicode61');
```

### 4.2 Why Not Neo4j / NetworkX / etc.

Neo4j requires a server process. NetworkX is in-memory only. Both add deployment complexity to a system that runs on a single Lightsail instance. SQLite with JSON payloads and indexed edge tables handles the query patterns below at the scale we operate (thousands of nodes, not millions). If the graph exceeds 100k nodes, revisit.

---

## 5. Query Patterns

Each query is expressed as a SQL template. The graph API wraps these in Python methods.

### 5.1 "What edges worked during high-volatility BTC regimes?"

```sql
SELECT
    tp.payload ->> '$.thesis_id' AS thesis,
    tp.payload ->> '$.description' AS description,
    lo.payload ->> '$.net_pnl' AS pnl,
    lo.payload ->> '$.trade_count' AS trades,
    mc.payload ->> '$.parameters.btc_5m_volatility' AS volatility
FROM edges e_su
JOIN nodes lo ON lo.node_id = e_su.source_node_id AND lo.node_type = 'live_outcome'
JOIN nodes mc ON mc.node_id = e_su.target_node_id AND mc.node_type = 'market_condition'
JOIN edges e_prod ON e_prod.target_node_id = lo.node_id AND e_prod.edge_type = 'produced'
JOIN nodes tp ON tp.node_id = e_prod.source_node_id AND tp.node_type = 'thesis_packet'
WHERE e_su.edge_type = 'succeeded_under'
  AND CAST(mc.payload ->> '$.parameters.btc_5m_volatility' AS REAL) > 0.02
  AND e_su.valid_to IS NULL
ORDER BY CAST(lo.payload ->> '$.net_pnl' AS REAL) DESC;
```

### 5.2 "Which thesis families have been promoted and then demoted?"

```sql
SELECT
    tp.payload ->> '$.thesis_family' AS family,
    tp.payload ->> '$.thesis_id' AS thesis,
    pd_promote.payload ->> '$.rationale' AS promote_reason,
    pd_demote.payload ->> '$.rationale' AS demote_reason,
    pd_promote.valid_from AS promoted_at,
    pd_demote.valid_from AS demoted_at
FROM nodes tp
JOIN edges e_p ON e_p.source_node_id = tp.node_id AND e_p.edge_type = 'promoted_by'
JOIN nodes pd_promote ON pd_promote.node_id = e_p.target_node_id
    AND pd_promote.payload ->> '$.decision' = 'promote'
JOIN edges e_d ON e_d.source_node_id = tp.node_id AND e_d.edge_type = 'promoted_by'
JOIN nodes pd_demote ON pd_demote.node_id = e_d.target_node_id
    AND pd_demote.payload ->> '$.decision' IN ('demote', 'kill')
WHERE tp.node_type = 'thesis_packet'
  AND pd_demote.valid_from > pd_promote.valid_from
ORDER BY pd_demote.valid_from DESC;
```

### 5.3 "What is the current best doctrine for hour 03-06 ET?"

```sql
SELECT
    dc.payload ->> '$.doctrine_id' AS doctrine,
    dc.payload ->> '$.rule_text' AS rule,
    dc.payload ->> '$.strength' AS strength,
    dc.confidence_current AS confidence
FROM nodes dc
WHERE dc.node_type = 'doctrine_candidate'
  AND dc.valid_to IS NULL
  AND CAST(dc.payload ->> '$.active' AS INTEGER) = 1
  AND EXISTS (
      SELECT 1 FROM json_each(dc.payload ->> '$.parameters.hours_et') je
      WHERE CAST(je.value AS INTEGER) BETWEEN 3 AND 6
  )
ORDER BY CAST(dc.payload ->> '$.strength' AS REAL) DESC
LIMIT 5;
```

### 5.4 "What changed between the March 11 winning session and March 15 loss?"

```sql
-- Collect all active conditions during both periods, then diff
WITH march_11 AS (
    SELECT node_id, node_type, payload
    FROM nodes
    WHERE valid_from <= 1741651200  -- 2026-03-11 00:00 UTC
      AND (valid_to IS NULL OR valid_to >= 1741737600)  -- through end of March 11
      AND node_type IN ('market_condition', 'regime_state', 'doctrine_candidate')
),
march_15 AS (
    SELECT node_id, node_type, payload
    FROM nodes
    WHERE valid_from <= 1741996800  -- 2026-03-15 00:00 UTC
      AND (valid_to IS NULL OR valid_to >= 1742083200)
      AND node_type IN ('market_condition', 'regime_state', 'doctrine_candidate')
)
SELECT 'only_march_11' AS period, m11.node_type, m11.payload
FROM march_11 m11
WHERE m11.node_id NOT IN (SELECT node_id FROM march_15)
UNION ALL
SELECT 'only_march_15', m15.node_type, m15.payload
FROM march_15 m15
WHERE m15.node_id NOT IN (SELECT node_id FROM march_11)
ORDER BY period, node_type;
```

### 5.5 "Which research dispatches led to profitable trades?"

```sql
SELECT
    tp.payload ->> '$.dispatch_refs' AS dispatches,
    tp.payload ->> '$.thesis_id' AS thesis,
    SUM(CAST(lo.payload ->> '$.net_pnl' AS REAL)) AS total_pnl,
    SUM(CAST(lo.payload ->> '$.trade_count' AS INTEGER)) AS total_trades
FROM nodes tp
JOIN edges e_prod ON e_prod.source_node_id = tp.node_id AND e_prod.edge_type = 'produced'
JOIN nodes lo ON lo.node_id = e_prod.target_node_id AND lo.node_type = 'live_outcome'
WHERE tp.node_type = 'thesis_packet'
  AND CAST(lo.payload ->> '$.net_pnl' AS REAL) > 0
GROUP BY tp.node_id
ORDER BY total_pnl DESC;
```

---

## 6. Memory Compaction Rules

Unbounded growth kills query performance and makes the graph unreadable. These rules keep TEMG finite.

### 6.1 Retention Tiers

| Tier | Age | Treatment |
|------|-----|-----------|
| **Hot** | < 30 days | Full resolution. All nodes, all edges, all payloads. |
| **Warm** | 30-90 days | Merge consecutive identical MarketCondition nodes into single spans. Collapse hourly RegimeState snapshots into daily summaries. Observation nodes with confidence_current < 0.2 archived. |
| **Cold** | 90-365 days | Only ThesisPacket, PromotionDecision, LiveOutcome, and DoctrineCandidate survive. MarketCondition and RegimeState compressed to daily summaries. Observations deleted unless they are the sole `motivated` source for a surviving ThesisPacket. |
| **Archive** | > 365 days | Only DoctrineCandidate and PromotionDecision survive. Everything else deleted. The system remembers *what it concluded* and *what gates it passed/failed*, but discards raw observations. |

### 6.2 Compaction Procedure

Runs once daily during the maintenance window (05:00-05:30 UTC, outside active BTC trading hours).

```
1. Mark expired: SET valid_to = now() on any node whose confidence_current < 0.05.
2. Merge spans: For consecutive MarketCondition nodes with identical condition_type
   and parameters (within tolerance), merge into a single node spanning the full period.
   Preserve the earliest valid_from and latest valid_to.
3. Archive observations: Move Warm-tier Observations with confidence < 0.2 to an
   archive table (nodes_archive, same schema). Delete from nodes.
4. Summarize regimes: Replace Cold-tier RegimeState hourly snapshots with daily
   summaries (mean changepoint_prob, modal regime, mean run_length).
5. Purge cold observations: Delete Cold-tier Observations that have no inbound
   'motivated' edges to surviving ThesisPackets.
6. Vacuum: Run VACUUM on temg.db after deletions.
```

### 6.3 Contradiction Resolution

When a new Observation contradicts an existing one:

1. Create the new Observation node with `valid_from = now()`.
2. Create a `contradicts` edge between the old and new nodes.
3. Set the old node's `valid_to = now()` and reduce `confidence_current` by 50%.
4. If the old node's confidence drops below 0.1, mark it superseded (`superseded_by = new_node_id`).
5. Any DoctrineCandidate that cited the old Observation as supporting evidence has its `strength` recomputed by dropping that evidence source.
6. If the recomputed strength drops below 0.3, the DoctrineCandidate is flagged for review (not automatically deactivated -- doctrine changes require a PromotionDecision node).

The old node is never deleted during Hot or Warm tiers. The historical record of "we believed X and then learned not-X" is itself valuable data.

### 6.4 Regime Change Handling

When `bot/regime_detector.py` fires a changepoint (STABLE -> TRANSITION):

1. Close the current RegimeState node (`valid_to = now()`).
2. Create a new RegimeState node with `regime = "transition"`.
3. Create a `preceded` edge from old to new.
4. For every active DoctrineCandidate, create an `active_during` edge to the closing RegimeState.
5. Do NOT automatically invalidate active doctrine. The system continues trading under existing doctrine until live outcomes under the new regime produce enough evidence to trigger a PromotionDecision (promote, hold, demote, or kill).
6. If the regime stabilizes (TRANSITION -> STABLE with new parameters), create a new RegimeState node and start accumulating LiveOutcome evidence for doctrine re-evaluation.

This is deliberate: regime changes are signals to *watch more carefully*, not to *immediately stop*. The March 11 winning session may have been a brief regime. Killing doctrine on every regime blip would destroy the system's ability to accumulate evidence.

### 6.5 Growth Bounds

Hard limits enforced by the compaction procedure:

| Metric | Limit | Action when exceeded |
|--------|-------|---------------------|
| Total Hot-tier nodes | 10,000 | Force Warm compaction on oldest 20% |
| Total Warm-tier nodes | 50,000 | Force Cold compaction on oldest 20% |
| Database file size | 500 MB | Emergency compaction: delete all Archive-tier, compress Cold |
| Edges per node | 200 | Prune lowest-confidence edges |
| RegimeState nodes per day | 288 (one per 5 min) | Summarize to hourly during Warm transition |

---

## 7. Integration with Existing Modules

### 7.1 reflexion_memory.py

ReflexionMemory continues to operate independently for per-trade TF-IDF retrieval. TEMG does not replace it. Instead, when ReflexionMemory stores a new reflection, a hook creates:
- An Observation node (the trade result facts)
- A LiveOutcome node (if this is the Nth trade completing a reporting period)
- Edges linking the observation to the active ThesisPacket and MarketCondition

The TF-IDF retrieval in ReflexionMemory handles "find similar past trades." TEMG handles "understand why those trades happened and whether the conditions still hold."

### 7.2 regime_detector.py

On every `RegimeDetector.observe()` call, if the regime state changes (or every N observations in stable regime), emit a RegimeState node and appropriate edges. The detector already produces `RegimeSnapshot` dataclasses -- TEMG wraps these.

### 7.3 Research Dispatches

A batch ingestion script (`scripts/ingest_dispatches_to_temg.py`, to be built) parses dispatch markdown files and creates:
- ThesisPacket nodes for each hypothesis mentioned
- Observation nodes for each empirical finding
- `motivated` edges from observations to theses
- `sourced_from` metadata linking to the dispatch file path

### 7.4 Promotion Gate (DISPATCH_102 pattern)

Every time a promotion gate runs (the BTC5 gate pattern from DISPATCH_102), the results are stored as a PromotionDecision node with edges to the evaluated ThesisPacket. This creates an auditable history of every scaling decision and its evidence basis.

### 7.5 ensemble_estimator.py / llm_tournament.py

Before making a probability estimate, query TEMG for:
1. Active DoctrineCandidate nodes matching the market category and time of day
2. Recent LiveOutcome nodes under current MarketCondition
3. Any Observations that contradict the thesis being evaluated

Inject this as structured context alongside the ReflexionMemory context prompt.

---

## 8. API Surface

```python
class TemporalEdgeMemoryGraph:
    def __init__(self, db_path: str = "data/temg.db") -> None: ...

    # --- Node operations ---
    def add_observation(self, content: str, data_points: dict, obs_class: str,
                        tags: list[str], source_ref: str, confidence: float = 1.0) -> str: ...
    def add_market_condition(self, condition_type: str, parameters: dict,
                             regime_label: str | None = None, source_ref: str = "") -> str: ...
    def add_thesis(self, thesis_id: str, family: str, description: str,
                   promotion_criteria: dict, dispatch_refs: list[str]) -> str: ...
    def add_promotion_decision(self, thesis_id: str, decision: str,
                               gate_results: dict, rationale: str,
                               capital_before: float, capital_after: float) -> str: ...
    def add_live_outcome(self, thesis_id: str, period_start: float, period_end: float,
                         trade_count: int, win_count: int, gross_pnl: float,
                         net_pnl: float, max_drawdown: float) -> str: ...
    def add_doctrine(self, doctrine_id: str, rule_text: str, parameters: dict,
                     supporting_outcomes: list[str]) -> str: ...
    def add_regime_state(self, regime: str, run_length: int,
                         changepoint_prob: float, regime_mean: float,
                         regime_var: float) -> str: ...

    # --- Edge operations ---
    def link(self, source_id: str, target_id: str, edge_type: str,
             confidence: float = 1.0, metadata: dict | None = None) -> str: ...
    def invalidate(self, node_id: str, reason: str, invalidated_by: str | None = None) -> None: ...
    def supersede(self, old_node_id: str, new_node_id: str) -> None: ...

    # --- Query operations ---
    def query_active_doctrine(self, hours_et: list[int] | None = None,
                              direction: str | None = None) -> list[dict]: ...
    def query_thesis_history(self, thesis_family: str) -> list[dict]: ...
    def query_outcomes_under_condition(self, condition_type: str,
                                       parameter_filter: dict) -> list[dict]: ...
    def query_dispatch_roi(self) -> list[dict]: ...
    def diff_periods(self, period_a: tuple[float, float],
                     period_b: tuple[float, float]) -> dict: ...
    def search_text(self, query: str, node_type: str | None = None,
                    limit: int = 20) -> list[dict]: ...

    # --- Maintenance ---
    def run_compaction(self) -> dict: ...  # Returns stats on nodes merged/archived/deleted
    def decay_confidence(self, half_life_days: float = 14.0) -> int: ...  # Returns nodes affected
    def stats(self) -> dict: ...
```

---

## 9. Confidence Decay Model

Node confidence decays over time unless refreshed by new supporting evidence.

```
confidence_current = confidence_at_creation * 2^(-age_days / half_life)
```

Default half-lives by node type:

| Node Type | Half-Life (days) | Rationale |
|-----------|-----------------|-----------|
| Observation | 14 | Market microstructure facts go stale fast |
| MarketCondition | 7 | Conditions change within a week |
| ThesisPacket | 30 | Theses deserve a full month of testing |
| PromotionDecision | 90 | Gate decisions remain relevant for a quarter |
| LiveOutcome | 60 | Outcome data stays useful for two months |
| DoctrineCandidate | 30 | Doctrine should be re-validated monthly |
| RegimeState | 7 | Regime snapshots lose relevance quickly |

Confidence is refreshed (reset to a new value) whenever:
- A new LiveOutcome edge connects to a ThesisPacket (thesis stays relevant)
- A new `succeeded_under` edge connects to a DoctrineCandidate (doctrine confirmed)
- A PromotionDecision references the node (explicit gate evaluation)

---

## 10. Bootstrap: Backfilling from Current State

The initial graph is populated from existing artifacts:

| Source | Nodes Created |
|--------|--------------|
| `research/dispatches/DISPATCH_*.md` | ThesisPacket, Observation (parsed from markdown sections) |
| DISPATCH_102 promotion gate results | PromotionDecision (FAIL, 3/6 criteria), linked Observations |
| Wallet reconciliation (50 closed trades) | LiveOutcome (aggregated by day and thesis) |
| `bot/regime_detector.py` state (if DB exists) | RegimeState snapshots |
| `COMMAND_NODE.md` Section 4 | Observations (wallet truth, BTC sleeve performance) |
| `research/edge_backlog_ranked.md` | ThesisPacket stubs for all 131 tracked strategies |
| BTC5 local DB (302 rows) | Observations (skip distribution, fill behavior) |
| DISPATCH_102 CSV analysis | Observations (hour-of-day P&L, direction bias) |

The bootstrap script creates approximately:
- ~200 Observation nodes (from dispatches and trade data)
- ~131 ThesisPacket nodes (from strategy backlog)
- ~10 MarketCondition nodes (from known trading sessions)
- ~5 PromotionDecision nodes (from documented gate evaluations)
- ~10 LiveOutcome nodes (from wallet trade history, aggregated by day)
- ~5 DoctrineCandidate nodes (from current operating rules)
- ~500 edges linking these together

---

## 11. Causal Chain Example

The complete chain for the March 11 BTC5 winning session:

```
Observation: "BTC 5-min markets have 0% maker fee"
  --motivated--> ThesisPacket: "btc5_maker_velocity" (from DISPATCH_075)
    --tested_under--> MarketCondition: {hour_et: 3-8, volatility: "moderate", date: "2026-03-11"}
      --produced--> LiveOutcome: {47 trades, 100% WR, $786 gross, hours 03-08 ET}
        --succeeded_under--> MarketCondition (same)
    --promoted_by--> PromotionDecision: {decision: "hold", gate: DISPATCH_102, reason: "3/6 fail"}

Observation: "DOWN trades +$52.80, UP trades -$38.18" (from CSV analysis)
  --motivated--> ThesisPacket: "btc5_down_only_filter"
    --evolved_into--> DoctrineCandidate: "btc5_down_only_0306et_v1"
      --active_during--> RegimeState: {regime: "stable", run_length: 47}

Observation: "skip_delta_too_large 54% of entries"
  --invalidated_by--> Observation: "delta threshold widened to 0.0050 on VPS"
```

This chain is queryable. "Why did March 11 work?" traverses from LiveOutcome backward through edges to find the MarketCondition, ThesisPacket, and original Observations. "Will it work again?" checks whether the MarketCondition still holds and whether the DoctrineCandidate has been invalidated.

---

## 12. Implementation Sequence

1. **Phase 1 (Week 1):** Build `bot/temg.py` with SQLite schema, node/edge CRUD, and the five query methods from Section 5. Unit tests in `tests/test_temg.py`.
2. **Phase 2 (Week 2):** Build `scripts/ingest_dispatches_to_temg.py` for bootstrap backfill. Populate from DISPATCH_102, wallet data, and strategy backlog.
3. **Phase 3 (Week 3):** Wire TEMG hooks into `regime_detector.py` (RegimeState emission) and `reflexion_memory.py` (Observation + LiveOutcome creation on trade resolution).
4. **Phase 4 (Week 4):** Wire TEMG context injection into `ensemble_estimator.py` and `llm_tournament.py`. Build compaction daemon.
5. **Phase 5 (Ongoing):** Accumulate. Every trade, every dispatch, every gate evaluation feeds the graph. Confidence decays. Compaction runs nightly. The graph becomes the system's long-term memory.

---

*This document is the specification. Implementation begins when John confirms the design or when the next engineering cycle allocates capacity. The graph does not exist yet. Do not reference it as if it does.*
