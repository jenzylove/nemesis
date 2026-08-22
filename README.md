# NEMESIS

Autonomous crypto incident response for tracing stolen funds with deterministic blockchain evidence, persistent monitoring, and evidence-grounded agent reasoning.

Current published preview: https://nemesis-incident-response.jennifereze12.chatgpt.site

The repository is the source of truth. The published preview may lag behind `main` until the frontend is republished or moved to the production hosting path.

## What NEMESIS does

A user starts with a supported chain and affected wallet address. A known theft transaction hash is optional.

### Known transaction path

If the user already knows the theft transaction, NEMESIS immediately retrieves and verifies the transaction through real Ethereum or Base JSON RPC, then continues into the existing trace pipeline.

### Wallet-only discovery path

If the transaction hash is not known, NEMESIS first performs deterministic incident discovery:

1. Bitquery retrieves indexed historical wallet transfer activity.
2. NEMESIS groups outgoing activity by transaction and ranks candidates using deterministic signals such as wallet outflow, value, transfer count, caller relationship, and proximity to the optional reported incident time.
3. GoPlus can add malicious-address risk flags to leading candidate counterparties.
4. Chainabuse can add public abuse-report evidence to the leading candidate. Results are cached and calls are deliberately limited.
5. The selected candidate is fetched again through Ethereum/Base JSON RPC.
6. NEMESIS refuses to proceed unless the RPC transaction itself contains deterministic value leaving the submitted wallet.
7. Only after RPC verification does the normal evidence, tracing, Taskmaster, and Gemini workflow continue.

Gemini does not choose or invent the theft transaction. The discovery decision is made from indexed deterministic records and then independently verified by RPC.

## Core investigation pipeline

After a transaction is known or discovered, NEMESIS:

1. Retrieves the transaction, receipt, containing block, native value, and ERC20 transfer logs through real Ethereum or Base JSON RPC.
2. Normalizes and persists deterministic evidence before model interpretation.
3. Runs the NEMESIS root agent through Google ADK and Gemini 3.5 Flash on Vertex AI.
4. Creates persisted trace branches for qualifying fund movement.
5. Recursively follows deterministic multi-hop movement.
6. Handles supported splits, residual branches, swaps, and bridge evidence without inventing unsupported paths.
7. Marks quiet branches dormant and keeps them in persistent monitoring state.
8. Uses Cloud Scheduler and Pub/Sub to recheck dormant branches and automatically resume tracing when confirmed movement appears.
9. Persists the graph, timeline, branch state, and provenance to Firestore for the frontend to display.

NEMESIS is not a chatbot wrapped around an RPC call. Gemini is deliberately kept downstream of deterministic evidence and cannot replace blockchain facts.

## Production stack

- Frontend: React / Next-compatible app built with Vinext
- API: FastAPI
- Runtime: Google Cloud Run, `us-central1`
- Persistence: Firestore
- Agent framework: Google ADK
- Model: Gemini 3.5 Flash through Vertex AI `global`
- Eventing: Google Cloud Pub/Sub
- Monitoring trigger: Google Cloud Scheduler
- Blockchain evidence: Ethereum and Base JSON RPC
- Incident discovery: Bitquery indexed EVM history
- Risk enrichment: GoPlus and Chainabuse
- Attribution: deterministic curated provider with guardrails

## Real and synthetic paths

### Real investigation

The real form accepts `wallet_address`, `chain`, an optional `theft_transaction_hash`, and an optional approximate `incident_time`.

A supplied hash uses the direct RPC path. A missing hash activates the Bitquery discovery path before RPC verification. The backend then persists evidence, invokes ADK/Gemini, creates trace state, and exposes the persisted graph and timeline to the case workspace.

### Deterministic demo

The demo is a controlled synthetic scenario for presenting a complete split, swap, bridge, dormant-monitoring, movement-resume, and actionable-destination story without pretending those demo facts came from a live theft.

Synthetic demo state is labelled as such and is separate from the real RPC workflow.

## Verified cloud baseline

On 2026-08-22 the previously integrated backend passed 33 backend tests and was deployed successfully to Cloud Run.

That cloud verification included:

- real Ethereum investigation
- real Base investigation
- deterministic ERC20 decoding
- persisted trace branches
- persisted graph nodes and edges
- persisted case timeline
- deterministic split and swap detection
- dormant monitoring registration
- Cloud Scheduler recheck
- authenticated Pub/Sub event callbacks
- confirmed movement detection
- automatic trace resume
- graph extension after resume
- persistent dormant state after continued tracing
- Google ADK Runner execution
- Gemini 3.5 Flash through Vertex AI `global`
- validated structured findings

