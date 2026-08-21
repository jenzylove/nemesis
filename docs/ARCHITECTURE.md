# NEMESIS architecture

The deterministic trace core owns every transaction, path, amount, timestamp, and entity label. Gemini and Google ADK can select tools, classify compromise evidence, summarize verified findings, and generate reports, but cannot write blockchain facts into the graph.

## Implemented vertical slice

1. FastAPI creates and persists a unique case.
2. The JSON RPC provider requests the transaction, receipt, and containing block.
3. The provider derives receipt status, confirmed block timestamp, and ERC20 Transfer logs.
4. Firestore persists the normalized deterministic evidence.
5. The Google ADK Runner opens a case session and runs the root NEMESIS agent.
6. The agent must call its deterministic evidence tool and returns a Pydantic validated finding through Gemini.
7. FastAPI returns RPC facts and the separate agent finding to the existing frontend.

Production mode fails closed when RPC, Firestore, or Gemini/Vertex configuration is absent. Local development may use the explicit in-memory fallback. Model output uses a forbidden-extra-fields schema, allowlisted evidence references, and a validator that rejects blockchain identifiers absent from deterministic evidence.

## Firestore collections

`cases/{caseId}` stores case metadata, normalized evidence, and the structured agent finding for this milestone.

## Integration truth

| Integration | Status |
| --- | --- |
| Direct EVM RPC | Implemented adapter |
| Gemini and Google ADK | Implemented runtime, activates with credentials |
| Firestore | Implemented repository, activates with project credentials |
| Pub/Sub and Scheduler | Not implemented in this milestone |
| Bitquery, GoPlus, Chainabuse read | Deferred adapters |
| Chainabuse write, TRM Beacon, BlockSec replay | Deferred, never simulated as real |
| Exchange freezing, cooperation, law enforcement | Outside MVP, evidence export only |

The production vertical slice intentionally stops after one supplied transaction. Deep path discovery, branch monitoring, bridges, exchange attribution, and escalation remain synthetic demo behavior.

The shared normalized transaction and provider contracts are reusable by a future Telegraph ONCHAIN_TX_LOOKUP miner wrapper.
