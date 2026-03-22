"""Trade proposal validation for RugbyDraft.

Seven rules are checked in order. Each failing rule raises a typed exception
so the FastAPI router can return a precise HTTP 400/403 response.

Rule order matters: cheap checks first, expensive checks last.
  1. Window open       — pure date/round math (cheapest)
  2. Self-trade        — identity check
  3. Ghost team        — single is_ghost_id() call
  4. Format            — count check
  5. Ownership         — O(n) set lookup
  6. Duplicates        — O(n) set intersection
  7. IR block          — most expensive (requires IR roster state)

This module is pure — no I/O, no database calls.
"""

from __future__ import annotations

from dataclasses import dataclass

from trades.window import TradeWindowContext, is_trade_window_open


# ---------------------------------------------------------------------------
# Typed exceptions — one per rule, all extend TradeValidationError
# ---------------------------------------------------------------------------


class TradeValidationError(Exception):
    """Base class for all trade validation errors."""


class TradeWindowClosedError(TradeValidationError):
    """Raised when a trade is proposed outside the allowed window."""


class TradeSelfTradeError(TradeValidationError):
    """Raised when a manager proposes a trade with themselves."""


class TradeGhostTeamError(TradeValidationError):
    """Raised when a ghost team is a party to the trade (CDC §11)."""


class TradeFormatError(TradeValidationError):
    """Raised when the trade format is invalid (not 1v1, 1v2, or 1v3)."""


class TradeOwnershipError(TradeValidationError):
    """Raised when a player does not belong to the claimed manager."""


class TradeDuplicatePlayerError(TradeValidationError):
    """Raised when the same player appears on both sides of the trade."""


class TradeIRBlockError(TradeValidationError):
    """Raised when a manager has an unintegrated recovered IR player (CDC §6.4)."""


# ---------------------------------------------------------------------------
# Input dataclasses — immutable, pure data
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TradeParty:
    """One side of a trade proposal.

    Attributes:
        member_id: The league member UUID.
        player_ids: The player UUIDs this party is giving away.
            - Proposer gives 1 player (always exactly 1, CDC §9.2).
            - Receiver gives 1, 2, or 3 players.
        is_ghost_team: Whether this member is a computer-managed ghost team.
        roster_player_ids: All player UUIDs currently on this member's roster.
            Used for ownership validation.
        has_unintegrated_ir_player: True if this manager has a recovered IR
            player not yet reintegrated for more than 1 week (CDC §6.4).
    """

    member_id: str
    player_ids: frozenset[str]
    is_ghost_team: bool
    roster_player_ids: frozenset[str]
    has_unintegrated_ir_player: bool


@dataclass(frozen=True)
class TradeProposal:
    """All data needed to validate a trade proposal.

    Attributes:
        proposer: The manager initiating the trade.
        receiver: The manager receiving the proposal.
        window_ctx: Trade window context (date + round state).
    """

    proposer: TradeParty
    receiver: TradeParty
    window_ctx: TradeWindowContext


# ---------------------------------------------------------------------------
# Individual rule validators — pure functions, raise on failure
# ---------------------------------------------------------------------------


def _check_window(proposal: TradeProposal) -> None:
    """Rule 1 — Trade window must be open (date + round double check)."""
    open_, reason = is_trade_window_open(proposal.window_ctx)
    if not open_:
        raise TradeWindowClosedError(reason)


def _check_no_self_trade(proposal: TradeProposal) -> None:
    """Rule 2 — A manager cannot trade with themselves."""
    if proposal.proposer.member_id == proposal.receiver.member_id:
        raise TradeSelfTradeError("A manager cannot propose a trade with themselves.")


