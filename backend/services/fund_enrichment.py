"""
fund_enrichment — pluggable provider for the two data points mfapi lacks:
expense ratio (TER) and AUM, for India mutual funds.

This is the clean seam for closing the India data gap. The scanner/model code
depends only on this interface; a concrete provider (e.g. an AMFI adapter) is
wired in once its data source + format are confirmed on a network that can reach
AMFI. Until then `NullEnrichmentProvider` is used and everything degrades
gracefully (TER/AUM stay None, scoring falls back to NAV-derived signals).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class FundEnrichment:
    expense_ratio: Optional[float] = None   # Total Expense Ratio %, e.g. 0.65
    aum: Optional[float] = None             # ₹ crore


class FundEnrichmentProvider(ABC):
    @abstractmethod
    async def enrich(self, scheme_codes: list[str]) -> dict[str, FundEnrichment]:
        """Return {scheme_code: FundEnrichment} for the codes it can resolve."""
        ...


class NullEnrichmentProvider(FundEnrichmentProvider):
    """Default — sources nothing. TER/AUM stay None; NAV-derived scoring is used."""

    async def enrich(self, scheme_codes: list[str]) -> dict[str, FundEnrichment]:
        return {}


class StaticEnrichmentProvider(FundEnrichmentProvider):
    """
    Serves a pre-built {scheme_code: FundEnrichment} map. Useful for tests and as
    the target shape an AMFI/Kuvera adapter should populate (e.g. parse AMFI's
    AAUM disclosure + a TER source into this map, cached daily).
    """

    def __init__(self, data: dict[str, FundEnrichment]) -> None:
        self._data = data

    async def enrich(self, scheme_codes: list[str]) -> dict[str, FundEnrichment]:
        return {c: self._data[c] for c in scheme_codes if c in self._data}
