-- =============================================================================
-- mart_fantasy_points
-- =============================================================================
-- Gold model. One row per starter per round per roster.
--
-- Calculates fantasy points for every starter in weekly_lineups based on
-- real match stats from pipeline_stg_match_stats (silver exported to PG).
--
-- Join chain:
--   weekly_lineups (roster_id, player_id, round_id)
--   → players (uuid → external_id)              [D-031]
--   → pipeline_stg_match_stats (player_external_id)
--   → pipeline_stg_matches (match_external_id → kickoff_utc, round dedup)
--   → competition_rounds (round_id resolution)
--
-- Key rules (CDC section 10):
--   - Kicker-only stats multiplied by is_kicker::int (0 or 1)
--   - Double match same round: only first match (earliest kickoff_utc) scores
--   - Captain: CEIL(raw * 1.5 * 2) / 2.0  → rounds UP to nearest 0.5
--   - COALESCE on all stats — safe for missing provider data
--
-- Silver column names (actual, from DESCRIBE):
--   match_external_id, player_external_id, metres_carried, fifty_twentytwo,
--   turnovers_won, penalties_conceded, is_first_match_of_round
--
-- Materialized as: table (target: prod)
-- =============================================================================

{{
    config(
        materialized='table',
        description='Fantasy points per starter per round. Captain x1.5, '
                    'kicker-only stats, double-match dedup (CDC 6.6).'
    )
}}

-- Step 1: resolve player external_id → UUID from PostgreSQL players table.
-- This is the bridge between silver (external IDs) and PG (UUIDs) — D-031.
with player_id_map as (

    select
        p.id            as player_uuid,
        p.external_id   as player_external_id
    from {{ source('postgres', 'players') }} p
    where p.external_id is not null

),

-- Step 2: resolve match external_id → round_id via real_matches + competition_rounds.
match_round_map as (

    select
        rm.external_id          as match_external_id,
        rm.id                   as match_uuid,
        rm.competition_round_id as round_id,
        cr.round_number,
        -- kickoff_utc comes from the silver pipeline_stg_matches export.
        -- We need it here for double-match deduplication ordering.
        sm.kickoff_utc
    from {{ source('postgres', 'real_matches') }} rm
    inner join {{ source('postgres', 'competition_rounds') }} cr
        on cr.id = rm.competition_round_id
    inner join {{ source('postgres', 'pipeline_stg_matches') }} sm
        on sm.match_external_id = rm.external_id
    where rm.external_id is not null

),

-- Step 3: join match stats with resolved IDs.
-- is_first_match_of_round is pre-computed in the silver model — use it
-- directly instead of recomputing ROW_NUMBER here.
resolved_stats as (

    select
        pid.player_uuid,
        mrm.round_id,
        mrm.match_uuid,
        mrm.kickoff_utc,
        ms.is_first_match_of_round,

        -- Attack stats
        coalesce(ms.tries, 0)               as tries,
        coalesce(ms.metres_carried, 0)      as metres_carried,
        coalesce(ms.offloads, 0)            as offloads,
        coalesce(ms.try_assists, 0)         as try_assists,
        coalesce(ms.drop_goals, 0)          as drop_goals,
        coalesce(ms.conversions_made, 0)    as conversions_made,
        coalesce(ms.conversions_missed, 0)  as conversions_missed,
        coalesce(ms.penalties_made, 0)      as penalties_made,
        coalesce(ms.penalties_missed, 0)    as penalties_missed,
        -- fifty_twentytwo: column name in silver (no underscore between 20 and 22)
        coalesce(ms.fifty_twentytwo, 0)     as fifty_twentytwo,

        -- Defence stats
        coalesce(ms.tackles, 0)             as tackles,
        coalesce(ms.dominant_tackles, 0)    as dominant_tackles,
        coalesce(ms.turnovers_won, 0)       as turnovers_won,
        coalesce(ms.lineout_steals, 0)      as lineout_steals,
        coalesce(ms.penalties_conceded, 0)  as penalties_conceded,
        coalesce(ms.yellow_cards, 0)        as yellow_cards,
        coalesce(ms.red_cards, 0)           as red_cards

    from {{ source('postgres', 'pipeline_stg_match_stats') }} ms
    inner join player_id_map pid
        on pid.player_external_id = ms.player_external_id
    inner join match_round_map mrm
        on mrm.match_external_id = ms.match_external_id

    -- Only keep first match per player per round (CDC 6.6 double-match rule).
    -- is_first_match_of_round is set by the silver model using ROW_NUMBER
    -- partitioned by (player_external_id, round_number) ordered by kickoff_utc.
    where ms.is_first_match_of_round = true

),

