from datetime import datetime, timezone
import uuid

from .incident_selection import rank_verified_candidates, wallet_outflow
from .models import CaseCreate, CaseResponse, DeterministicEvidence, InvestigationCase


SUPPORTED_CHAINS = ("ethereum", "base")


class CaseWorkflow:
    def __init__(self, repository, provider, classifier, taskmaster=None, discovery=None):
        self.repository = repository
        self.provider = provider
        self.classifier = classifier
        self.taskmaster = taskmaster
        self.discovery = discovery

    async def _select_verified_incident(self, chain, wallet, discovery):
        """Rank deterministic RPC evidence and refuse to guess on a close result."""
        return await rank_verified_candidates(
            self.provider, chain, wallet, discovery
        )
    async def _discover_auto_chain(self, wallet, incident_time):
        if self.discovery is None:
            from .discovery import DiscoveryUnavailableError

            raise DiscoveryUnavailableError(
                "Wallet-only discovery is not configured. Add a theft transaction hash or configure Alchemy."
            )

        resolved = []
        failures = []
        for chain in SUPPORTED_CHAINS:
            try:
                discovery = await self.discovery.discover(chain, wallet, incident_time)
                transaction = await self._select_verified_incident(chain, wallet, discovery)
                resolved.append((discovery.selected_score or 0, chain, discovery, transaction))
            except Exception as exc:
                failures.append(f"{chain}: {exc}")

        if not resolved:
            detail = "; ".join(failures) if failures else "no supported chain returned a verified incident"
            raise ValueError(
                f"no verified incident found on supported chains ({', '.join(SUPPORTED_CHAINS)}): {detail}"
            )

        resolved.sort(key=lambda item: (item[3] is not None, item[0]), reverse=True)
        _, chain, discovery, transaction = resolved[0]
        return chain, discovery, transaction

    async def _resolve_supplied_hash_chain(self, tx_hash):
        failures = []
        for chain in SUPPORTED_CHAINS:
            try:
                transaction = await self.provider.get_normalized_transaction(chain, tx_hash)
                if transaction.hash.lower() == tx_hash and transaction.status == "success":
                    return chain, transaction
            except Exception as exc:
                failures.append(f"{chain}: {exc}")
        detail = "; ".join(failures) if failures else "transaction was not resolved"
        raise ValueError(
            f"transaction hash was not found on supported chains ({', '.join(SUPPORTED_CHAINS)}): {detail}"
        )

    async def create_and_investigate(self, request: CaseCreate, owner_user_id: str, owner_email: str | None = None) -> CaseResponse:
        now = datetime.now(timezone.utc)
        wallet = request.wallet_address.lower()
        supplied_hash = request.theft_transaction_hash.lower() if request.theft_transaction_hash else None
        case = InvestigationCase(
            id=f"NMS-{now:%y%m%d}-{uuid.uuid4().hex[:8].upper()}",
            state="INVESTIGATING",
            created_at=now,
            updated_at=now,
            wallet_address=wallet,
            chain=request.chain,
            owner_user_id=owner_user_id,
            owner_email=owner_email,
            theft_transaction_hash=supplied_hash,
        )
        try:
            if supplied_hash is None:
                if request.chain == "auto":
                    resolved_chain, discovery, transaction = await self._discover_auto_chain(
                        wallet, request.incident_time
                    )
                    case.chain = resolved_chain
                    case.discovery = discovery
                else:
                    if self.discovery is None:
                        from .discovery import DiscoveryUnavailableError

                        raise DiscoveryUnavailableError(
                            "Wallet-only discovery is not configured. Add a theft transaction hash or configure Alchemy."
                        )
                    case.discovery = await self.discovery.discover(
                        request.chain, wallet, request.incident_time
                    )
                    transaction = await self._select_verified_incident(
                        request.chain, wallet, case.discovery
                    )
                if transaction is None:
                    case.state = "AMBIGUOUS_INCIDENT"
                    case.updated_at = datetime.now(timezone.utc)
                    await self.repository.save(case)
                    return CaseResponse(
                        case=case,
                        factual_source="json_rpc",
                        agent_runtime="unavailable",
                    )
                tx_hash = transaction.hash.lower()
                case.theft_transaction_hash = tx_hash
                case.updated_at = datetime.now(timezone.utc)
                await self.repository.save(case)
            else:
                tx_hash = supplied_hash
                if request.chain == "auto":
                    resolved_chain, transaction = await self._resolve_supplied_hash_chain(tx_hash)
                    case.chain = resolved_chain
                else:
                    transaction = await self.provider.get_normalized_transaction(
                        request.chain, tx_hash
                    )
                    if transaction.hash.lower() != tx_hash:
                        raise ValueError(
                            "resolved transaction hash does not match deterministic RPC evidence"
                        )

            if transaction.status != "success" or not wallet_outflow(transaction, wallet):
                raise ValueError(
                    "the supplied transaction contains no deterministic value leaving the submitted wallet"
                )

            evidence = DeterministicEvidence(
                submitted_wallet=wallet,
                transaction=transaction,
            )
            case.evidence = evidence
            case.updated_at = datetime.now(timezone.utc)
            await self.repository.save(case)

            branches = []
            if self.taskmaster:
                branches = await self.taskmaster.trace_initial(case.id, evidence)

            try:
                case.finding = await self.classifier.classify(case.id, evidence)
                case.finding.compromise_mechanism_confidence = case.finding.confidence
                runtime = "google_adk_gemini"
            except (RuntimeError, ValueError) as exc:
                case.error = str(exc)
                runtime = "unavailable"

            if self.taskmaster:
                statuses = {branch.status for branch in (branches or []) if branch}
                if "ACTIONABLE" in statuses:
                    case.state = "ACTIONABLE"
                elif "DORMANT" in statuses:
                    case.state = "MONITORING"
                elif branches:
                    case.state = "INVESTIGATING"
                else:
                    case.state = "LIMITED"
            else:
                case.state = "EVIDENCE_READY"
            case.updated_at = datetime.now(timezone.utc)
            await self.repository.save(case)
            return CaseResponse(case=case, factual_source="json_rpc", agent_runtime=runtime)
        except Exception as exc:
            case.state = "FAILED"
            case.error = str(exc)
            case.updated_at = datetime.now(timezone.utc)
            if case.evidence is not None:
                await self.repository.save(case)
            raise
