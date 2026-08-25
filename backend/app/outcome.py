from __future__ import annotations

# Why a branch stopped, and what that means for the victim. These are kept
# apart deliberately: reaching the configured trace depth means NEMESIS knows
# where the funds are and chose to stop, while a retrieval failure means it
# could not establish what happened next. Collapsing the two would let an
# infrastructure limit read as a forensic conclusion.
DEPTH_LIMITED = "MAX_DEPTH"
RETRIEVAL_FAILED = "CONTINUATION_EVIDENCE_UNAVAILABLE"
BRIDGE_UNRESOLVED = {"BRIDGE_DESTINATION_UNRESOLVED", "BRIDGE_DESTINATION_EVIDENCE_INCOMPLETE"}

# Funds whose onward path could not be established. Funds resting at a known
# address are located, even when tracing deliberately stopped there.
UNRESOLVED_REASONS = {RETRIEVAL_FAILED} | BRIDGE_UNRESOLVED


def derive_case_state(branches: list[dict], current: str) -> str:
    statuses = {branch.get("status") for branch in branches}
    if "ACTIONABLE" in statuses:
        return "ACTIONABLE"
    if "MOVING" in statuses:
        return "INVESTIGATING"
    if "DORMANT" in statuses:
        return "MONITORING"
    if statuses and statuses <= {"OBSCURED", "RECOVERED"}:
        return "LIMITED" if "OBSCURED" in statuses else "EVIDENCE_READY"
    return current


def _amount(branch: dict) -> int:
    try:
        return int(branch.get("amount") or 0)
    except (TypeError, ValueError):
        return 0


def build_outcome(asset_totals: list[dict], trace: dict) -> dict:
    branches = trace.get("branches") or []
    counts = {status: 0 for status in ("MOVING", "DORMANT", "OBSCURED", "ACTIONABLE", "RECOVERED")}
    services = []
    reasons: dict[str, dict] = {}
    for branch in branches:
        status = branch.get("status")
        if status in counts:
            counts[status] += 1
        reason = branch.get("terminal_reason")
        if reason:
            bucket = reasons.setdefault(reason, {"branch_count": 0, "amounts": {}})
            bucket["branch_count"] += 1
            asset = branch.get("asset") or "unknown"
            bucket["amounts"][asset] = bucket["amounts"].get(asset, 0) + _amount(branch)
        attribution = branch.get("attribution")
        if attribution:
            services.append({
                "branch_id": branch.get("id"),
                "entity_name": attribution.get("entity_name"),
                "entity_type": attribution.get("entity_type"),
                "address": attribution.get("address"),
                "chain": attribution.get("chain"),
                "confidence": attribution.get("confidence"),
                "source": attribution.get("source"),
                "evidence_type": attribution.get("evidence_type"),
                "actionable": bool(attribution.get("actionable")),
            })

    # Where the money actually sits now, largest first. This is the question a
    # victim asks before any other, and it is answerable straight from the
    # persisted branches.
    holdings = sorted(
        (
            {
                "address": branch.get("current_address"),
                "chain": branch.get("chain"),
                "asset": branch.get("asset"),
                "amount": branch.get("amount"),
                "status": branch.get("status"),
                "terminal_reason": branch.get("terminal_reason"),
                "depth": branch.get("depth"),
            }
            for branch in branches
        ),
        key=lambda item: int(item["amount"] or 0),
        reverse=True,
    )[:10]

    terminal_breakdown = [
        {
            "reason": reason,
            "branch_count": bucket["branch_count"],
            "amounts": [
                {"asset": asset, "amount": str(amount), "unit": "raw"}
                for asset, amount in sorted(bucket["amounts"].items())
            ],
            "meaning": _reason_meaning(reason),
        }
        for reason, bucket in sorted(reasons.items())
    ]

    sanctioned = [s for s in services if s["entity_type"] == "sanctioned"]
    contactable = [s for s in services if s["entity_type"] in ("exchange", "service")]
    depth_limited = reasons.get(DEPTH_LIMITED, {}).get("branch_count", 0)
    retrieval_failed = reasons.get(RETRIEVAL_FAILED, {}).get("branch_count", 0)

    actions = ["Download and preserve the current evidence package."]
    if sanctioned:
        actions.append(
            "Traced funds reached an address carrying an OFAC sanctions designation. "
            "Report this case, with the preserved evidence package, to law enforcement "
            "and to any exchange you filed a report with."
        )
    if contactable:
        actions.append("Contact the attributed service with the verified transaction evidence.")
    if counts["DORMANT"]:
        actions.append("Continue monitoring dormant branches for confirmed movement.")
    if depth_limited:
        actions.append(
            f"{depth_limited} branch(es) reached the configured trace depth with funds still "
            "identifiable onchain. The addresses holding them are listed in this case."
        )
    if retrieval_failed:
        actions.append(
            f"{retrieval_failed} branch(es) could not be extended because onchain evidence "
            "could not be retrieved. Re-running the investigation later may extend them."
        )

    summary = _summary(branches, counts, sanctioned, depth_limited, retrieval_failed)

    limitations = [
        "Amounts use raw onchain units when verified token decimals are unavailable.",
        "NEMESIS cannot freeze funds, access KYC records, or guarantee recovery.",
        "A sanctions designation identifies the destination address, not the person controlling it.",
    ]
    if depth_limited:
        limitations.append(
            "Tracing stops at a configured depth. Branches that reached it are not conclusions, "
            "only the point where this investigation stopped following them."
        )
    if retrieval_failed:
        limitations.append(
            "Some branches could not be extended because an onchain data source was unavailable. "
            "That is a retrieval limit, not evidence that those funds stopped moving."
        )

    return {
        "summary": summary,
        "asset_totals": asset_totals,
        "branch_counts": {key.lower(): value for key, value in counts.items()},
        "terminal_breakdown": terminal_breakdown,
        "current_holdings": holdings,
        "identified_services": services,
        "next_actions": actions,
        "limitations": limitations,
    }


