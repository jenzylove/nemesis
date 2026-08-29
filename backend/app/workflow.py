from datetime import datetime, timezone
import uuid

from .discovery import (
    DiscoveryProviderError,
    DiscoveryUnavailableError,
    IncidentNotFoundError,
    WalletInactiveError,
)
from .incident_selection import rank_verified_candidates, wallet_outflow
from .models import CaseCreate, CaseResponse, DeterministicEvidence, InvestigationCase
from .movement import MovementDetectionError
from .progress import ProgressReporter
from .providers import RpcProviderError


SUPPORTED_CHAINS = ("ethereum", "base")

# Failures that mean "NEMESIS could not retrieve evidence", never "the evidence
# says nothing happened". Collapsing the two would let an outage masquerade as a
# forensic finding, which is the one thing this product must not do.
EVIDENCE_RETRIEVAL_ERRORS = (
    DiscoveryProviderError,
    DiscoveryUnavailableError,
    RpcProviderError,
    MovementDetectionError,
    TimeoutError,
)

EVIDENCE_RETRIEVAL_MESSAGE = (
    "NEMESIS could not reach the onchain data sources needed to verify this wallet, "
    "so no conclusion has been drawn about it. Nothing here means the wallet is safe "
    "or that no incident occurred. Please try again shortly."
)


# The only failures that describe the evidence itself. A wallet with nothing to
# find, or an incident that could not be picked out of what was found, are
# answers. Everything else is NEMESIS failing to look.
INVESTIGATIVE_OUTCOMES = (IncidentNotFoundError, ValueError)


def is_evidence_retrieval_failure(error: BaseException) -> bool:
    """Whether this failure means NEMESIS could not retrieve evidence.

    Deliberately inverted: anything not recognised as an investigative answer
    counts as a retrieval failure. A bug or an unfamiliar provider error must
    never reach a victim as "no incident found", because that reads as "your
    wallet is fine". This product would rather admit it could not look than
    imply it looked and saw nothing.
    """
    if isinstance(error, EVIDENCE_RETRIEVAL_ERRORS):
        return True
    return not isinstance(error, INVESTIGATIVE_OUTCOMES)


