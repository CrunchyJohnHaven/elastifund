# Elastifund.io Demo Script

This script is built for a 12-15 minute internal demo. It shows what exists today, then uses the Elastic-backed hub scaffold to explain the next layer.

## Demo objective

Show the full story:

1. fork and bootstrap the platform
2. start the Elastic-backed hub
3. run one trading-facing surface
4. run one non-trading lane
5. show the flywheel and knowledge-sharing path
6. close with the honest caveat that autonomy is supervised, not magical

## Pre-demo checklist

- `.env` exists and contains safe local values
- Docker is running
- the root Python environment can run `data_layer` and `nontrading` CLIs
- a separate environment can run the FastAPI export or dashboard if needed
- do not use live credentials for a recorded or shared demo

## Part 1: Show the repo shape

Narration:

"This is not one bot. It is a monorepo with live execution, a research flywheel, a non-trading lane, and a hub scaffold."

Screen points:

- `bot/` and `polymarket-bot/`
- `flywheel/`
- `nontrading/`
- `hub/`
- `deploy/`

## Part 2: Start the hub stack

Command:

```bash
cp .env.example .env
docker compose up --build -d
```

Narration:

"This brings up Elasticsearch, Kibana, Kafka, Redis, and the hub gateway. The gateway is the thin control surface for a bigger hub-and-spoke platform."

Smoke checks:

```bash
curl http://localhost:8000/healthz
curl http://localhost:8000/v1/topology
```

What to point out:

- dependency health
- shared index names
- shared topic names
- privacy tiers and the private boundary

## Part 3: Show the current API surface

Narration:

"There are two real HTTP surfaces in the repo today: the hub gateway and the trading dashboard API."

Show the generated specs:

```bash
python3 -m venv .venv-openapi
source .venv-openapi/bin/activate
pip install fastapi pydantic-settings sqlalchemy structlog
python scripts/export_openapi_specs.py
ls docs/api
```

Files to open:

- `docs/api/elastifund-hub.openapi.json`
- `docs/api/polymarket-dashboard.openapi.json`
- `docs/api/README.md`

Point out:

- `/v1/topology` on the hub
- `/kill`, `/risk`, and `/execution` on the dashboard
- the explicit note that auth and safety are documented, not hand-waved

## Part 4: Run the non-trading digital-product lane

Command:

```bash
python3 -m nontrading.digital_products.main \
  --run-once \
  --source-file nontrading/tests/fixtures/sample_product_niches.json \
  --top 3 \
  --emit-elastic-bulk reports/demo/digital-products.bulk.ndjson
```

Narration:

"This is the pragmatic first non-trading lane: niche discovery for digital products. It is cheap, low-friction, and naturally produces shared knowledge."

What to point out:

- ranked niches
- composite scoring
- generated bulk payload for Elasticsearch ingestion

Open or mention:

- `reports/demo/digital-products.bulk.ndjson`
- `docs/NON_TRADING_EARNING_AGENT_DESIGN.md`

## Part 5: Run one flywheel cycle

Command:

```bash
python3 -m data_layer flywheel-cycle \
  --input docs/examples/flywheel_cycle.sample.json \
  --artifact-dir reports/flywheel/demo \
  --json
```

Narration:

"The flywheel does not rewrite the live bot. It evaluates evidence, emits promotion decisions, and produces artifacts that humans or later automation can review."

What to point out:

- scorecard output
- promotion and demotion decisions
- artifact generation under `reports/flywheel/demo`

## Part 6: Tie it back to Elastic

Open:

- `docs/launch/ELASTIC_LEADERSHIP_PITCH_DECK.md`

Narration:

"The reason Elastic matters is that this platform needs search, metrics, dashboards, vector similarity, and observability in one place. Without that, the operational overhead swallows the product."

## Part 7: Close with the honest caveat

Use this line directly:

"What is real today is supervised automation plus a growing shared-evidence layer. What is not yet real is a set-it-and-forget-it autonomous money machine, and the architecture is intentionally honest about that."

## Optional add-ons

If time allows:

- open Kibana on `http://localhost:5601`
- show `docs/ELASTIFUND_IO_FOUNDATION.md`
- show `docs/adr/` to prove the architecture decisions are documented and reviewable
