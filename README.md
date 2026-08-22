# NEMESIS

Autonomous crypto incident response for tracing stolen funds with deterministic blockchain evidence, persistent monitoring, and evidence-grounded agent reasoning.

Public frontend: https://nemesis-incident-response.jennifereze12.chatgpt.site

## What NEMESIS does

A user submits a wallet address, supported chain, and confirmed theft transaction hash. NEMESIS then:

1. Retrieves the transaction, receipt, containing block, native value, and ERC20 transfer logs through real Ethereum or Base JSON RPC.
2. Normalizes and persists deterministic evidence before any model interpretation.
3. Runs the NEMESIS root agent through Google ADK and Gemini 3.5 Flash on Vertex AI.
4. Creates persisted trace branches for qualifying fund movement.
5. Recursively follows deterministic multi-hop movement.
6. Handles supported splits, residual branches, swaps, and bridge evidence without inventing unsupported paths.
7. Marks quiet branches dormant and keeps them in persistent monitoring state.
8. Uses Cloud Scheduler and Pub/Sub to recheck dormant branches and automatically resume tracing when confirmed movement appears.
9. Persists the graph, timeline, branch state, and provenance to Firestore for the frontend to display.

NEMESIS is not a chatbot wrapped around an RPC call. Gemini is deliberately kept downstream of the deterministic evidence layer and cannot replace blockchain facts.

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
- Attribution: deterministic curated provider with guardrails

## Real and synthetic paths

### Real investigation

The real form posts `wallet_address`, `chain`, and `theft_transaction_hash` to the FastAPI backend. The backend retrieves live RPC evidence, persists it, invokes ADK/Gemini, creates trace state, and exposes the persisted graph and timeline to the case workspace.

### Deterministic demo

The demo is a controlled synthetic scenario for presenting a complete split, swap, bridge, dormant-monitoring, movement-resume, and actionable-destination story without pretending those demo facts came from a live theft.

Synthetic demo state is labelled as such and is separate from the real RPC workflow.

## Verified cloud release

On 2026-08-22 the integrated backend passed 33 backend tests and was deployed successfully to Cloud Run.

Cloud verification included:

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

No universal bridge-resolution claim is made. No exchange customer identity, KYC, UID, freeze, cooperation, or guaranteed recovery is claimed.

## Current integration status

| Integration | Status |
| --- | --- |
| Ethereum JSON RPC | Implemented and cloud verified |
| Base JSON RPC | Implemented and cloud verified |
| Cloud Run | Implemented and deployed |
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
| Bitquery / Coinpath | Planned, not currently active |
| GoPlus | Planned, not currently active |
| BlockSec | Planned, not currently active |
| Chainabuse | Planned, not currently active |
| TRM Beacon | Approval-dependent, not currently active |
| BigQuery | Not used by the deployed runtime |

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the system flow, autonomy loop, persistence model, integration boundaries, and current limitations.

## Local backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

From the repository root, copy `.env.example` to `.env` and configure the required values.

Production mode refuses to start unless the deterministic RPC, Firestore, and Gemini/Vertex configuration is present. Local development may use the explicit in-memory fallback where supported.

Run the frontend with:

```bash
NEXT_PUBLIC_NEMESIS_API_URL=http://localhost:8080 npm run dev
```

## Tests

```bash
backend/.venv/bin/pytest -q backend/tests
npm test
```

## Google Cloud deployment

The FastAPI backend ships with a non-root Cloud Run container, `cloudbuild.yaml`, and `infra/bootstrap-gcp.sh`.

1. Select a Google Cloud project with billing enabled.
2. Configure `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`, and the required runtime settings.
3. Create the Firestore Native database.
4. Store Ethereum and Base RPC URLs in Secret Manager.
5. Submit the backend build with `gcloud builds submit --config cloudbuild.yaml .`.
6. Configure the frontend with the deployed Cloud Run API URL.
7. Publish the frontend and verify the complete browser-to-API flow.

The runtime service account needs the minimum roles required for Firestore, Vertex AI, and Secret Manager. Scheduler and Pub/Sub endpoints remain protected even while the public investigation API is reachable from the approved frontend origin.

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