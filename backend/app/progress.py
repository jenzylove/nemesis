"""Investigation progress, reported from the steps the workflow actually reaches.

A wallet-only investigation runs for minutes inside a single request. Without
this the interface can only show one static label for the whole wait, which is
indistinguishable from a hung page. Each phase is published when the workflow
genuinely arrives at it, so the interface never claims progress that has not
happened.

The client supplies the token because it has to poll before the case it is
waiting for exists.
"""
from __future__ import annotations

from datetime import datetime, timezone

# Ordered so the interface can show what is done, what is running, and what is
# still to come, without inventing timings.
PHASES: tuple[tuple[str, str], ...] = (
    ("SEARCHING_WALLET_HISTORY", "Searching wallet history"),
    ("RANKING_CANDIDATES", "Ranking possible incidents"),
    ("VERIFYING_INCIDENT", "Verifying onchain evidence"),
    ("RECONSTRUCTING_ASSETS", "Reconstructing stolen assets"),
    ("TRACING_FUNDS", "Tracing fund movement"),
    ("ASSESSING_COMPROMISE", "Assessing the compromise"),
    ("PREPARING_CASE", "Preparing the case"),
)
PHASE_LABELS = dict(PHASES)
PHASE_ORDER = [name for name, _ in PHASES]


class ProgressReporter:
    """No-op base. Progress reporting must never fail an investigation."""

    async def publish(self, token: str | None, phase: str, owner_user_id: str) -> None:
        return None

    async def read(self, token: str, owner_user_id: str) -> dict | None:
        return None


class InMemoryProgressReporter(ProgressReporter):
    def __init__(self) -> None:
        self._records: dict[str, dict] = {}

    async def publish(self, token, phase, owner_user_id):
        if not token:
            return
        self._records[token] = {
            "phase": phase,
            "owner_user_id": owner_user_id,
            "updated_at": datetime.now(timezone.utc),
        }

    async def read(self, token, owner_user_id):
        record = self._records.get(token)
        if not record or record.get("owner_user_id") != owner_user_id:
            return None
        return record


class FirestoreProgressReporter(ProgressReporter):
    def __init__(self, client, collection: str = "investigation_progress"):
        self.client = client
        self.collection = collection

    async def publish(self, token, phase, owner_user_id):
        if not token:
            return
        try:
            await self.client.collection(self.collection).document(token).set({
                "phase": phase,
                "owner_user_id": owner_user_id,
                "updated_at": datetime.now(timezone.utc),
            })
        except Exception:
            # Progress is a convenience. Losing it must not affect the case.
            return None

    async def read(self, token, owner_user_id):
        try:
            snapshot = await self.client.collection(self.collection).document(token).get()
        except Exception:
            return None
        if not snapshot.exists:
            return None
        record = snapshot.to_dict() or {}
        if record.get("owner_user_id") != owner_user_id:
            return None
        return record


def describe(phase: str | None) -> dict:
    """Public shape: the phase reached, its label, and where it sits in the run."""
    if phase not in PHASE_LABELS:
        return {"phase": None, "label": None, "index": 0, "total": len(PHASE_ORDER), "phases": PHASES_PUBLIC}
    return {
        "phase": phase,
        "label": PHASE_LABELS[phase],
        "index": PHASE_ORDER.index(phase) + 1,
        "total": len(PHASE_ORDER),
        "phases": PHASES_PUBLIC,
    }


PHASES_PUBLIC = [{"phase": name, "label": label} for name, label in PHASES]
