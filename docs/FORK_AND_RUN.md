# Fork And Run

This is the lowest-friction path for booting Elastifund from a fresh fork.

Use this guide if:

- you want the repo running locally as fast as possible
- you have not worked in this monorepo before
- you want to verify the stack before editing code

If you want to pair Codex and Claude Code on top of that booted fork, continue to [docs/PARALLEL_AGENT_WORKFLOW.md](docs/PARALLEL_AGENT_WORKFLOW.md) after this guide.

## What This Starts

The repo-root stack can bring up:

- Elasticsearch
- Kibana
- Kafka
- Redis
- the FastAPI hub gateway at `http://localhost:8080`
- a bootstrap agent that registers itself with that hub

If all you want is the simplest working boot, stay at the repo root and ignore nested subprojects for now.

## Before You Start

Install these first:

- Git
- Python 3
- Docker Desktop or Docker Engine if you want the full local stack

If `docker --version` fails, you can still do the non-Docker setup and test pass. You just will not be able to launch the full containerized stack yet.

## Fastest Verified Setup

```bash
git clone https://github.com/YOUR-GITHUB-USERNAME/elastifund.git
cd elastifund
python3 scripts/doctor.py
python3 scripts/quickstart.py
```

That is the lowest-friction path for a first run.

If you want to prepare the repo first and bring Docker up separately:

```bash
python3 scripts/quickstart.py --prepare-only
docker compose up --build
```

If you want the full local developer verification pass:

```bash
python3 -m venv .venv
source .venv/bin/activate
make bootstrap
make verify
```

If you also want to sanity-check the current non-trading lane:

```bash
make test-nontrading
make smoke-nontrading
```

## Bring Up The Full Local Stack

```bash
docker compose up --build
```

Then check:

```bash
curl http://localhost:8080/healthz
curl http://localhost:8080/api/v1/agents
```

## What Success Looks Like

You are in good shape when:

- `make test` passes
- `http://localhost:8080/healthz` returns JSON
- `http://localhost:8080/api/v1/agents` shows at least one registered agent
- Kibana opens at `http://localhost:5601`

The first health check may say `degraded` for a short time while services warm up. Give it 30-60 seconds, then retry.

## Share One Hub Across Multiple Forks

The supported collaboration model right now is deliberately simple:

- one host hub
- many spoke forks

To host a shared hub, run:

```bash
python3 scripts/quickstart.py --prepare-only \
  --agent-name "john-main" \
  --hub-external-url "https://your-public-hub.example"
docker compose up --build
```

Then share only these values with trusted collaborators:

- your public hub URL
- your `ELASTIFUND_HUB_BOOTSTRAP_TOKEN` from `.env`

Do not share wallet keys, exchange credentials, or any other secret just to let someone join your hub.

## Join Someone Else’s Running Hub

Ask the host for:

- their public hub URL
- their hub bootstrap token

Then run this in your own fork:

```bash
python3 scripts/quickstart.py --prepare-only \
  --agent-name "alice-laptop" \
  --hub-url "https://your-friend-hub.example" \
  --hub-bootstrap-token "paste-the-shared-token-here"
docker compose up --build
```

That keeps your local fork running, but points your bootstrap agent at the shared coordination hub.

## Confirm That Two Forks Can See Each Other

On the host machine:

```bash
curl https://your-public-hub.example/api/v1/agents
```

You should see both agents in the registry.

## Troubleshooting

`docker: command not found`

- Install Docker Desktop or Docker Engine, then rerun `docker compose up --build`.

`hub request failed 401`

- The bootstrap token is wrong. Ask the host for the exact `ELASTIFUND_HUB_BOOTSTRAP_TOKEN` again.

`hub is unreachable`

- The hub URL is wrong, the host is offline, or the host has not opened the right port.

`address already in use`

- Another service is already using one of the configured ports. Adjust the port values in `.env` and rerun.

`healthz` stays degraded for several minutes

- Run `docker compose ps`.
- Check `docker compose logs hub-gateway`.
- Check `docker compose logs elasticsearch`.

## What Was Verified While Writing This

On March 8, 2026, the repo passed:

- `python3 scripts/doctor.py`
- `python3 scripts/quickstart.py --prepare-only`
- `make hygiene`
- `make test`
- `make test-polymarket`
- a local two-agent handshake where two separate env identities registered and heartbeated into the same hub registry

The only step not executed directly in this environment was `docker compose up --build`, because Docker was not installed here.
