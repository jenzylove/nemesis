# NEMESIS

Working MVP for autonomous crypto incident response.

## Real vertical slice

The real form sends wallet, chain, and theft transaction hash to FastAPI. The backend creates a case, loads the transaction and receipt through Ethereum or Base JSON RPC, loads the containing block timestamp, decodes ERC20 Transfer logs, persists deterministic evidence, then invokes the NEMESIS root agent through Google ADK and Gemini. The response keeps RPC facts separate from the agent finding.

## Synthetic demo

Select **Run deterministic demo instead** to exercise the existing controlled fund split, swap, bridge, dormant branch, and actionable destination sequence. Demo facts are explicitly labelled synthetic and do not enter the real RPC workflow.

## Local backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

From the repository root, copy `.env.example` to `.env` and export its values. The backend uses process memory only when `FIRESTORE_PROJECT_ID` is absent. Production mode refuses to start unless both RPC URLs, Firestore, and either Vertex AI or a Gemini API key are configured. ADK uses the Gemini API when `GOOGLE_API_KEY` exists or Vertex AI when `GOOGLE_GENAI_USE_VERTEXAI=TRUE`.

Run the frontend with `NEXT_PUBLIC_NEMESIS_API_URL=http://localhost:8080 npm run dev`.

## Tests

```bash
backend/.venv/bin/pytest -q backend/tests
npm test
```

## Google Cloud production

The frontend is deployed through Sites. The FastAPI runtime includes a non-root Cloud Run container, `cloudbuild.yaml`, and `infra/bootstrap-gcp.sh`.

Taskmaster uses Firestore collections `monitoring_branches`, `processed_events`, and `case_timeline`. Cloud Scheduler publishes periodic rechecks through the protected monitoring endpoint. Pub/Sub delivers authenticated events to the protected event endpoint. Event document creation is the idempotency boundary, and a detected transaction produces a persistent `MOVEMENT_DETECTED` event followed by `TRACE_RESUMED` after deterministic RPC normalization.

1. Select a Google Cloud project with billing enabled.
2. Set `GOOGLE_CLOUD_PROJECT` and optionally `GOOGLE_CLOUD_LOCATION`, then run `infra/bootstrap-gcp.sh`.
3. Create the Firestore Native database once. Its location is permanent, so choose it deliberately.
4. Add RPC URLs without printing them:

```bash
printf '%s' "$ETHEREUM_RPC_URL" | gcloud secrets versions add nemesis-staging-ethereum-rpc --data-file=-
printf '%s' "$BASE_RPC_URL" | gcloud secrets versions add nemesis-staging-base-rpc --data-file=-
```

5. Submit the build with `gcloud builds submit --config cloudbuild.yaml .`.
6. Set `NEXT_PUBLIC_NEMESIS_API_URL` to the resulting Cloud Run URL and publish the frontend again.

The runtime service account needs `roles/datastore.user`, `roles/aiplatform.user`, and `roles/secretmanager.secretAccessor`. The Cloud Build service account also needs permission to deploy Cloud Run and act as `nemesis-runtime`.

## Safety boundary

NEMESIS traces onchain evidence. It does not claim an exchange account holder, UID, email, KYC identity, exchange cooperation, a freeze, law enforcement action, or guaranteed recovery.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
