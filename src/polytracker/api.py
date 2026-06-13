"""Polymarket API client.

All public functions handle HTTP errors gracefully and log them instead of
raising, so callers don't need to wrap every call in try/except.
"""

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

import httpx

from polytracker.config import settings

logger = logging.getLogger(__name__)

# In-memory cache: event_id -> category string (with emoji prefix)
category_cache: Dict[str, str] = {}


# ── Public helpers ─────────────────────────────────────────────────────────


async def fetch_positions(
    client: httpx.AsyncClient,
    wallet: str,
) -> Optional[List[Dict[str, Any]]]:
    """Fetch all current positions for *wallet*, paginating as needed.

    Returns ``None`` if the entire request fails (network error, non-2xx
    response, etc.), or a list of position dicts on success.
    """
    url = "https://data-api.polymarket.com/positions"
    all_positions: List[Dict[str, Any]] = []
    limit = settings.api_page_limit
    offset = 0

    try:
        while True:
            params = {
                "user": wallet,
                "sortBy": "CURRENT",
                "sortDirection": "DESC",
                "limit": limit,
                "offset": offset,
            }
            response = await client.get(url, params=params, timeout=settings.api_timeout)
            response.raise_for_status()

            # Detect API returning HTML instead of JSON (Polymarket outage)
            content_type = response.headers.get("content-type", "")
            if "json" not in content_type:
                logger.error(
                    "Polymarket API returned %s (expected JSON) for %s",
                    content_type or "empty response",
                    wallet,
                )
                return None

            data = response.json()

            if not data:
                break

            all_positions.extend(data)

            if len(data) < limit:
                break

            offset += limit

        return all_positions

    except httpx.HTTPError as e:
        logger.error("API error fetching positions for %s: %s", wallet, e)
        return None
    except json.JSONDecodeError as e:
        logger.error("Invalid JSON from Polymarket API for %s: %s", wallet, e)
        return None
    except Exception:
        logger.exception("Unexpected error fetching positions for %s", wallet)
        return None


async def fetch_recent_activity(
    client: httpx.AsyncClient,
    wallet: str,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Fetch recent trades **and** activity for *wallet* concurrently.

    Returns a ``(trades, activity)`` tuple. Either list may be empty if
    the corresponding endpoint failed.
    """
    trades_url = "https://data-api.polymarket.com/trades"
    activity_url = "https://data-api.polymarket.com/activity"
    trades: List[Dict[str, Any]] = []
    activity: List[Dict[str, Any]] = []

    try:
        r1, r2 = await asyncio.gather(
            client.get(
                trades_url,
                params={"user": wallet, "limit": 20},
                timeout=settings.api_timeout,
            ),
            client.get(
                activity_url,
                params={"user": wallet, "limit": 20},
                timeout=settings.api_timeout,
            ),
            return_exceptions=True,
        )

        if isinstance(r1, httpx.Response) and r1.status_code == 200:
            trades = r1.json()
        if isinstance(r2, httpx.Response) and r2.status_code == 200:
            activity = r2.json()

    except httpx.HTTPError as e:
        logger.error("API error fetching activity for %s: %s", wallet, e)
    except Exception:
        logger.exception("Unexpected error fetching activity for %s", wallet)

    return trades, activity


async def get_event_category(
    client: httpx.AsyncClient,
    event_id: Optional[str],
) -> str:
    """Fetch a human-readable category for *event_id*, with emoji prefix.

    Results are cached in ``category_cache`` so repeated lookups for the
    same event return instantly.  Returns an empty string on failure or
    when the category can't be determined.
    """
    if not event_id:
        return ""

    cached = category_cache.get(event_id)
    if cached is not None:
        return cached

    url = f"https://gamma-api.polymarket.com/events/{event_id}"
    try:
        response = await client.get(url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            markets = data.get("markets", [])
            if markets:
                cat = markets[0].get("category", "")
                if cat:
                    # Apply emoji prefix based on keyword matching
                    for keyword, emoji in settings.category_emojis.items():
                        if keyword in cat:
                            cat = f"{emoji} {cat}"
                            break
                    category_cache[event_id] = cat
                    return cat

    except (httpx.HTTPError, ValueError, KeyError) as e:
        logger.debug("Failed to fetch category for event %s: %s", event_id, e)

    return ""


def fetch_positions_blocking(address: str) -> List[Dict[str, Any]]:
    """Fetch all positions synchronously (used during the initial ``/add`` sync).

    Uses ``httpx.Client`` instead of ``requests`` to keep a single HTTP
    library across the project.
    """
    url = "https://data-api.polymarket.com/positions"
    all_positions: List[Dict[str, Any]] = []
    limit = settings.api_page_limit
    offset = 0

    try:
        with httpx.Client(
            verify=settings.api_verify_ssl, proxy=settings.proxy_url or None
        ) as client:
            while True:
                params = {
                    "user": address,
                    "sortBy": "CURRENT",
                    "sortDirection": "DESC",
                    "limit": limit,
                    "offset": offset,
                }
                response = client.get(url, params=params, timeout=settings.api_timeout)
                response.raise_for_status()

                # Detect API returning HTML instead of JSON (Polymarket outage)
                content_type = response.headers.get("content-type", "")
                if "json" not in content_type:
                    logger.error(
                        "Polymarket API returned %s (expected JSON) for %s. "
                        "The API may be temporarily unavailable.",
                        content_type or "empty response",
                        address,
                    )
                    return []

                data = response.json()

                if not data:
                    break

                all_positions.extend(data)

                if len(data) < limit:
                    break

                offset += limit

        return all_positions

    except httpx.HTTPError as e:
        logger.error("HTTP error syncing positions for %s: %s", address, e)
        return []
    except json.JSONDecodeError as e:
        logger.error("Invalid JSON from Polymarket API for %s: %s", address, e)
        return []
    except Exception:
        logger.exception("Unexpected error syncing positions for %s", address)
        return []
