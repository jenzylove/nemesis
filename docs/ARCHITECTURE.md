# NEMESIS architecture

NEMESIS is an autonomous crypto incident response system built around a strict separation between deterministic blockchain evidence and model interpretation.

The deterministic trace core owns transaction facts, transfer paths, amounts, timestamps, graph structure, branch state, and supported attribution evidence. Google ADK and Gemini may classify and summarize verified evidence, but they cannot invent blockchain facts or write unsupported identifiers into the graph.

## Deployed architecture

```text
Public NEMESIS frontend
        |
        v
FastAPI on Cloud Run
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

Backend deployment region: `us-central1`.

## Real investigation lifecycle

1. A user submits a wallet address, chain, and confirmed theft transaction hash.
2. FastAPI retrieves the transaction, receipt, and containing block through Ethereum or Base JSON RPC.
3. The provider derives receipt status, confirmed block timestamp, native value, and ERC20 transfer logs.
4. Deterministic evidence is normalized and persisted before model interpretation.
5. The Google ADK Runner opens the case and invokes the NEMESIS root agent with Gemini 3.5 Flash.
6. Structured model output is validated against deterministic evidence and cannot add unsupported blockchain identifiers.
7. Taskmaster creates trace branches for qualifying outgoing value and persists the graph and timeline.
8. Moving branches are recursively followed across successive deterministic movements until they become `DORMANT`, `OBSCURED`, `ACTIONABLE`, or reach configured maximum depth.
9. Supported fund splits create independent persisted branches. Residual tracked token value may remain as its own branch.
10. Deterministically evidenced swaps continue the resulting asset without inventing a protocol label.
11. Supported bridge evidence may create a cross-chain continuation only when destination evidence can be resolved deterministically. Unresolved destinations are not guessed.
12. Dormant branches remain registered for monitoring.
13. Cloud Scheduler triggers rechecks. Pub/Sub carries authenticated events. Confirmed movement creates a persisted `MOVEMENT_DETECTED` event and automatically resumes tracing from the affected branch.
14. The frontend reads the persisted graph, branches, and timeline from the real API.

## Persistence and idempotency

Firestore is the production state store.

Primary collections used by the current runtime include:

- `cases`
- `trace_branches`
- `case_graph_nodes`
- `case_graph_edges`
- `case_timeline`
- `processed_events`

Event document creation is the idempotency boundary for asynchronous Taskmaster events, preventing duplicate Pub/Sub deliveries from extending the same branch twice.

## Agent boundary

Gemini is not the source of truth for chain activity.

Before an agent finding is accepted, the runtime validates evidence references and rejects unsupported identifiers. Attribution is handled through a separate deterministic attribution layer. An address is never treated as a real-world identity merely because a model suggests one.

The application never claims access to exchange customer UID, email, KYC records, fund-freezing powers, law-enforcement systems, guaranteed recovery, or exchange cooperation.

## Current integration status

| Integration | Status | Role |
| --- | --- | --- |
| Ethereum JSON RPC | Implemented and cloud verified | Transaction evidence and tracing |
| Base JSON RPC | Implemented and cloud verified | Transaction evidence and tracing |
| FastAPI | Implemented and deployed | Public application API |
| Cloud Run | Implemented and deployed | Backend runtime |
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
| Bitquery / Coinpath | Planned integration, not currently active | External tracing/enrichment source |
| GoPlus | Planned integration, not currently active | Security/contract diagnosis enrichment |
| BlockSec | Planned integration, not currently active | Security/replay enrichment |
| Chainabuse read/reporting | Planned integration, not currently active | Abuse screening and escalation |
| TRM Beacon | Approval-dependent, not currently active | Escalation path only if approved |
| BigQuery | Not part of the deployed runtime | No production dependency today |

## Verified cloud state

On 2026-08-22 the final integrated backend passed 33 backend tests and was deployed to Cloud Run. Real Ethereum and Base cases persisted evidence to Firestore. The Ethereum verification produced multiple trace branches, graph nodes and edges, deterministic split/swap evidence, dormant monitoring, Scheduler rechecks, Pub/Sub callbacks, movement detection, automatic trace resume, and persistent graph/timeline updates. Google ADK executed Gemini 3.5 Flash through Vertex AI `global` and returned validated structured findings.

The deterministic demo remains intentionally separate from the real RPC workflow and is labelled synthetic in the UI.

## Remaining production limitations

NEMESIS should not claim universal cross-chain destination resolution. A bridge continuation is only valid when the configured provider can deterministically resolve the destination.

The current curated attribution source is intentionally limited. Production-grade exchange/service attribution would require an additional vetted dataset or provider.

Bitquery, GoPlus, BlockSec, Chainabuse, and TRM Beacon were part of the broader planned ecosystem but are not wired into the deployed runtime yet. Their absence must not be hidden or represented as completed integration.