The newer wallet-only discovery, Bitquery, GoPlus, and Chainabuse source changes are not yet represented by that cloud baseline. They must be tested with the current suite and then deployed and verified before being described as cloud verified.

No universal bridge-resolution claim is made. No exchange customer identity, KYC, UID, freeze, cooperation, or guaranteed recovery is claimed.

## Current integration status

| Integration | Status |
| --- | --- |
| Ethereum JSON RPC | Implemented and cloud verified |
| Base JSON RPC | Implemented and cloud verified |
| Cloud Run | Existing backend deployed; current source update pending redeploy |
| Firestore | Implemented and cloud verified |
| Google ADK | Implemented and cloud verified |
| Gemini 3.5 Flash / Vertex AI | Implemented and cloud verified |
| Pub/Sub | Implemented and cloud verified |
| Cloud Scheduler | Implemented and cloud verified |
| Multi-hop tracing | Implemented and cloud verified |
| Fund splits | Implemented and cloud verified |
| Swap detection | Implemented and exercised in verification |
| Dormant monitoring / autonomous resume | Implemented and cloud verified |
| Deterministic attribution guardrails | Implemented |
| Supported bridge evidence | Implemented with deterministic limits |
| Wallet-only incident discovery | Implemented in source; deployment verification pending |
| Bitquery | Implemented in source for historical wallet discovery; credential/deployment verification pending |
| GoPlus | Implemented in source as best-effort malicious-address enrichment; live verification pending |
| Chainabuse | Implemented in source with cached, call-conservative screening; credential/deployment verification pending |
| BlockSec | Planned after deployment verification |
| TRM Beacon | Approval-dependent; planned after deployment verification |
| BigQuery | Not used by the deployed runtime |

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the system flow, autonomy loop, persistence model, integration boundaries, and current limitations.

## Configuration

Copy `.env.example` to `.env` for local development. Do not commit real provider credentials.

Wallet-only discovery uses:

```text
BITQUERY_ACCESS_TOKEN=
BITQUERY_ENDPOINT=https://streaming.bitquery.io/graphql
DISCOVERY_CANDIDATE_LIMIT=100
GOPLUS_BASE_URL=https://api.gopluslabs.io/api/v1
GOPLUS_ACCESS_TOKEN=
CHAINABUSE_API_KEY=
CHAINABUSE_BASE_URL=https://api.chainabuse.com/v0
```

`GOPLUS_ACCESS_TOKEN` is optional for the current best-effort integration. Production provider secrets should live in the deployment secret store rather than the repository.

## Local backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Production mode refuses to start unless the deterministic RPC, Firestore, and Gemini/Vertex configuration is present. Wallet-only investigations additionally require a configured Bitquery token; the known-transaction path does not.

Run the frontend with:

```bash
NEXT_PUBLIC_NEMESIS_API_URL=http://localhost:8080 npm run dev
```

## Tests

```bash
backend/.venv/bin/pytest -q backend/tests
npm test
```

`backend/tests/test_incident_discovery.py` covers wallet-only workflow selection, RPC verification, Bitquery ranking, GoPlus normalization/caching, and Chainabuse authentication/caching.

## Deployment direction

The intended production request path is:

```text
Production frontend
        |
        v
Google Cloud Run API
        |
        +--> Ethereum / Base JSON RPC
        +--> Bitquery
        +--> GoPlus
        +--> Chainabuse
        +--> Firestore
        +--> Google ADK / Gemini
        +--> Pub/Sub / Cloud Scheduler
```

The production frontend should call Cloud Run directly. The ChatGPT Site preview is not part of the intended production request path.

The FastAPI backend ships with a non-root Cloud Run container, `cloudbuild.yaml`, and `infra/bootstrap-gcp.sh`. After the new production frontend URL exists, add that origin to `CORS_ALLOWED_ORIGINS`, add the Bitquery and Chainabuse credentials through the deployment secret configuration, redeploy the current commit, and verify a wallet-only browser investigation end to end.

## Safety boundary

NEMESIS traces onchain evidence and prepares structured evidence for escalation.

It does **not** claim:

- a thief's real-world identity from an address alone
- exchange account holder details
- customer UID, email, or KYC access
- fund freezing
- law-enforcement action
- exchange cooperation
- guaranteed asset recovery

Every production claim should remain tied to evidence the deployed system can actually prove.