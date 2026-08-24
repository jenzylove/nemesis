# NEMESIS architecture

NEMESIS is an autonomous crypto incident response system built around a strict separation between deterministic blockchain evidence and model interpretation.

The deterministic trace core owns transaction facts, transfer paths, amounts, timestamps, graph structure, branch state, incident-candidate selection, and supported attribution evidence. Google ADK and Gemini may classify and summarize verified evidence, but they cannot invent blockchain facts, choose an unsupported theft transaction, or write unsupported identifiers into the graph.

## Runtime architecture

```text
Production frontend
        |
        v
FastAPI on Cloud Run
        |
        +--> Wallet-only incident discovery
        |      Alchemy historical wallet transfer index
        |         |
        |         +--> GoPlus risk enrichment (best effort)
        |         +--> Chainabuse public report screening (cached / call-conservative)
        |      selected candidate must pass RPC verification
        |
        +--> Ethereum / Base JSON RPC
        |      transaction, receipt, block, ERC20 logs,
        |      outgoing movement checks
        |
        +--> Firestore
        |      cases
        |      trace_branches
        |      case_graph_nodes
        |      case_graph_edges
        |      case_timeline
        |      monitoring state / processed events
        |
        +--> Google ADK Runner
        |      Gemini 3.5 Flash on Vertex AI (global)
        |
        +--> Pub/Sub
        |      asynchronous trace and recheck events
        |
        +--> Cloud Scheduler
               periodic dormant-branch monitoring
```

The existing backend deployment region is `us-central1`.

Alchemy historical discovery, Bitquery realtime signals, GoPlus, Chainabuse, wallet-only intake, and RPC verification are implemented in the current source. Deployment status must be verified against the Git SHA returned by the health endpoint.

## Investigation entry paths

### Known theft transaction

When the user supplies a confirmed theft transaction hash, NEMESIS preserves the existing fast path:

1. FastAPI validates the wallet, chain, and transaction hash.
2. Ethereum/Base JSON RPC retrieves the transaction, receipt, and containing block.
3. Deterministic evidence is normalized and persisted.
4. Taskmaster tracing and Google ADK/Gemini continue normally.

This path does not depend on Alchemy, Bitquery, GoPlus, or Chainabuse.

### Wallet-only incident discovery

When the user does not know the theft transaction:

1. The user supplies the affected wallet and chain. Approximate incident time is optional.
2. Alchemy retrieves historical transfers involving that wallet. Candidate transactions remain untrusted until verified by JSON RPC.
3. NEMESIS keeps only transactions containing deterministic outgoing transfer rows from the submitted wallet.
4. Candidate transactions are grouped and scored using deterministic signals:
   - wallet is the transfer sender
   - transaction caller relationship to the wallet
   - indexed USD outflow size
   - multiple outgoing transfers within one transaction
   - proximity to the user-supplied approximate incident time, when present
5. GoPlus screens the counterparties of the leading candidates. Malicious-address flags may increase candidate score. GoPlus failure does not create or remove blockchain facts.
6. Chainabuse screens only the leading counterparty and caches the result to conserve limited API calls. Existing public abuse reports may increase candidate score.
7. The highest deterministic candidate becomes the proposed theft transaction.
8. NEMESIS retrieves that exact transaction again through the configured Ethereum/Base JSON RPC provider.
9. The workflow refuses to continue unless RPC evidence independently confirms that value left the submitted wallet in that transaction.
10. Only after this verification is the transaction admitted to the normal trace pipeline.

Gemini is not used to invent, select, or replace a theft transaction hash.

## Real trace lifecycle

Once a transaction has been supplied or discovered and RPC verified:

1. The provider derives receipt status, confirmed block timestamp, native value, and ERC20 transfer logs.
2. Deterministic evidence is normalized and persisted before model interpretation.
3. The Google ADK Runner opens the case and invokes the NEMESIS root agent with Gemini 3.5 Flash.
4. Structured model output is validated against deterministic evidence and cannot add unsupported blockchain identifiers.
5. Taskmaster creates trace branches for qualifying outgoing value and persists the graph and timeline.
6. Moving branches are recursively followed across successive deterministic movements until they become `DORMANT`, `OBSCURED`, `ACTIONABLE`, or reach configured maximum depth.
7. Supported fund splits create independent persisted branches. Residual tracked token value may remain as its own branch.
8. Deterministically evidenced swaps continue the resulting asset without inventing a protocol label.
9. Supported bridge evidence may create a cross-chain continuation only when destination evidence can be resolved deterministically. Unresolved destinations are not guessed.
10. Dormant branches remain registered for monitoring.
11. Cloud Scheduler triggers rechecks. Pub/Sub carries authenticated events. Confirmed movement creates a persisted `MOVEMENT_DETECTED` event and automatically resumes tracing from the affected branch.
12. The frontend reads the persisted graph, branches, and timeline from the real API.

## Discovery data boundary

Alchemy is used for historical incident discovery and catch-up. Bitquery is used only for realtime movement signals when configured. Neither is the final source of truth.

The persisted case can record:

- selected transaction hash
- deterministic candidate score
- candidate count
- optional reported incident time
- top candidate reasons
- GoPlus risk flags when available
- Chainabuse report count when available

