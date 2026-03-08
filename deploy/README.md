# Deploy Assets

This directory holds deployment and infrastructure assets for the Elastifund hub-and-spoke stack.

## What You’ll Find Here

- `init/` bootstrap scripts for local Docker Compose
- `k8s/` starter Kubernetes manifests for the hub gateway and shared services
- `kibana/` saved-object and dashboard packs for the observability layer

## Fast Local Path

From the repo root:

```bash
make onboard
make preflight
docker compose up --build
```

## When To Edit This Directory

Edit `deploy/` when you are changing:

- local or hosted bootstrapping
- container/service startup behavior
- shared observability assets
- infrastructure wiring for the hub, not trading strategy logic

## Related Docs

- [docs/FORK_AND_RUN.md](../docs/FORK_AND_RUN.md)
- [docs/api/README.md](../docs/api/README.md)
- [deploy/kibana/phase6/README.md](kibana/phase6/README.md)
