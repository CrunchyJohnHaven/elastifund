# Elastic Employee Build Dispatch

| Metadata | Value |
|---|---|
| Canonical file | `docs/ops/elastic_employee_build_dispatch_20260311.md` |
| Role | Internal onboarding trial dispatch for Elastic contributors |
| Source packet | `COMMAND_NODE.md` |
| Last updated | 2026-03-11 |

## INSTANCE ROSTER (PASTE TARGETS)

Instance 1 - GPT-5.3-Codex / Medium - Cold-clone the repo into paper mode and log every setup friction point  
Instance 2 - GPT-4 / Low - Turn friction into an idiot-proof FAQ and blocker map  
Instance 3 - Claude Code / Sonnet - Publish and harden the hidden `/build/` onboarding packet  
Instance 4 - Claude Code / Opus - Resolve contradictions across secrets, access, infra, and policy boundaries  
Instance 5 - GPT-4 / Medium - Validate the shared paper-hub path and the minimum-secret collaboration contract  
Instance 6 - GPT-5.3-Codex / High - Consolidate evidence, verify changes, and issue the next-cycle work order

## CURRENT TRUTH SNAPSHOT

- `README.md -> docs/FORK_AND_RUN.md` is the canonical start path for a fresh contributor.
- `docs/FORK_AND_RUN.md` already defines an Elastic-employee-safe path: `make doctor`, `python3 scripts/quickstart.py --prepare-only`, `python3 -m venv .venv`, `make bootstrap`, `make verify`, `make smoke-nontrading`.
- `scripts/quickstart.py` and `scripts/elastifund_setup.py` exist and support non-interactive onboarding plus shared paper-hub overrides.
- `.env.example` ships onboarding defaults with `ELASTIFUND_AGENT_RUN_MODE=paper`.
- `docs/FORK_AND_RUN.md` explicitly says the shared host/spoke flow is paper-mode only and says not to share wallet keys, exchange credentials, treasury credentials, or other live secrets just to let someone join the hub.
- `develop/index.html` is the public onboarding route and `build/index.html` is the hidden cohort packet for this trial run.
- The current runtime/public posture is still blocked/shadow-mismatched, so onboarding must stay paper-mode safe and artifact-backed.
- Latest checked-in verification summary is `1641 passed, 5 warnings in 37.10s; 25 passed, 1 warning in 4.56s`.
- After doc or config changes, `make hygiene` is required.

## DISPATCH PLAN BY INSTANCE

### Instance 1 - GPT-5.3-Codex / Medium

Objective: Prove that a fresh fork can boot in local paper mode with no private help.

Inputs:
- `README.md`
- `docs/FORK_AND_RUN.md`
- `.env.example`
- `scripts/doctor.py`
- `scripts/quickstart.py`
- `scripts/elastifund_setup.py`

Actions:
1. Fork the repo into a personal GitHub namespace.
2. Clone the fork into a clean local directory.
3. Run `make doctor`.
4. Run `python3 scripts/quickstart.py --prepare-only`.
5. Create and activate `.venv`.
6. Run `make bootstrap`.
7. Run `make verify`.
8. Run `make smoke-nontrading`.
9. Record every blocking command, exact error, and missing dependency.

Success checks:
- `.env` exists and `state/elastifund/runtime-manifest.json` exists.
- No step required a live wallet key, trading key, treasury secret, or private VPS credential.
- Either the verification pass is green or the first blocker is explicit and reproducible.
- If there is no defensible direct ARR claim from this work, report `candidate_delta_arr_bps=0` and treat the result as info-gain plus velocity gain.

Required outputs:
- `candidate_delta_arr_bps`
- `expected_improvement_velocity_delta`
- `arr_confidence_score`
- `block_reasons`
- `finance_gate_pass`
- `one_next_cycle_action`

### Instance 2 - GPT-4 / Low

Objective: Convert setup friction into an idiot-proof FAQ and blocker map that a new employee can follow cold.

Inputs:
- `build/index.html`
- `develop/index.html`
- `docs/FORK_AND_RUN.md`
- friction log from Instance 1