-- Step 4: join with weekly_lineups to get starter/captain/kicker context.
-- Only starters score (slot_type = 'starter'). bench and ir excluded.
lineup_stats as (

    select
        wl.roster_id,
        wl.round_id,
        wl.player_id                        as player_uuid,
        wl.is_captain,
        wl.is_kicker,
        wl.is_kicker::integer               as kicker_flag,

        -- Stats are NULL if the player had no match this round (bye week).
        -- All COALESCE below guard against this.
        rs.match_uuid,
        coalesce(rs.tries, 0)               as tries,
        coalesce(rs.metres_carried, 0)      as metres_carried,
        coalesce(rs.offloads, 0)            as offloads,
        coalesce(rs.try_assists, 0)         as try_assists,
        coalesce(rs.drop_goals, 0)          as drop_goals,
        coalesce(rs.conversions_made, 0)    as conversions_made,
        coalesce(rs.conversions_missed, 0)  as conversions_missed,
        coalesce(rs.penalties_made, 0)      as penalties_made,
        coalesce(rs.penalties_missed, 0)    as penalties_missed,
        coalesce(rs.fifty_twentytwo, 0)     as fifty_twentytwo,
        coalesce(rs.tackles, 0)             as tackles,
        coalesce(rs.dominant_tackles, 0)    as dominant_tackles,
        coalesce(rs.turnovers_won, 0)       as turnovers_won,
        coalesce(rs.lineout_steals, 0)      as lineout_steals,
        coalesce(rs.penalties_conceded, 0)  as penalties_conceded,
        coalesce(rs.yellow_cards, 0)        as yellow_cards,
        coalesce(rs.red_cards, 0)           as red_cards

    from {{ source('postgres', 'weekly_lineups') }} wl

    -- Left join: starters with no match still appear with 0 points (bye week).
    left join resolved_stats rs
        on rs.player_uuid = wl.player_id
        and rs.round_id   = wl.round_id

    -- Only starters score fantasy points (CDC 6.5).
    where wl.slot_type = 'starter'

),

-- Step 5: calculate individual point components per scoring action.
point_components as (

    select
        ls.roster_id,
        ls.round_id,
        ls.player_uuid,
        ls.is_captain,
        ls.is_kicker,
        ls.match_uuid,

        -- Attack (CDC 10.1)
        round(ls.metres_carried * 0.1, 2)              as metres_pts,
        ls.offloads           * 1.0                    as offload_pts,
        ls.try_assists        * 2.0                    as try_assist_pts,
        ls.tries              * 5.0                    as try_pts,
        ls.drop_goals         * 3.0                    as drop_goal_pts,
        -- Kicker-only: multiply by kicker_flag (1 for kicker, 0 for others)
        ls.conversions_made   * ls.kicker_flag * 2.0   as conversion_made_pts,
        ls.conversions_missed * ls.kicker_flag * (-0.5) as conversion_missed_pts,
        ls.penalties_made     * ls.kicker_flag * 3.0   as penalty_made_pts,
        ls.penalties_missed   * ls.kicker_flag * (-1.0) as penalty_missed_pts,
        -- Conditional: 0 if provider does not supply this stat
        ls.fifty_twentytwo    * 2.0                    as fifty_twenty_pts,

        -- Defence (CDC 10.2)
        ls.tackles            * 0.5                    as tackle_pts,
        ls.dominant_tackles   * 1.0                    as dominant_tackle_pts,
        ls.turnovers_won      * 2.0                    as turnover_pts,
        ls.lineout_steals     * 2.0                    as lineout_steal_pts,
        ls.penalties_conceded * (-1.0)                 as penalty_conceded_pts,
        ls.yellow_cards       * (-2.0)                 as yellow_card_pts,
        ls.red_cards          * (-3.0)                 as red_card_pts

    from lineup_stats ls

),

