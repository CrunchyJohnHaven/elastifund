# OpenClaw Adapter

| Metadata | Value |
|---|---|
| Canonical file | `inventory/systems/openclaw/README.md` |
| Role | OpenClaw comparison-only adapter runbook |
| Adapter status | active scaffold |
| Last updated | 2026-03-11 |

OpenClaw is a sibling benchmark target for Elastifund's `comparison_only` lane.

## Scope

- Upstream repo: `https://github.com/openclaw/openclaw.git`.
- Audited commit: `59bc3c66300ba93a71b4220146e7135950387770`.
- Upstream version observed on March 10, 2026: `2026.3.9`.
- Runtime floor: Node `>=22.12.0`.
- Benchmark posture: isolated AWS sibling stack only.

This adapter is deliberately excluded from allocator decisions and live Elastifund state. It exists to compare cycle time, decision counts, model cost, and benchmark outcomes on a shared evidence plane.

## Canonical Files In This Directory

| File | Classification | Purpose |
|---|---|---|
| `adapter.py` | canonical adapter implementation | Normalization and packet generation for OpenClaw comparison runs |
| `upstream.lock.json` | canonical upstream lock | Version/commit/runtime contract for reproducible builds |
| `openclaw.benchmark.json` | canonical config template | Isolated OpenClaw runtime config used by benchmark scaffolding |
| `README.md` | canonical runbook | Operator instructions and isolation policy |

`openclaw.benchmark.json` and `upstream.lock.json` intentionally keep dot-style names for compatibility with existing benchmark references.

## Isolation Rules

- Separate namespace: `openclaw-benchmark`.
- Separate secrets object: `openclaw-benchmark-secrets`.
- Separate state PVC: `openclaw-benchmark-state`.
- Separate log index prefix: `elastifund-openclaw-benchmark-*`.
- No trading wallets.
- No shared DB mounts.
- No shared allocator inputs.

## Build

```bash
git clone https://github.com/openclaw/openclaw.git /tmp/openclaw-benchmark
git -C /tmp/openclaw-benchmark checkout 59bc3c66300ba93a71b4220146e7135950387770
docker build \
  -t openclaw-benchmark:59bc3c6 \
  --build-arg OPENCLAW_EXTENSIONS="diagnostics-otel" \
  /tmp/openclaw-benchmark
```

## Deploy Scaffold

Apply the manifests in `deploy/k8s/` after filling the example secret:

```bash
kubectl apply -f deploy/k8s/openclaw-benchmark-namespace.yaml
kubectl apply -f deploy/k8s/openclaw-benchmark-configmap.yaml
kubectl apply -f deploy/k8s/openclaw-benchmark-secret.example.yaml
kubectl apply -f deploy/k8s/openclaw-benchmark-deployment.yaml
kubectl apply -f deploy/k8s/openclaw-benchmark-networkpolicy.yaml
```

The deployment only exposes a pod-local gateway. Use `kubectl port-forward` for the benchmark operator path instead of creating a public ingress.

## Normalize Telemetry

1. Export OpenClaw diagnostics as JSONL from the isolated stack.
2. Provide a shared comparison file with per-case Elastifund vs OpenClaw outcomes.
3. Emit the normalized evidence packet.

```bash
python3 scripts/normalize_openclaw_benchmark.py \
  --diagnostics reports/openclaw/raw/diagnostics.jsonl \
  --comparison reports/openclaw/raw/outcomes.json \
  --run-id openclaw-cycle3-comparison-only \
  --output reports/openclaw/normalized/latest.json
```

The output contract is versioned in `inventory/metrics/evidence_plane.py` and always sets `comparison_mode = "comparison_only"` and `allocator_eligible = false`, with isolation guards of `wallet_access = "none"` and `shared_state_access = "none"`.
