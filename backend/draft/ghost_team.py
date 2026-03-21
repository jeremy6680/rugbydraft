"""Ghost team generation for RugbyDraft.

A ghost team is a computer-managed team that fills the bracket when the
number of human managers is odd or below the competition minimum.

This module is intentionally pure: no I/O, no global state.
The DraftEngine is the caller — this module never imports from engine.py.

CDC reference: section 11.
"""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Prefix that identifies a ghost team manager ID throughout the codebase.
# Convention: ghost-<uuid4>. Never collides with Supabase Auth UUIDs.
GHOST_ID_PREFIX = "ghost-"

# Rugby cities used to generate ghost team names.
# Deliberately international — reflects the Six Nations / Top 14 context.
_GHOST_CITIES: list[str] = [
    "Cardiff",
    "Dublin",
    "Édimbourg",
    "Rome",
    "Twickenham",
    "Paris",
    "Toulouse",
    "Bordeaux",
    "Clermont",
    "Lyon",
    "Toulon",
    "La Rochelle",
    "Bayonne",
    "Biarritz",
    "Perpignan",
    "Limerick",
    "Belfast",
    "Glasgow",
    "Cape Town",
    "Auckland",
    "Buenos Aires",
]

# Name templates. {city} is substituted at generation time.
# Keep them evocative and rugby-flavoured.
_GHOST_NAME_TEMPLATES: list[str] = [
    "Les Fantômes de {city}",
    "Les Ombres de {city}",
    "Les Spectres de {city}",
    "Les Esprits de {city}",
    "Les Légendes de {city}",
]

# Avatar identifiers — opaque string keys resolved to URLs by the frontend.
# Format: "ghost_avatar_{n}" where n is 1-based.
# Add more entries as the design team provides new assets.
_GHOST_AVATARS: list[str] = [
    "ghost_avatar_1",
    "ghost_avatar_2",
    "ghost_avatar_3",
    "ghost_avatar_4",
    "ghost_avatar_5",
]


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GhostTeam:
    """Immutable representation of a ghost team.

    Attributes:
        manager_id: Unique identifier with GHOST_ID_PREFIX. Used as the
            manager slot in DraftEngine — treated identically to a human
            manager_id except that the engine never starts a timer for it.
        name: Display name generated from _GHOST_NAME_TEMPLATES + _GHOST_CITIES.
        avatar_id: Opaque key resolved to an image URL by the frontend.
    """

    manager_id: str
    name: str
    avatar_id: str


# ---------------------------------------------------------------------------
# Pure generation functions
# ---------------------------------------------------------------------------


def is_ghost_id(manager_id: str) -> bool:
    """Return True if manager_id belongs to a ghost team.

    This is the single source of truth for ghost detection.
    Import this function anywhere you need to branch on ghost vs human.

    Args:
        manager_id: Any manager identifier string.

    Returns:
        True if the ID starts with GHOST_ID_PREFIX, False otherwise.
    """
    return manager_id.startswith(GHOST_ID_PREFIX)


def generate_ghost_name(*, seed: int | None = None) -> str:
    """Generate a random ghost team display name.

    Args:
        seed: Optional random seed for deterministic output in tests.
            Pass None (default) in production for true randomness.

    Returns:
        A string like "Les Fantômes de Cardiff".
    """
    rng = random.Random(seed)
    template = rng.choice(_GHOST_NAME_TEMPLATES)
    city = rng.choice(_GHOST_CITIES)
    return template.format(city=city)


def generate_ghost_avatar(*, seed: int | None = None) -> str:
    """Pick a random avatar identifier from the predefined set.

    Args:
        seed: Optional random seed for deterministic output in tests.

    Returns:
        An avatar key string, e.g. "ghost_avatar_3".
    """
    rng = random.Random(seed)
    return rng.choice(_GHOST_AVATARS)


def create_ghost_teams(count: int, *, seed: int | None = None) -> list[GhostTeam]:
    """Create ``count`` ghost teams with unique IDs, names, and avatars.

    Names and avatars are drawn without replacement when possible
    (falls back to replacement if count > pool size).

    Args:
        count: Number of ghost teams to create. Must be >= 1.
        seed: Optional random seed for deterministic output in tests.
            Each ghost team uses a derived seed to stay independent.

    Returns:
        A list of ``count`` GhostTeam instances.

    Raises:
        ValueError: If count < 1.

    Example:
        >>> teams = create_ghost_teams(2, seed=42)
        >>> len(teams)
        2
        >>> all(is_ghost_id(t.manager_id) for t in teams)
        True
    """
    if count < 1:
        raise ValueError(f"count must be >= 1, got {count}")

    rng = random.Random(seed)

    # Draw city+template combinations without replacement for variety.
    # If count exceeds the number of combinations, allow repeats.
    combos = [
        template.format(city=city)
        for template in _GHOST_NAME_TEMPLATES
        for city in _GHOST_CITIES
    ]

    if count <= len(combos):
        names = rng.sample(combos, count)
    else:
        # More ghost teams than unique name combinations — extremely unlikely
        # in practice (5 templates × 21 cities = 105 combinations).
        names = [rng.choice(combos) for _ in range(count)]

    # Avatars: cycle through the pool, then repeat.
    avatars = [_GHOST_AVATARS[i % len(_GHOST_AVATARS)] for i in range(count)]
    rng.shuffle(avatars)

    teams: list[GhostTeam] = []
    for i in range(count):
        # Use uuid4 to guarantee uniqueness across league restarts.
        ghost_id = f"{GHOST_ID_PREFIX}{uuid.uuid4()}"
        teams.append(
            GhostTeam(
                manager_id=ghost_id,
                name=names[i],
                avatar_id=avatars[i],
            )
        )

    return teams


def ghost_teams_needed(manager_count: int, min_teams: int = 4) -> int:
    """Calculate how many ghost teams are needed to start a valid draft.

    Two conditions from CDC section 11:
    1. Total team count must be even (snake draft requires pairs).
    2. Total team count must be >= min_teams.

    Args:
        manager_count: Number of human managers registered for the draft.
        min_teams: Minimum total teams required by the competition.
            Defaults to 4 (CDC suggestion).

    Returns:
        Number of ghost teams to create (0 if none needed).

    Example:
        >>> ghost_teams_needed(4)   # even, meets minimum → 0
        0
        >>> ghost_teams_needed(3)   # odd → 1 ghost to reach 4 (even + min)
        1
        >>> ghost_teams_needed(1)   # 1 human → needs 3 ghosts to reach 4
        3
        >>> ghost_teams_needed(5)   # odd → 1 ghost to reach 6 (even, > min)
        1
    """
    if manager_count < 1:
        raise ValueError(f"manager_count must be >= 1, got {manager_count}")

    needed = 0

    # Condition 1: reach the minimum team count.
    if manager_count + needed < min_teams:
        needed = min_teams - manager_count

    # Condition 2: make the total even.
    if (manager_count + needed) % 2 != 0:
        needed += 1

    return needed