def _reason_meaning(reason: str) -> str:
    if reason == DEPTH_LIMITED:
        return "Funds are identifiable at this address; tracing stopped at the configured depth."
    if reason == RETRIEVAL_FAILED:
        return "Onchain evidence could not be retrieved, so onward movement is unknown."
    if reason in BRIDGE_UNRESOLVED:
        return "Funds entered a bridge whose destination could not be deterministically resolved."
    if reason == "NO_DETERMINISTIC_OUTGOING_PATH":
        return "No verified onward movement from this address; the branch is under monitoring."
    if reason == "DETERMINISTIC_ACTIONABLE_ENTITY":
        return "Funds reached a destination NEMESIS can attribute from deterministic evidence."
    return "See the branch evidence for why tracing stopped here."


def _summary(branches, counts, sanctioned, depth_limited, retrieval_failed) -> str:
    if not branches:
        return "No qualifying trace branch has been established from the verified incident yet."
    traced = f"Stolen funds were traced across {len(branches)} branch(es)"
    if sanctioned:
        return (
            f"{traced}, and {len(sanctioned)} of them reached an OFAC-sanctioned address. "
            "Unresolved branches remain monitored where applicable."
        )
    if counts["ACTIONABLE"]:
        return f"{traced}, {counts['ACTIONABLE']} of which reached an attributed destination."
    if counts["DORMANT"]:
        return (
            f"{traced}. No actionable destination identified yet; "
            f"{counts['DORMANT']} dormant branch(es) remain under monitoring."
        )
    if counts["MOVING"]:
        return f"{traced}, and tracing remains active across {counts['MOVING']} of them."
    parts = []
    if depth_limited:
        parts.append(f"{depth_limited} reached the configured trace depth with funds still identifiable onchain")
    if retrieval_failed:
        parts.append(f"{retrieval_failed} could not be extended because onchain evidence could not be retrieved")
    if parts:
        return f"{traced}. " + "; ".join(parts).capitalize() + "."
    return f"{traced}. Remaining branches are terminal; limitations are preserved with the evidence."