def _check_no_ghost_team(proposal: TradeProposal) -> None:
    """Rule 3 — Ghost teams cannot participate in trades (CDC §11)."""
    if proposal.proposer.is_ghost_team:
        raise TradeGhostTeamError(
            f"Ghost team {proposal.proposer.member_id} cannot initiate trades."
        )
    if proposal.receiver.is_ghost_team:
        raise TradeGhostTeamError(
            f"Ghost team {proposal.receiver.member_id} cannot receive trade proposals."
        )


def _check_format(proposal: TradeProposal) -> None:
    """Rule 4 — Each side must give 1, 2, or 3 players (CDC §9.2).

    Valid formats: 1v1, 1v2, 1v3, 2v1, 2v2, 2v3, 3v1, 3v2, 3v3.
    No pick exchanges — only player-for-player.
    """
    proposer_count = len(proposal.proposer.player_ids)
    receiver_count = len(proposal.receiver.player_ids)

    if proposer_count not in (1, 2, 3):
        raise TradeFormatError(
            f"Proposer must offer 1, 2, or 3 players, got {proposer_count}."
        )
    if receiver_count not in (1, 2, 3):
        raise TradeFormatError(
            f"Receiver must give 1, 2, or 3 players, got {receiver_count}."
        )


def _check_ownership(proposal: TradeProposal) -> None:
    """Rule 5 — Each player must belong to the party giving them away."""
    for player_id in proposal.proposer.player_ids:
        if player_id not in proposal.proposer.roster_player_ids:
            raise TradeOwnershipError(
                f"Player {player_id} does not belong to proposer "
                f"{proposal.proposer.member_id}."
            )
    for player_id in proposal.receiver.player_ids:
        if player_id not in proposal.receiver.roster_player_ids:
            raise TradeOwnershipError(
                f"Player {player_id} does not belong to receiver "
                f"{proposal.receiver.member_id}."
            )


def _check_no_duplicates(proposal: TradeProposal) -> None:
    """Rule 6 — The same player cannot appear on both sides of the trade."""
    overlap = proposal.proposer.player_ids & proposal.receiver.player_ids
    if overlap:
        raise TradeDuplicatePlayerError(
            f"Player(s) {overlap} appear on both sides of the trade."
        )


def _check_ir_block(proposal: TradeProposal) -> None:
    """Rule 7 — IR block: neither party can trade with an unintegrated recovered player.

    CDC §6.4 + §9.2: if a manager has a player who recovered from injury
    more than 1 week ago and has not been reintegrated into the active roster,
    all trades (and waivers) are blocked until reintegration.
    """
    if proposal.proposer.has_unintegrated_ir_player:
        raise TradeIRBlockError(
            f"Manager {proposal.proposer.member_id} has an unintegrated recovered "
            "IR player. Reintegrate the player before proposing trades."
        )
    if proposal.receiver.has_unintegrated_ir_player:
        raise TradeIRBlockError(
            f"Manager {proposal.receiver.member_id} has an unintegrated recovered "
            "IR player. They cannot accept trades until they reintegrate."
        )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

# Ordered list of rule checkers — order is significant (cheap first).
_RULES: list = [
    _check_window,
    _check_no_self_trade,
    _check_no_ghost_team,
    _check_format,
    _check_ownership,
    _check_no_duplicates,
    _check_ir_block,
]


def validate_trade(proposal: TradeProposal) -> None:
    """Run all 7 validation rules against a trade proposal.

    Rules are evaluated in order. The first failing rule raises its
    typed exception — subsequent rules are not evaluated.

    Args:
        proposal: The fully populated trade proposal to validate.

    Raises:
        TradeWindowClosedError: Window is closed (date or round).
        TradeSelfTradeError: Proposer and receiver are the same manager.
        TradeGhostTeamError: One party is a ghost team.
        TradeFormatError: Not a 1v1, 1v2, or 1v3 format.
        TradeOwnershipError: A player does not belong to the claimed party.
        TradeDuplicatePlayerError: Same player on both sides.
        TradeIRBlockError: Either party has an unintegrated recovered IR player.
    """
    for rule in _RULES:
        rule(proposal)
