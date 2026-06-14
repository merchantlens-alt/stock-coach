"""
fund_portfolio — shared model-portfolio assembly for India MFs and US ETFs.

Both markets build "the N funds you should own" the same way:
  • one fund per ROLE (not N top-scorers — that would overlap),
  • each the best LONG-TERM pick in its category with rule-outs excluded,
  • avoid two funds from the same AMC / issuer,
  • weights from a risk preset, renormalised if a slot can't be filled.

Only the slot taxonomy, weights, and rationale differ per market — those are
passed in, so this assembler stays market-agnostic.
"""
from __future__ import annotations

import re
from typing import Optional

from models.schemas import FundScheme, ModelHolding, ModelPortfolioResponse

# A slot = (role, primary category, fallback categories, plain-English role note).
Slot = tuple[str, str, list[str], str]


def amc_of(name: str) -> str:
    """Normalised issuer/AMC key (first brand word) for overlap control."""
    words = re.sub(r"[^a-z0-9 ]", "", name.lower()).split()
    return words[0] if words else name.lower()


def _pick_for_slot(
    categories: list[str],
    by_cat: dict[str, list[FundScheme]],
    used_amc: set[str],
    used_codes: set[str],
) -> Optional[FundScheme]:
    # First pass respects AMC diversification; second relaxes it if forced to.
    for allow_dupe_amc in (False, True):
        for cat in categories:
            for f in by_cat.get(cat, []):
                if f.scheme_code in used_codes:
                    continue
                if not allow_dupe_amc and amc_of(f.name) in used_amc:
                    continue
                return f
    return None


def _slot_why(role: str, role_note: str, f: FundScheme) -> str:
    rank = (f"#{f.category_rank} of {f.category_size} in {f.category}"
            if f.category_rank else f"a {f.category} fund")
    # Bonds are picked for stability, not return — don't claim "long-term potential".
    basis = "on cost & stability" if f.category == "Bonds" else "on long-term potential"
    extra = ""
    if f.is_discovery:
        extra = " A younger fund already beating peers — held small as a satellite."
    elif f.expense_ratio is not None:
        extra = f" Expense ratio {f.expense_ratio:.2f}%."
    elif f.active_return_3y is not None and f.active_return_3y > 0:
        extra = f" Beats its benchmark by {f.active_return_3y:+.0f}pp."
    return f"{role}: {role_note}. Picked {rank} {basis}.{extra}"


def assemble_portfolio(
    *,
    funds: list[FundScheme],
    slots: list[Slot],
    weights: list[float],
    risk: str,
    rationale: str,
    market: str,
    universe_size: int,
    no_cost_note: Optional[str] = None,
) -> ModelPortfolioResponse:
    """Build a role-diversified model portfolio from a scored fund list."""
    if not funds:
        return ModelPortfolioResponse(market=market, risk=risk, universe_size=universe_size)  # type: ignore[arg-type]

    # Eligible picks: drop rule-outs and anything the scanner rates "avoid" — a
    # model portfolio should never recommend a fund we'd tell you to skip.
    by_cat: dict[str, list[FundScheme]] = {}
    for f in funds:
        if f.is_closet_index or f.is_decaying or f.entry_signal == "avoid":
            continue
        by_cat.setdefault(f.category or "?", []).append(f)
    for lst in by_cat.values():
        lst.sort(key=lambda f: f.long_term_score, reverse=True)

    used_amc: set[str] = set()
    used_codes: set[str] = set()
    holdings: list[ModelHolding] = []

    for (role, primary, fallbacks, role_note), weight in zip(slots, weights):
        if weight <= 0:
            continue
        pick = _pick_for_slot([primary, *fallbacks], by_cat, used_amc, used_codes)
        if pick is None:
            continue
        used_amc.add(amc_of(pick.name))
        used_codes.add(pick.scheme_code)
        holdings.append(ModelHolding(
            role=role, weight_pct=float(weight),
            why=_slot_why(role, role_note, pick), fund=pick,
        ))

    # Renormalise weights to 100 if a slot was skipped.
    filled = sum(h.weight_pct for h in holdings)
    if holdings and filled > 0 and abs(filled - 100.0) > 0.1:
        for h in holdings:
            h.weight_pct = round(h.weight_pct / filled * 100, 1)

    # Blended TER only if every holding has a sourced expense ratio.
    blended: Optional[float] = None
    if holdings and all(h.fund.expense_ratio is not None for h in holdings):
        blended = round(sum(h.weight_pct / 100 * (h.fund.expense_ratio or 0) for h in holdings), 3)

    final_rationale = rationale
    if blended is None and no_cost_note:
        final_rationale += " " + no_cost_note

    return ModelPortfolioResponse(
        market=market,  # type: ignore[arg-type]
        risk=risk,  # type: ignore[arg-type]
        holdings=holdings, rationale=final_rationale,
        blended_expense_ratio=blended, universe_size=universe_size,
    )