class CaseWorkflow:
    def __init__(self, repository, provider, classifier, taskmaster=None, discovery=None, progress=None):
        self.repository = repository
        self.provider = provider
        self.classifier = classifier
        self.taskmaster = taskmaster
        self.discovery = discovery
        self.progress = progress or ProgressReporter()

    async def _report(self, request, owner_user_id, phase):
        """Announce a phase the workflow has actually reached."""
        try:
            await self.progress.publish(getattr(request, "progress_token", None), phase, owner_user_id)
        except Exception:
            return None

    async def _select_verified_incident(self, chain, wallet, discovery):
        """Rank deterministic RPC evidence and refuse to guess on a close result."""
        return await rank_verified_candidates(
            self.provider, chain, wallet, discovery
        )
    async def _discover_auto_chain(self, wallet, incident_time, reporter=None):
        if self.discovery is None:
            from .discovery import DiscoveryUnavailableError

            raise DiscoveryUnavailableError(
                "Wallet-only discovery is not configured. Add a theft transaction hash or configure Alchemy."
            )

        resolved = []
        failures = []
        retrieval_failures = []
        inactive_chains = []
        for chain in SUPPORTED_CHAINS:
            try:
                discovery = await self.discovery.discover(chain, wallet, incident_time)
                if reporter:
                    await reporter("RANKING_CANDIDATES")
                transaction = await self._select_verified_incident(chain, wallet, discovery)
                resolved.append((discovery.selected_score or 0, chain, discovery, transaction))
            except Exception as exc:
                failures.append(f"{chain}: {exc}")
                if is_evidence_retrieval_failure(exc):
                    retrieval_failures.append(f"{chain}: {exc}")
                if isinstance(exc, WalletInactiveError):
                    inactive_chains.append(chain)

        if not resolved:
            # If every chain failed and any of those failures was an outage, this
            # is an infrastructure problem and must not be reported as an
            # investigative result.
            if retrieval_failures:
                raise DiscoveryProviderError(EVIDENCE_RETRIEVAL_MESSAGE)
            if len(inactive_chains) == len(SUPPORTED_CHAINS):
                # The product could not have found anything here, which is not
                # the same as having looked and found nothing.
                raise ValueError(
                    "This wallet has never sent a transaction on "
                    f"{' or '.join(c.title() for c in SUPPORTED_CHAINS)}, the networks NEMESIS "
                    "supports today. If the funds were taken on another network, NEMESIS "
                    "cannot investigate it yet."
                )
            raise ValueError(
                "No verified incident was found for this wallet on the supported networks "
                f"({', '.join(SUPPORTED_CHAINS)}). If you know the theft transaction hash, "
                "adding it will let NEMESIS investigate it directly."
            )

        resolved.sort(key=lambda item: (item[3] is not None, item[0]), reverse=True)
        _, chain, discovery, transaction = resolved[0]
        return chain, discovery, transaction

    async def _resolve_supplied_hash_chain(self, tx_hash):
        retrieval_failures = []
        for chain in SUPPORTED_CHAINS:
            try:
                transaction = await self.provider.get_normalized_transaction(chain, tx_hash)
                if transaction.hash.lower() == tx_hash and transaction.status == "success":
                    return chain, transaction
            except LookupError:
                continue
            except Exception as exc:
                if is_evidence_retrieval_failure(exc):
                    retrieval_failures.append(f"{chain}: {exc}")
        if retrieval_failures:
            raise DiscoveryProviderError(EVIDENCE_RETRIEVAL_MESSAGE)
        raise ValueError(
            "That transaction hash was not found on the supported networks "
            f"({', '.join(SUPPORTED_CHAINS)}). Please check the hash and try again."
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
                    await self._report(request, owner_user_id, "SEARCHING_WALLET_HISTORY")
                    resolved_chain, discovery, transaction = await self._discover_auto_chain(
                        wallet, request.incident_time,
                        lambda phase: self._report(request, owner_user_id, phase),
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

            await self._report(request, owner_user_id, "VERIFYING_INCIDENT")
            if transaction.status != "success" or not wallet_outflow(transaction, wallet):
                raise ValueError(
                    "the supplied transaction contains no deterministic value leaving the submitted wallet"
                )

            await self._report(request, owner_user_id, "RECONSTRUCTING_ASSETS")
            evidence = DeterministicEvidence(
                submitted_wallet=wallet,
                transaction=transaction,
            )
            case.evidence = evidence
            case.updated_at = datetime.now(timezone.utc)
            await self.repository.save(case)

            branches = []
            if self.taskmaster:
                await self._report(request, owner_user_id, "TRACING_FUNDS")
                branches = await self.taskmaster.trace_initial(case.id, evidence)

            try:
                await self._report(request, owner_user_id, "ASSESSING_COMPROMISE")
                case.finding = await self.classifier.classify(case.id, evidence)
                case.finding.compromise_mechanism_confidence = case.finding.confidence
                runtime = "google_adk_gemini"
            except (RuntimeError, ValueError):
                # Deterministic evidence and tracing already stand on their own.
                # A classifier failure degrades the case, it does not invalidate
                # it, and the victim should not be shown runtime internals.
                case.error = (
                    "NEMESIS could not produce a verified assessment of the compromise "
                    "mechanism for this incident. The deterministic onchain evidence and "
                    "fund tracing below are unaffected."
                )
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
            await self._report(request, owner_user_id, "PREPARING_CASE")
            await self.repository.save(case)
            return CaseResponse(case=case, factual_source="json_rpc", agent_runtime=runtime)
        except Exception as exc:
            retrieval_failure = is_evidence_retrieval_failure(exc)
            case.state = "EVIDENCE_RETRIEVAL_FAILED" if retrieval_failure else "FAILED"
            case.error = EVIDENCE_RETRIEVAL_MESSAGE if retrieval_failure else str(exc)
            case.updated_at = datetime.now(timezone.utc)
            if case.evidence is not None:
                await self.repository.save(case)
            raise
