-- =============================================================================
-- mart_roster_scores
-- =============================================================================
-- Gold model. One row per roster per round.
--
-- Aggregates total fantasy points for each roster in a given round.
-- This is the "score" that appears on the weekly matchup result screen.
--
-- Score = sum of total_points for all starters (15 players).
-- Bench and IR players are excluded (already excluded in mart_fantasy_points).
--
-- Dependencies:
--   - mart_fantasy_points  (one row per starter per round per roster)
--
-- Materialized as: table
-- =============================================================================

{{
    config(
        materialized='table',
        description='Total fantasy points per roster per round. '
                    'Aggregates mart_fantasy_points starters only.'
    )
}}

select
    {{ dbt_utils.generate_surrogate_key(['roster_id', 'round_id']) }}
                                as roster_score_id,

    roster_id,
    round_id,

    -- Total points for this roster this round (sum of all 15 starters).
    -- Returns 0 if no starters have been scored yet (pipeline not run yet).
    coalesce(
        sum(total_points), 0
    )::numeric(8, 2)            as round_total_points,

    -- Count of starters who actually played a match this round.
    -- Useful to detect incomplete scoring (e.g. bye week, postponed matches).
    count(match_id)             as starters_with_match,

    -- Total starters in the lineup (should always be 15 for a complete roster).
    count(*)                    as total_starters,

    -- Flag: TRUE if all starters had a match this round.
    -- FALSE if some players had a bye or their match has not been played yet.
    (count(match_id) = count(*)) as all_starters_scored

from {{ ref('mart_fantasy_points') }}

group by roster_id, round_id