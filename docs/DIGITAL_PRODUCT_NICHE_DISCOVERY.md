# Digital Product Niche Discovery

## Purpose

This module implements the first digital-product lane for the broader Elastifund non-trading architecture: research niches before any content-generation or listing automation is allowed to spend budget.

It is intentionally narrow:

- rank Etsy/Gumroad-style niches from normalized marketplace research snapshots
- score them with a deterministic composite formula
- persist the results in SQLite for auditability
- emit Elastic bulk NDJSON so the same rankings can be indexed into `elastifund-knowledge`

The module does not place listings, call image-generation APIs, or require a live Elasticsearch cluster.

## Scoring Model

The core score matches the architecture brief:

```text
composite_score = (monthly_demand * average_price * profit_margin) / competition_count
```

Implementation details:

- `competition_count` is clamped with a configurable floor so sparse niches do not divide by zero
- `profit_margin` is normalized into a `0.0-1.0` ratio
- ties break toward higher demand, then higher price, then lower competition
- each niche also gets a deterministic 768-dimensional hash embedding for semantic matching

## Files

- `nontrading/digital_products/config.py`
- `nontrading/digital_products/models.py`
- `nontrading/digital_products/embeddings.py`
- `nontrading/digital_products/store.py`
- `nontrading/digital_products/research.py`
- `nontrading/digital_products/main.py`

## Run Once

```bash
python3 -m nontrading.digital_products.main \
  --run-once \
  --source-file nontrading/tests/fixtures/sample_product_niches.json \
  --emit-elastic-bulk data/digital_product_exports/sample.ndjson
```

What this does:

- reads normalized niche candidates from JSON
- filters candidates by the configured demand and price minimums
- ranks them and stores the run in `data/digital_products.db`
- writes Elastic bulk NDJSON if requested

## Environment Variables

- `JJ_DP_DB_PATH`
- `JJ_DP_EXPORT_DIR`
- `JJ_DP_MARKETPLACE`
- `JJ_DP_RESULT_LIMIT`
- `JJ_DP_EMBEDDING_DIMS`
- `JJ_DP_COMPETITION_FLOOR`
- `JJ_DP_MIN_MONTHLY_DEMAND`
- `JJ_DP_MIN_AVG_PRICE`
- `JJ_DP_ELASTIC_INDEX`

## Elastic Export Shape

Each ranked niche can be exported as a document with:

- `doc_type=digital_product_niche`
- marketplace, niche slug, title, product type, and keywords
- demand, price, competition, profit margin, and composite score
- `vector` with 768 dimensions
- metadata and run identifiers

This keeps the local repo SQLite-first while preserving a clean upgrade path to the Elastic knowledge hub.
