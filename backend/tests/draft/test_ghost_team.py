# backend/tests/draft/test_ghost_team.py
"""Unit tests for backend/draft/ghost_team.py.

All tests are pure (no I/O, no FastAPI, no DB).
Deterministic behaviour is guaranteed via the seed parameter.
"""

import pytest

from draft.ghost_team import (
    GHOST_ID_PREFIX,
    GhostTeam,
    _GHOST_AVATARS,
    _GHOST_CITIES,
    _GHOST_NAME_TEMPLATES,
    create_ghost_teams,
    generate_ghost_avatar,
    generate_ghost_name,
    ghost_teams_needed,
    is_ghost_id,
)


# ---------------------------------------------------------------------------
# TestIsGhostId
# ---------------------------------------------------------------------------


class TestIsGhostId:
    """is_ghost_id() is the single source of truth for ghost detection."""

    def test_ghost_id_prefix_detected(self) -> None:
        """A well-formed ghost ID is correctly identified."""
        assert is_ghost_id("ghost-abc-123") is True

    def test_ghost_id_prefix_constant_used(self) -> None:
        """Detection relies on the GHOST_ID_PREFIX constant — not a hardcoded string."""
        assert is_ghost_id(f"{GHOST_ID_PREFIX}anything") is True

    def test_human_uuid_not_detected(self) -> None:
        """A standard Supabase Auth UUID is not a ghost ID."""
        assert is_ghost_id("550e8400-e29b-41d4-a716-446655440000") is False

    def test_empty_string_not_detected(self) -> None:
        assert is_ghost_id("") is False

    def test_partial_prefix_not_detected(self) -> None:
        """'ghos-...' (missing 't') must not match."""
        assert is_ghost_id("ghos-t-something") is False

    def test_prefix_in_middle_not_detected(self) -> None:
        """The prefix must be at the start, not embedded."""
        assert is_ghost_id("user-ghost-123") is False


# ---------------------------------------------------------------------------
# TestGenerateGhostName
# ---------------------------------------------------------------------------


class TestGenerateGhostName:
    """generate_ghost_name() returns a well-formed display name."""

    def test_returns_string(self) -> None:
        name = generate_ghost_name(seed=0)
        assert isinstance(name, str)

    def test_name_is_not_empty(self) -> None:
        name = generate_ghost_name(seed=1)
        assert len(name) > 0

    def test_name_contains_a_city(self) -> None:
        """The generated name must contain one of the known rugby cities."""
        name = generate_ghost_name(seed=42)
        assert any(city in name for city in _GHOST_CITIES)

    def test_name_matches_a_template(self) -> None:
        """The generated name must be derived from a known template."""
        name = generate_ghost_name(seed=42)
        # Check that the name matches at least one template pattern
        # by verifying the city-free part is recognised.
        matched = any(
            name == template.format(city=city)
            for template in _GHOST_NAME_TEMPLATES
            for city in _GHOST_CITIES
        )
        assert matched, f"Name '{name}' does not match any known template+city combo"

    def test_seed_is_deterministic(self) -> None:
        """Same seed must always produce the same name."""
        assert generate_ghost_name(seed=99) == generate_ghost_name(seed=99)

    def test_different_seeds_produce_variety(self) -> None:
        """Different seeds should produce different names (probabilistic check)."""
        names = {generate_ghost_name(seed=i) for i in range(20)}
        # With 105 possible combinations, 20 draws should yield > 1 unique name.
        assert len(names) > 1

    def test_no_seed_does_not_raise(self) -> None:
        """Production call (seed=None) must not raise."""
        name = generate_ghost_name()
        assert isinstance(name, str)


# ---------------------------------------------------------------------------
# TestGenerateGhostAvatar
# ---------------------------------------------------------------------------


class TestGenerateGhostAvatar:
    """generate_ghost_avatar() returns a valid avatar identifier."""

    def test_returns_known_avatar_id(self) -> None:
        avatar = generate_ghost_avatar(seed=0)
        assert avatar in _GHOST_AVATARS

    def test_seed_is_deterministic(self) -> None:
        assert generate_ghost_avatar(seed=7) == generate_ghost_avatar(seed=7)

    def test_no_seed_does_not_raise(self) -> None:
        avatar = generate_ghost_avatar()
        assert avatar in _GHOST_AVATARS


# ---------------------------------------------------------------------------
# TestCreateGhostTeams
# ---------------------------------------------------------------------------