Actions:
1. Group every blocker into one of four buckets: machine setup, Python/env, Docker, or repo workflow.
2. Write one plain-English answer for each blocker using the exact command or file that resolves it.
3. Add missing answers to the hidden onboarding packet.
4. Remove duplicate or conflicting setup guidance.
5. Mark any unanswered blocker as a hold/repair branch with a retry condition.

Success checks:
- Every blocker from Instance 1 maps to one visible answer or one explicit hold branch.
- The page answers fork vs clone, local vs shared hub, secrets needed, Docker optionality, and what to report back.
- No answer invents a secret, a private URL, or an undocumented setup path.

Required outputs:
- `candidate_delta_arr_bps`
- `expected_improvement_velocity_delta`
- `arr_confidence_score`
- `block_reasons`
- `finance_gate_pass`
- `one_next_cycle_action`

### Instance 3 - Claude Code / Sonnet

Objective: Publish the hidden `/build/` route so the cohort has one clean, idiot-proof setup packet.

Inputs:
- `REPLIT_NEXT_BUILD.md`
- `develop/index.html`
- `build/index.html`
- `build/README.md`
- `site.css`
- `site.js`

Actions:
1. Keep `/develop/` as the public onboarding lane.
2. Add `/build/` as a hidden companion route, not a top-nav route.
3. Include prerequisites, approved entry paths, ordered setup steps, FAQ coverage, and the first 20-minute report-back contract.
4. Link `/develop/` to `/build/` with one explicit deep link.
5. Keep all copy paper-mode safe and artifact-backed.

Success checks:
- `/build/` exists and is reachable by direct URL.
- `/build/` is not added to the primary nav.
- `/develop/` links to `/build/`.
- The page states that live creds, wallet keys, treasury access, and personal VPS access are not part of first-pass onboarding.

Required outputs:
- `candidate_delta_arr_bps`
- `expected_improvement_velocity_delta`
- `arr_confidence_score`
- `block_reasons`
- `finance_gate_pass`
- `one_next_cycle_action`

### Instance 4 - Claude Code / Opus

Objective: Resolve contradictions before the cohort sees them.

Inputs:
- `COMMAND_NODE.md`
- `docs/FORK_AND_RUN.md`
- `.env.example`
- `REPLIT_NEXT_BUILD.md`
- `docs/PARALLEL_AGENT_WORKFLOW.md`
- `docs/REPO_MAP.md`

Actions:
1. Audit every onboarding step for contradictions across repo docs, route copy, and env defaults.
2. Enforce one answer on these questions: fork or clone, local or shared hub, secrets needed, Docker optionality, and who owns a file.
3. Remove or flag any step that implies piggybacking on live trading infra.
4. Convert every stale or unsafe branch into an explicit `hold/repair` branch with a retry condition.
5. Push unresolved contradictions back to the doc owner before the run window closes.

Success checks:
- No route or doc tells a new employee to ask for live keys or personal infra just to get started.
- Any stale input now triggers an explicit hold/repair branch with retry timing instead of a silent dead end.
- The onboarding story is one of two paths only: local paper clone or shared paper hub.

Required outputs:
- `candidate_delta_arr_bps`
- `expected_improvement_velocity_delta`
- `arr_confidence_score`
- `block_reasons`
- `finance_gate_pass`
- `one_next_cycle_action`

### Instance 5 - GPT-4 / Medium

Objective: Validate the shared paper-hub path and the minimum-secret collaboration contract.

Inputs:
- `docs/FORK_AND_RUN.md`
- `.env.example`
- `scripts/quickstart.py`
- `scripts/elastifund_setup.py`
- `build/index.html`

Actions:
1. Extract the exact host and spoke commands for the shared paper-hub flow.
2. Reduce the handoff to the smallest allowed secret list: public hub URL and bootstrap token only.
3. Verify that the onboarding packet names the banned handoffs: wallet keys, exchange credentials, treasury credentials, and live VPS access.
4. Define the fallback path when the shared hub is unavailable: return to local paper clone immediately.
5. Add the required report-back schema to the packet.

