from __future__ import annotations


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


def build_outcome(asset_totals: list[dict], trace: dict) -> dict:
    branches = trace.get("branches") or []
    counts = {status: 0 for status in ("MOVING", "DORMANT", "OBSCURED", "ACTIONABLE", "RECOVERED")}
    services = []
    for branch in branches:
        status = branch.get("status")
        if status in counts:
            counts[status] += 1
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
    actions = ["Download and preserve the current evidence package."]
    if counts["ACTIONABLE"]:
        actions.append("Contact the attributed service with the verified transaction evidence.")
    if counts["DORMANT"]:
        actions.append("Continue monitoring dormant branches for confirmed movement.")
    if counts["OBSCURED"]:
        actions.append("Review unresolved branches and their stated evidence limitations.")
    if not branches:
        summary = "No qualifying trace branch has been established from the verified incident yet."
    elif counts["ACTIONABLE"]:
        summary = f"{counts['ACTIONABLE']} actionable destination branch(es) identified; unresolved branches remain monitored where applicable."
    elif counts["DORMANT"]:
        summary = f"No actionable destination identified yet. {counts['DORMANT']} dormant branch(es) remain under monitoring."
    elif counts["MOVING"]:
        summary = f"Tracing remains active across {counts['MOVING']} moving branch(es)."
    else:
        summary = "Tracing reached only unresolved or terminal branches; limitations are preserved with the evidence."
    return {
        "summary": summary,
        "asset_totals": asset_totals,
        "branch_counts": {key.lower(): value for key, value in counts.items()},
        "identified_services": services,
        "next_actions": actions,
        "limitations": [
            "Amounts use raw onchain units when verified token decimals are unavailable.",
            "NEMESIS cannot freeze funds, access KYC records, or guarantee recovery.",
        ],
    }