class TestCreateGhostTeams:
    """create_ghost_teams() produces correctly formed GhostTeam instances."""

    def test_returns_correct_count(self) -> None:
        teams = create_ghost_teams(3, seed=0)
        assert len(teams) == 3

    def test_single_ghost_team(self) -> None:
        teams = create_ghost_teams(1, seed=0)
        assert len(teams) == 1

    def test_all_ids_are_ghost_ids(self) -> None:
        teams = create_ghost_teams(4, seed=0)
        assert all(is_ghost_id(t.manager_id) for t in teams)

    def test_all_ids_are_unique(self) -> None:
        """uuid4-based IDs must never collide, even within one batch."""
        teams = create_ghost_teams(10, seed=0)
        ids = [t.manager_id for t in teams]
        assert len(ids) == len(set(ids))

    def test_all_names_are_non_empty_strings(self) -> None:
        teams = create_ghost_teams(3, seed=1)
        assert all(isinstance(t.name, str) and len(t.name) > 0 for t in teams)

    def test_all_avatars_are_valid(self) -> None:
        teams = create_ghost_teams(5, seed=2)
        assert all(t.avatar_id in _GHOST_AVATARS for t in teams)

    def test_names_are_unique_for_small_count(self) -> None:
        """With count <= 105 combinations, names must be drawn without replacement."""
        teams = create_ghost_teams(10, seed=3)
        names = [t.name for t in teams]
        assert len(names) == len(set(names))

    def test_returns_frozen_dataclasses(self) -> None:
        """GhostTeam is frozen — mutation must raise."""
        team = create_ghost_teams(1, seed=0)[0]
        with pytest.raises(Exception):
            team.name = "Mutated"  # type: ignore[misc]

    def test_count_zero_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="count must be >= 1"):
            create_ghost_teams(0)

    def test_count_negative_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="count must be >= 1"):
            create_ghost_teams(-1)

    def test_ids_unique_across_two_batches(self) -> None:
        """Two separate calls must never produce the same manager_id."""
        batch_a = create_ghost_teams(5, seed=10)
        batch_b = create_ghost_teams(5, seed=10)
        ids_a = {t.manager_id for t in batch_a}
        ids_b = {t.manager_id for t in batch_b}
        # uuid4 makes collision astronomically unlikely — but we verify anyway.
        assert ids_a.isdisjoint(ids_b)


# ---------------------------------------------------------------------------
# TestGhostTeamsNeeded
# ---------------------------------------------------------------------------


class TestGhostTeamsNeeded:
    """ghost_teams_needed() implements CDC section 11 business rules.

    Rules:
    1. Total team count must be >= min_teams (default 4).
    2. Total team count must be even.
    Both conditions must be satisfied simultaneously.
    """

    def test_four_managers_needs_zero(self) -> None:
        """4 managers: even + meets minimum → no ghost needed."""
        assert ghost_teams_needed(4) == 0

    def test_six_managers_needs_zero(self) -> None:
        assert ghost_teams_needed(6) == 0

    def test_eight_managers_needs_zero(self) -> None:
        assert ghost_teams_needed(8) == 0

    def test_three_managers_needs_one(self) -> None:
        """3 managers: below minimum (4) → add 1 to reach 4 (even). """
        assert ghost_teams_needed(3) == 1

    def test_five_managers_needs_one(self) -> None:
        """5 managers: meets minimum but odd → add 1 ghost."""
        assert ghost_teams_needed(5) == 1

    def test_seven_managers_needs_one(self) -> None:
        assert ghost_teams_needed(7) == 1

    def test_two_managers_needs_two(self) -> None:
        """2 managers: below minimum (4) and even → add 2 to reach 4."""
        assert ghost_teams_needed(2) == 2

    def test_one_manager_needs_three(self) -> None:
        """1 manager: needs 3 ghosts to reach 4 (minimum + even)."""
        assert ghost_teams_needed(1) == 3

    def test_total_is_always_even(self) -> None:
        """For any manager count 1–20, total must always be even."""
        for n in range(1, 21):
            needed = ghost_teams_needed(n)
            assert (n + needed) % 2 == 0, (
                f"manager_count={n}, needed={needed}, total={n + needed} is odd"
            )

    def test_total_always_meets_minimum(self) -> None:
        """For any manager count 1–20, total must always be >= 4."""
        for n in range(1, 21):
            needed = ghost_teams_needed(n)
            assert n + needed >= 4, (
                f"manager_count={n}, needed={needed}, total={n + needed} < 4"
            )

    def test_custom_minimum(self) -> None:
        """min_teams parameter overrides the default of 4."""
        # 6 managers, min=8: need 2 more to reach 8 (even).
        assert ghost_teams_needed(6, min_teams=8) == 2

    def test_custom_minimum_odd_result_still_rounded_up(self) -> None:
        """Even with a custom min, the total must still be even."""
        # 4 managers, min=7: need 3 to reach 7 (odd) → 4 to reach 8.
        assert ghost_teams_needed(4, min_teams=7) == 4

    def test_zero_managers_raises(self) -> None:
        with pytest.raises(ValueError, match="manager_count must be >= 1"):
            ghost_teams_needed(0)

    def test_negative_managers_raises(self) -> None:
        with pytest.raises(ValueError, match="manager_count must be >= 1"):
            ghost_teams_needed(-1)