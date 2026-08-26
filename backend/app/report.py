"""A readable incident report built from the same facts as the evidence package.

The package is structured for machines: an investigator, an exchange fraud desk
or a police report can parse it. A victim downloading it got raw JSON and no way
in. This renders the same values as plain text, keeping the boundary the product
depends on: what the chain proves, what NEMESIS assessed, and what is unknown.

Nothing is computed here. Every line restates a value already present in the
package, so the report can never claim more than the evidence does.
"""
from __future__ import annotations


def _amount(raw: str | int) -> str:
    """Native amounts are stored in wei; show both so neither is lost."""
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return str(raw)
    return f"{value / 1e18:,.6f}".rstrip("0").rstrip(".") + f" (raw {value})"


def render(package: dict) -> str:
    meta = package.get("case_metadata") or {}
    facts = package.get("deterministic_facts") or {}
    assessment = package.get("nemesis_assessment") or {}
    outcome = facts.get("current_outcome") or {}
    discovery = facts.get("discovery") or {}
    evidence = (facts.get("normalized_evidence") or {}).get("transaction") or {}

    L: list[str] = []
    add = L.append

    add("NEMESIS INCIDENT REPORT")
    add("=" * 72)
    add(f"Case             {meta.get('id')}")
    add(f"Status           {meta.get('state')}")
    add(f"Network          {str(meta.get('chain') or '').upper()}")
    add(f"Opened           {meta.get('created_at')}")
    add(f"Report generated {package.get('generated_at')}")
    add("")

    add("WHAT THE CHAIN PROVES")
    add("-" * 72)
    add(f"Affected wallet      {facts.get('submitted_wallet')}")
    add(f"Incident transaction {facts.get('selected_theft_transaction')}")
    if evidence:
        add(f"Block                {evidence.get('block_number')}  ({evidence.get('timestamp')})")
        add(f"Called by            {evidence.get('from_address')}")
        add(f"Transaction status   {evidence.get('status')}")
    if discovery:
        confidence = discovery.get("incident_selection_confidence")
        add(f"Candidates examined  {discovery.get('candidate_count')}")
        if confidence is not None:
            add(f"Incident selection   {round(float(confidence) * 100)}% confidence")
        if discovery.get("ambiguity_reason"):
            add(f"Ambiguity            {discovery['ambiguity_reason']}")
    add("")

    totals = outcome.get("asset_totals") or facts.get("asset_totals") or []
    if totals:
        add("WHAT WAS TAKEN, AND WHERE IT IS")
        add("-" * 72)
        for row in totals:
            label = "ETH" if row.get("asset") == "native" else str(row.get("asset"))
            add(f"Asset      {label}")
            add(f"  stolen     {_amount(row.get('stolen', 0))}")
            add(f"  located    {_amount(row.get('located', 0))}")
            add(f"  unresolved {_amount(row.get('unresolved', 0))}")
        add("")

    holdings = outcome.get("current_holdings") or []
    if holdings:
        add("ADDRESSES CURRENTLY HOLDING TRACED FUNDS")
        add("-" * 72)
        for row in holdings[:25]:
            add(f"  {row.get('address')}   {_amount(row.get('amount', 0))}")
        if len(holdings) > 25:
            add(f"  ... {len(holdings) - 25} more listed in the evidence package")
        add("")

    counts = outcome.get("branch_counts") or {}
    branches = facts.get("trace_branches") or []
    add("HOW THE FUNDS MOVED")
    add("-" * 72)
    add(f"Trace branches   {len(branches)}")
    if branches:
        add(f"Deepest hop      {max(int(b.get('depth') or 0) for b in branches)}")
    live = {k: v for k, v in counts.items() if v}
    if live:
        add("Branch states    " + ", ".join(f"{k} {v}" for k, v in sorted(live.items())))
    for row in outcome.get("terminal_breakdown") or []:
        add(f"  {row.get('reason'):<38} {row.get('branch_count')} branch(es)")
    add("")

    services = outcome.get("identified_services") or []
    if services:
        add("IDENTIFIED DESTINATIONS")
        add("-" * 72)
        for row in services:
            flag = "ACTIONABLE" if row.get("actionable") else "recorded"
            add(f"[{flag}] {row.get('entity_name')}  ({row.get('entity_type')})")
            add(f"  address    {row.get('address')}")
            add(f"  evidence   {row.get('evidence_type')}")
            add(f"  source     {row.get('source')}")
        add("")

    add("NEMESIS ASSESSMENT")
    add("-" * 72)
    if assessment:
        confidence = assessment.get("compromise_mechanism_confidence")
        if confidence is None:
            confidence = assessment.get("confidence")
        add(f"Compromise mechanism  {assessment.get('classification')}")
        if confidence is not None:
            add(f"Confidence            {round(float(confidence) * 100)}%")
        add("")
        add(str(assessment.get("summary") or "").strip())
    else:
        add("No verified assessment was produced for this incident.")
        add("The deterministic evidence above is unaffected.")
    add("")

    add("WHAT YOU CAN DO NOW")
    add("-" * 72)
    for i, action in enumerate(outcome.get("next_actions") or [], 1):
        add(f"{i}. {action}")
    add("")

    add("LIMITS OF THIS REPORT")
    add("-" * 72)
    seen = set()
    for note in [*(outcome.get("limitations") or []), *(package.get("unknowns_and_limitations") or [])]:
        text = str(note).strip()
        if text and text not in seen:
            seen.add(text)
            add(f"- {text}")
    add("")
    add("This report restates the accompanying evidence package and adds nothing")
    add("to it. NEMESIS cannot freeze funds, recover funds, obtain account-holder")
    add("identity, or compel any exchange or authority to act.")
    return "\n".join(L)