Success checks:
- The shared-hub path is copy-paste ready.
- The secret list is explicit and minimal.
- Failure of the host/spoke flow does not halt onboarding; it reroutes to local paper mode.
- `finance_gate_pass` stays `true` unless someone is asking for paid infra or tool spend.

Required outputs:
- `candidate_delta_arr_bps`
- `expected_improvement_velocity_delta`
- `arr_confidence_score`
- `block_reasons`
- `finance_gate_pass`
- `one_next_cycle_action`

### Instance 6 - GPT-5.3-Codex / High

Objective: Consolidate the evidence, verify the patch set, and issue the next-cycle work order.

Inputs:
- outputs from Instances 1-5
- `reports/runtime_truth_latest.json`
- `reports/root_test_status.json`
- `docs/ops/elastic_employee_build_dispatch_20260311.md`

Actions:
1. Merge the friction log, FAQ fixes, route changes, and policy decisions into one coherent handoff.
2. Run the narrowest relevant tests plus `make hygiene`.
3. Confirm the hidden route, doc links, and static route checks all pass.
4. Rank any remaining blockers by impact on onboarding velocity.
5. Emit the next-cycle work order with one owner per blocker.

Success checks:
- Verification is green for the touched surfaces or the remaining blocker is explicit and reproducible.
- The site, docs, and dispatch plan tell the same onboarding story.
- Recommendations include ARR impact, confidence, info gain, risk or cap constraints, and rollout checks.

Required outputs:
- `candidate_delta_arr_bps`
- `expected_improvement_velocity_delta`
- `arr_confidence_score`
- `block_reasons`
- `finance_gate_pass`
- `one_next_cycle_action`

## 20-MINUTE RUN WINDOW

Run order for this non-trading context: `3 -> 4 -> 5 -> 1 -> 2 -> 6`.

- Minute 0-4: Instance 3 drafts or updates the hidden `/build/` route.
- Minute 0-4: Instance 4 audits for contradictions and unsafe asks.
- Minute 0-5: Instance 5 locks the shared paper-hub path and minimum-secret contract.
- Minute 5-12: Instance 1 runs the cold-clone paper-mode setup and captures friction.
- Minute 8-15: Instance 2 converts friction into FAQ fixes and missing-answer patches.
- Minute 15-20: Instance 6 reruns verification, ranks remaining blockers, and issues the next-cycle work order.

Hard gate:

- If Instance 4 finds a step that requires live creds, private wallet material, or personal VPS access for first-pass onboarding, pause Instances 1 and 5 until the unsafe step is removed.

## DONE CONDITIONS

- A new contributor can fork, clone, run `make doctor`, run `python3 scripts/quickstart.py --prepare-only`, and reach a verified local paper-mode state without private help.
- `make verify` and `make smoke-nontrading` pass, or the first real blocker is explicit and reproducible.
- The hidden `/build/` packet exists, stays out of primary nav, and links back to `/develop/`.
- The approved collaboration stories are explicit: local paper clone first, shared paper hub second.
- No onboarding instruction depends on live trading credentials, wallet keys, treasury access, or a personal live VPS.
- Every instance emits the six mandatory fields.

## FAILSAFE AND ROLLBACK RULES

- If any setup path asks for live exchange keys, wallet keys, treasury credentials, or personal VPS access, stop and roll back to the local paper-clone path immediately.
- If docs and scripts disagree, script truth wins for the cycle; convert the doc step into `hold/repair` with a retry in the next cycle.
- If Docker is missing, do not halt onboarding. Continue with prepare-only, virtualenv bootstrap, and verification.
- If the shared paper hub fails, do not debug it for the whole cohort in-line. Fallback to isolated local paper mode and retry shared hub later.
- If no defensible ARR estimate exists for a task, set `candidate_delta_arr_bps=0`, explain the info gain, and keep the velocity delta explicit.
- If any patch breaks `make hygiene`, roll back the offending doc or route change before widening scope.