-- Step 6: sum components, apply captain multiplier.
-- Captain formula (CDC 10.3): CEIL(raw * 1.5 * 2) / 2.0 → nearest 0.5 UP.
final_scores as (

    select
        pc.roster_id,
        pc.round_id,
        pc.player_uuid                              as player_id,
        pc.is_captain,
        pc.is_kicker,
        pc.match_uuid                               as match_id,

        -- Raw points: sum of all components
        (
            pc.metres_pts + pc.offload_pts + pc.try_assist_pts
            + pc.try_pts + pc.drop_goal_pts
            + pc.conversion_made_pts + pc.conversion_missed_pts
            + pc.penalty_made_pts + pc.penalty_missed_pts
            + pc.fifty_twenty_pts
            + pc.tackle_pts + pc.dominant_tackle_pts
            + pc.turnover_pts + pc.lineout_steal_pts
            + pc.penalty_conceded_pts
            + pc.yellow_card_pts + pc.red_card_pts
        )::numeric(8, 2)                            as raw_points,

        -- Captain multiplier stored for audit trail
        case when pc.is_captain then 1.5 else 1.0
        end::numeric(3, 2)                          as captain_multiplier,

        -- Total points with captain rounding
        case
            when pc.is_captain then
                ceil((
                    pc.metres_pts + pc.offload_pts + pc.try_assist_pts
                    + pc.try_pts + pc.drop_goal_pts
                    + pc.conversion_made_pts + pc.conversion_missed_pts
                    + pc.penalty_made_pts + pc.penalty_missed_pts
                    + pc.fifty_twenty_pts
                    + pc.tackle_pts + pc.dominant_tackle_pts
                    + pc.turnover_pts + pc.lineout_steal_pts
                    + pc.penalty_conceded_pts
                    + pc.yellow_card_pts + pc.red_card_pts
                ) * 1.5 * 2) / 2.0
            else (
                    pc.metres_pts + pc.offload_pts + pc.try_assist_pts
                    + pc.try_pts + pc.drop_goal_pts
                    + pc.conversion_made_pts + pc.conversion_missed_pts
                    + pc.penalty_made_pts + pc.penalty_missed_pts
                    + pc.fifty_twenty_pts
                    + pc.tackle_pts + pc.dominant_tackle_pts
                    + pc.turnover_pts + pc.lineout_steal_pts
                    + pc.penalty_conceded_pts
                    + pc.yellow_card_pts + pc.red_card_pts
            )
        end::numeric(8, 2)                          as total_points,

        -- Breakdown columns (for points_breakdown JSONB in fantasy_scores)
        pc.metres_pts,
        pc.offload_pts,
        pc.try_assist_pts,
        pc.try_pts,
        pc.drop_goal_pts,
        pc.conversion_made_pts,
        pc.conversion_missed_pts,
        pc.penalty_made_pts,
        pc.penalty_missed_pts,
        pc.fifty_twenty_pts,
        pc.tackle_pts,
        pc.dominant_tackle_pts,
        pc.turnover_pts,
        pc.lineout_steal_pts,
        pc.penalty_conceded_pts,
        pc.yellow_card_pts,
        pc.red_card_pts

    from point_components pc

)

select
    {{ dbt_utils.generate_surrogate_key(['roster_id', 'round_id', 'player_id']) }}
                        as fantasy_score_id,
    roster_id,
    round_id,
    player_id,
    is_captain,
    is_kicker,
    match_id,
    raw_points,
    captain_multiplier,
    total_points,
    metres_pts,
    offload_pts,
    try_assist_pts,
    try_pts,
    drop_goal_pts,
    conversion_made_pts,
    conversion_missed_pts,
    penalty_made_pts,
    penalty_missed_pts,
    fifty_twenty_pts,
    tackle_pts,
    dominant_tackle_pts,
    turnover_pts,
    lineout_steal_pts,
    penalty_conceded_pts,
    yellow_card_pts,
    red_card_pts

from final_scores