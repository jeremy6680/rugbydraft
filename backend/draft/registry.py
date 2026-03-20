# backend/draft/registry.py
"""
DraftRegistry — in-memory store of active DraftEngine instances.

One DraftEngine per active draft, keyed by league_id.
The registry is stored as a singleton in FastAPI's application state
(app.state.draft_registry) so all request handlers share the same instance.

Architecture note (D-001):
    FastAPI is the authority of state. The registry IS that authority —
    it holds the live DraftEngine objects. Supabase is never queried
    for draft state during an active draft.

Lifecycle:
    - register()         : called when a draft is started
    - get()              : called by all draft endpoints
    - remove()           : called when the draft completes or is cancelled
    - active_league_ids(): diagnostic / admin use

Thread safety:
    Mutations (register, remove) are protected by an asyncio.Lock.
    get() is read-only — no lock needed (GIL + atomic dict lookup in CPython).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from draft.engine import DraftEngine

logger = logging.getLogger(__name__)


class DraftRegistry:
    """Thread-safe in-memory registry of active DraftEngine instances.

    Usage (FastAPI lifespan — see app/main.py):
        app.state.draft_registry = DraftRegistry()

    Usage (endpoint):
        registry: DraftRegistry = request.app.state.draft_registry
        engine = registry.get(league_id)
        if engine is None:
            raise HTTPException(404, "No active draft for this league")
    """

    def __init__(self) -> None:
        """Initialise with an empty registry and a concurrency lock."""
        self._engines: dict[str, DraftEngine] = {}
        self._lock = asyncio.Lock()

    async def register(self, league_id: str, engine: DraftEngine) -> None:
        """Register a new DraftEngine for a league.

        Args:
            league_id: The league this draft belongs to.
            engine: The DraftEngine instance to register.

        Raises:
            ValueError: If an engine already exists for this league_id.
                        Call remove() first to replace an existing draft.
        """
        async with self._lock:
            if league_id in self._engines:
                raise ValueError(
                    f"A draft engine already exists for league '{league_id}'. "
                    "Call remove() before registering a new one."
                )
            self._engines[league_id] = engine
            logger.info(
                "DraftRegistry: engine registered for league '%s'", league_id
            )

    def get(self, league_id: str) -> Optional[DraftEngine]:
        """Return the active DraftEngine for a league, or None.

        Read-only — no lock needed.

        Args:
            league_id: The league to look up.

        Returns:
            The DraftEngine if an active draft exists, None otherwise.
        """
        return self._engines.get(league_id)

    async def remove(self, league_id: str) -> None:
        """Remove and discard the DraftEngine for a league.

        Safe to call if no engine exists for this league (no-op).

        Args:
            league_id: The league whose engine should be removed.
        """
        async with self._lock:
            engine = self._engines.pop(league_id, None)
            if engine is not None:
                logger.info(
                    "DraftRegistry: engine removed for league '%s'", league_id
                )

    def active_league_ids(self) -> list[str]:
        """Return the list of league IDs with an active draft engine.

        For diagnostic and admin endpoints only — not for pick validation.

        Returns:
            Snapshot list of active league IDs at call time.
        """
        return list(self._engines.keys())

    def __len__(self) -> int:
        """Number of currently active draft engines."""
        return len(self._engines)