The final admitted transaction evidence still comes from Ethereum/Base JSON RPC. If Alchemy returns a candidate that RPC cannot verify, or RPC evidence does not show value leaving the submitted wallet, the workflow fails instead of fabricating an incident.

## Enrichment failure model

GoPlus and Chainabuse are enrichment signals rather than prerequisites for the deterministic tracing core.

- GoPlus requests are best effort and cached per chain/address during a running instance.
- Chainabuse requests are best effort, cached by address, and restricted to the leading candidate to avoid wasting a tightly limited API allowance.
- If an enrichment provider is unavailable, NEMESIS may continue using Alchemy candidate evidence and independent RPC verification.
- No provider flag is treated as a real-world identity claim.

Wallet-only discovery requires a configured Alchemy key. If Alchemy is unavailable, the API tells the user to provide a known theft transaction hash instead.

## Persistence and idempotency

Firestore is the production state store.

Primary collections used by the current runtime include:

- `cases`
- `trace_branches`
- `case_graph_nodes`
- `case_graph_edges`
- `case_timeline`
- `processed_events`

The discovery object is stored inside the case document before the selected transaction is processed further.

An event claim prevents concurrent duplicate handling. The marker becomes permanently complete only after successful processing; failures release the claim so Pub/Sub can retry without losing the movement event.

## Agent boundary

Gemini is not the source of truth for chain activity.

Before an agent finding is accepted, the runtime validates evidence references and rejects unsupported identifiers. Attribution is handled through a separate deterministic attribution layer. An address is never treated as a real-world identity merely because a model or enrichment provider suggests one.

The application never claims access to exchange customer UID, email, KYC records, fund-freezing powers, law-enforcement systems, guaranteed recovery, or exchange cooperation.

## Current integration status

| Integration | Status | Role |
| --- | --- | --- |
| Ethereum JSON RPC | Implemented and cloud verified | Final transaction evidence and tracing |
| Base JSON RPC | Implemented and cloud verified | Final transaction evidence and tracing |
| FastAPI | Implemented | Owner-protected application API |
| Cloud Run | Deployment verified by health Git SHA | Backend runtime |
| Firestore | Implemented and cloud verified | Cases, branches, graph, timeline, monitoring state |
| Google ADK | Implemented and cloud verified | Agent runtime |
| Gemini 3.5 Flash / Vertex AI | Implemented and cloud verified | Evidence-grounded classification and findings |
| Pub/Sub | Implemented and cloud verified | Asynchronous recheck and trace events |
| Cloud Scheduler | Implemented and cloud verified | Dormant branch rechecks |
| Multi-hop tracing | Implemented and cloud verified | Recursive deterministic continuation |
| Split handling | Implemented and cloud verified | Independent trace branches |
| Swap detection | Implemented and tested; exercised in cloud verification | Asset transition from deterministic receipt evidence |
| Dormant monitoring and autonomous resume | Implemented and cloud verified | Taskmaster autonomy |
| Curated deterministic attribution layer | Implemented | Guarded service/entity attribution |
| Supported bridge evidence | Implemented with deterministic guardrails | Bridge detection and continuation when resolvable |
| Wallet-only incident discovery | Implemented | Start from wallet when theft hash is unknown |
| Alchemy | Implemented | Historical wallet discovery and catch-up candidates; every movement is RPC-verified |
| Bitquery | Implemented when configured | Realtime outgoing-movement signals; every movement is RPC-verified |
| GoPlus | Implemented in current source; live verification pending | Best-effort malicious-address risk enrichment |
| Chainabuse read screening | Implemented in current source; credential/deployment verification pending | Cached public abuse-report enrichment for the leading candidate |
| BigQuery | Not part of the runtime | No production dependency today |

## Verified cloud baseline

On 2026-08-22 the pre-discovery integrated backend passed 33 backend tests and was deployed to Cloud Run. Real Ethereum and Base cases persisted evidence to Firestore. The Ethereum verification produced multiple trace branches, graph nodes and edges, deterministic split/swap evidence, dormant monitoring, Scheduler rechecks, Pub/Sub callbacks, movement detection, automatic trace resume, and persistent graph/timeline updates. Google ADK executed Gemini 3.5 Flash through Vertex AI `global` and returned validated structured findings.

The deterministic demo remains intentionally separate from the real RPC workflow and is labelled synthetic in the UI.

The current wallet-only discovery and enrichment source changes still require the updated test suite to be executed, provider credentials to be configured in the deployment environment, Cloud Run to be redeployed, and a real wallet-only browser investigation to be verified before those features are called cloud verified.

## Remaining production limitations

NEMESIS should not claim universal cross-chain destination resolution. A bridge continuation is only valid when the configured provider can deterministically resolve the destination.

The current curated attribution source is intentionally limited. Production-grade exchange/service attribution would require an additional vetted dataset or provider.

Alchemy candidate ranking identifies the strongest deterministic incident candidate available in the retrieved indexed history; it is not a guarantee that every historical compromise can always be inferred from wallet activity alone. Approximate incident time materially improves candidate ranking when the user knows it.

GoPlus and Chainabuse are risk-enrichment sources, not identity or guilt oracles.

No additional tracing, attribution, or recovery provider is implied by this architecture.