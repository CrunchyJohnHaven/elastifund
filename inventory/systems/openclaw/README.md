# OpenClaw Adapter

OpenClaw is a sibling benchmark target for Elastifund's `comparison_only` lane.

## Scope

- upstream repo: `https://github.com/openclaw/openclaw.git`
- audited commit: `59bc3c66300ba93a71b4220146e7135950387770`
- upstream version observed on March 10, 2026: `2026.3.9`
- runtime floor: Node `>=22.12.0`
- benchmark posture: isolated AWS sibling stack only

This adapter is deliberately excluded from allocator decisions and live Elastifund state. It exists to compare cycle time, decision counts, model cost, and benchmark outcomes on a shared evidence plane.

## Isolation Rules

- separate namespace: `openclaw-benchmark`
- separate secrets object: `openclaw-benchmark-secrets`
- separate state PVC: `openclaw-benchmark-state`
- separate log index prefix: `elastifund-openclaw-benchmark-*`
- no trading wallets
- no shared DB mounts
- no shared allocator inputs

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
3. Emit the normalized evidence packet:

```bash
python3 scripts/normalize_openclaw_benchmark.py \
  --diagnostics reports/openclaw/raw/diagnostics.jsonl \
  --comparison reports/openclaw/raw/outcomes.json \
  --run-id openclaw-cycle3-comparison-only \
  --output reports/openclaw/normalized/latest.json
```

The output contract is versioned in `inventory/metrics/evidence_plane.py` and always sets:

- `comparison_mode = "comparison_only"`
- `allocator_eligible = false`
- `isolation.wallet_access = "none"`
- `isolation.shared_state_access = "none"`
