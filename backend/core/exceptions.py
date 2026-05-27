from fastapi import HTTPException, status


class StockCoachError(Exception):
    """Base error for all domain exceptions."""


class MarketDataError(StockCoachError):
    """Raised when fetching market data fails."""


class NewsError(StockCoachError):
    """Raised when fetching news fails."""


class AIAgentError(StockCoachError):
    """Raised when an AI agent call fails."""


class CacheError(StockCoachError):
    """Raised when cache read/write fails."""


class TickerNotFoundError(StockCoachError):
    """Raised when a ticker is not found in the market."""
    def __init__(self, ticker: str) -> None:
        super().__init__(f"Ticker not found: {ticker}")
        self.ticker = ticker


# HTTP-level helpers
def ticker_not_found(ticker: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Ticker '{ticker}' not found or no data available.",
    )


def upstream_error(source: str, detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail=f"Upstream error from {source}: {detail}",
    )


def rate_limit_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Rate limit reached. Please try again later.",
    )
