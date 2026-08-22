from datetime import datetime, timezone
import uuid

from .models import CaseCreate, CaseResponse, DeterministicEvidence, InvestigationCase


class CaseWorkflow:
    def __init__(self, repository, provider, classifier, taskmaster=None, discovery=None):
        self.repository = repository
        self.provider = provider
        self.classifier = classifier
        self.taskmaster = taskmaster
        self.discovery = discovery

    async def create_and_investigate(self, request: CaseCreate) -> CaseResponse:
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
            theft_transaction_hash=supplied_hash,
        )
        await self.repository.save(case)

        try:
            tx_hash = supplied_hash
            if tx_hash is None:
                if self.discovery is None:
                    from .discovery import DiscoveryUnavailableError

                    raise DiscoveryUnavailableError(
                        "Wallet-only discovery is not configured. Add a theft transaction hash or configure Bitquery."
                    )
                case.discovery = await self.discovery.discover(
                    request.chain, wallet, request.incident_time
                )
                tx_hash = case.discovery.selected_transaction_hash.lower()
                case.theft_transaction_hash = tx_hash
                case.updated_at = datetime.now(timezone.utc)
                await self.repository.save(case)

            transaction = await self.provider.get_normalized_transaction(request.chain, tx_hash)
            if transaction.hash.lower() != tx_hash:
                raise ValueError("resolved transaction hash does not match deterministic RPC evidence")

            # A discovered incident must actually contain value leaving the submitted wallet.
            if supplied_hash is None:
                wallet_outflow = (
                    transaction.from_address == wallet and int(transaction.native_value_wei) > 0
                ) or any(transfer.from_address == wallet for transfer in transaction.erc20_transfers)
                if not wallet_outflow:
                    raise ValueError(
                        "the discovered transaction did not contain deterministic value leaving the submitted wallet"
                    )

            evidence = DeterministicEvidence(
                submitted_wallet=wallet,
                transaction=transaction,
            )
            case.evidence = evidence
            case.updated_at = datetime.now(timezone.utc)
            await self.repository.save(case)

            if self.taskmaster:
                await self.taskmaster.trace_initial(case.id, evidence)

            try:
                case.finding = await self.classifier.classify(case.id, evidence)
                case.state = "COMPLETE"
                runtime = "google_adk_gemini"
            except (RuntimeError, ValueError) as exc:
                case.state = "FAILED"
                case.error = str(exc)
                runtime = "unavailable"

            case.updated_at = datetime.now(timezone.utc)
            await self.repository.save(case)
            return CaseResponse(case=case, factual_source="json_rpc", agent_runtime=runtime)
        except Exception as exc:
            case.state = "FAILED"
            case.error = str(exc)
            case.updated_at = datetime.now(timezone.utc)
            await self.repository.save(case)
            raise
