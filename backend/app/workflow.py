from datetime import datetime, timezone
import uuid

from .models import CaseCreate, CaseResponse, DeterministicEvidence, InvestigationCase


SUPPORTED_CHAINS = ("ethereum", "base")


class CaseWorkflow:
    def __init__(self, repository, provider, classifier, taskmaster=None, discovery=None):
        self.repository = repository
        self.provider = provider
        self.classifier = classifier
        self.taskmaster = taskmaster
        self.discovery = discovery

    @staticmethod
    def _append_reason(candidate, reason: str) -> None:
        if reason not in candidate.reasons and len(candidate.reasons) < 12:
            candidate.reasons.append(reason)

    @staticmethod
    def _wallet_outflow(transaction, wallet: str) -> bool:
        return (
            transaction.from_address == wallet
            and int(transaction.native_value_wei) > 0
        ) or any(
            transfer.from_address == wallet
            for transfer in transaction.erc20_transfers
        )

    async def _select_verified_incident(self, chain, wallet, discovery):
        """Choose the likely drain from provider-ranked candidates using RPC facts."""
        if not discovery.candidates:
            tx_hash = discovery.selected_transaction_hash.lower()
            transaction = await self.provider.get_normalized_transaction(chain, tx_hash)
            if transaction.hash.lower() != tx_hash:
                raise ValueError(
                    "resolved transaction hash does not match deterministic RPC evidence"
                )
            if transaction.status != "success" or not self._wallet_outflow(transaction, wallet):
                raise ValueError(
                    "the discovered transaction did not contain deterministic value leaving the submitted wallet"
                )
            return transaction

        ranked = []
        for candidate in discovery.candidates:
            tx_hash = candidate.transaction_hash.lower()
            transaction = await self.provider.get_normalized_transaction(chain, tx_hash)
            if transaction.hash.lower() != tx_hash or transaction.status != "success":
                continue

            token_outflows = [
                transfer for transfer in transaction.erc20_transfers
                if transfer.from_address == wallet
            ]
            native_outflow = (
                transaction.from_address == wallet
                and int(transaction.native_value_wei) > 0
            )
            if not token_outflows and not native_outflow:
                continue

            candidate.transaction_from = transaction.from_address
            candidate.transaction_to = transaction.to_address
            candidate.outgoing_transfer_count = max(
                candidate.outgoing_transfer_count,
                len(token_outflows) + (1 if native_outflow else 0),
            )

            if token_outflows and transaction.from_address != wallet:
                candidate.score += 45
                self._append_reason(
                    candidate,
                    "RPC shows a third-party transaction caller moved wallet tokens",
                )

            distinct_assets = {t.token_contract for t in token_outflows}
            if len(distinct_assets) > 1:
                candidate.score += min(24, 8 * (len(distinct_assets) - 1))
                self._append_reason(
                    candidate,
                    "RPC shows multiple distinct assets leaving the wallet",
                )

            distinct_destinations = {t.to_address for t in token_outflows}
            if len(distinct_destinations) > 1:
                candidate.score += min(12, 4 * (len(distinct_destinations) - 1))
                self._append_reason(
                    candidate,
                    "RPC shows victim funds splitting across destinations",
                )

            if native_outflow and token_outflows:
                candidate.score += 8
                self._append_reason(
                    candidate,
                    "RPC shows native and token value leaving together",
                )

            ranked.append((candidate, transaction))

        if not ranked:
            raise ValueError(
                "no discovered candidate contained deterministic value leaving the submitted wallet"
            )

        ranked.sort(
            key=lambda item: (
                item[0].score,
                item[0].timestamp or datetime.min.replace(tzinfo=timezone.utc),
            ),
            reverse=True,
        )
        discovery.candidates = [candidate for candidate, _ in ranked[:5]]
        selected, transaction = ranked[0]
        discovery.selected_transaction_hash = selected.transaction_hash.lower()
        discovery.selected_score = selected.score
        return transaction

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
                resolved.append((discovery.selected_score, chain, discovery, transaction))
            except Exception as exc:
                failures.append(f"{chain}: {exc}")

        if not resolved:
            detail = "; ".join(failures) if failures else "no supported chain returned a verified incident"
            raise ValueError(
                f"no verified incident found on supported chains ({', '.join(SUPPORTED_CHAINS)}): {detail}"
            )

        resolved.sort(key=lambda item: item[0], reverse=True)
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
