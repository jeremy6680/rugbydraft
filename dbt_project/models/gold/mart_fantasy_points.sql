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
--   → players (uuid → external_id)                          [D-031]
--   → pipeline_stg_match_stats (player_external_id)
--   → pipeline_stg_matches (match_external_id → kickoff_utc)
--   → competition_rounds (round_id resolution)
--
-- Key rules (CDC section 10 + D-039):
--   - Kicker-only stats multiplied by is_kicker::int (0 or 1)
--   - Double match same round: only first match (earliest kickoff_utc) scores
--   - Captain: CEIL(raw * 1.5 * 2) / 2.0  → rounds UP to nearest 0.5
--   - COALESCE on all conditional stats — safe for missing provider data
--   - tries, yellow_cards, red_cards: resolved by the DSG connector and
--     stored flat in pipeline_stg_match_stats (no separate event tables)
--   - penalties_made = goals - conversion_goals (DSG field semantics)
--
-- Conditional stats (COALESCE to 0 if absent from API response):
--   line_breaks, catch_from_kick, lineouts_won, lineouts_lost,
--   kick_assists, handling_errors, turnovers_conceded
--
-- Scoring system: v2 — see DECISIONS.md D-039
-- Materialized as: table (target: prod)
-- =============================================================================

{{
    config(
        materialized='table',
        description='Fantasy points per starter per round. Captain x1.5, '
                    'kicker-only stats, double-match dedup (CDC 6.6). '
                    'Scoring system v2 — D-039.'
    )
}}

-- ---------------------------------------------------------------------------
-- Step 1: resolve player external_id → UUID from PostgreSQL players table.
-- Bridge between silver (external IDs) and PG (UUIDs) — D-031.
-- ---------------------------------------------------------------------------
with player_id_map as (

    select
        p.id            as player_uuid,
        p.external_id   as player_external_id
    from {{ source('postgres', 'players') }} p
    where p.external_id is not null

),

-- ---------------------------------------------------------------------------
-- Step 2: resolve match external_id → round_id via real_matches.
-- kickoff_utc is used for double-match deduplication ordering.
-- ---------------------------------------------------------------------------
match_round_map as (

    select
        rm.external_id          as match_external_id,
        rm.id                   as match_uuid,
        rm.competition_round_id as round_id,
        cr.round_number,
        sm.kickoff_utc
    from {{ source('postgres', 'real_matches') }} rm
    inner join {{ source('postgres', 'competition_rounds') }} cr
        on cr.id = rm.competition_round_id
    inner join {{ source('postgres', 'pipeline_stg_matches') }} sm
        on sm.match_external_id = rm.external_id
    where rm.external_id is not null

),

-- ---------------------------------------------------------------------------
-- Step 3: join match stats with resolved IDs.
-- tries, yellow_cards, red_cards come flat from pipeline_stg_match_stats —
-- the DSG connector resolves them from scores/bookings event nodes before
-- writing to data/raw/player_stats.json (see connectors/base.py D-039).
-- is_first_match_of_round is pre-computed in silver (CDC 6.6).
-- penalties_made = goals - conversion_goals (DSG field semantics).
-- ---------------------------------------------------------------------------
resolved_stats as (

    select
        pid.player_uuid,
        mrm.round_id,
        mrm.match_uuid,
        mrm.kickoff_utc,
        ms.is_first_match_of_round,

        -- Attack
        coalesce(ms.tries, 0)                           as tries,
        coalesce(ms.metres_carried, 0)                  as metres_carried,
        coalesce(ms.try_assists, 0)                     as try_assists,
        coalesce(ms.kick_assists, 0)                    as kick_assists,
        -- Conditional attack stats
        coalesce(ms.line_breaks, 0)                     as line_breaks,
        coalesce(ms.catch_from_kick, 0)                 as catch_from_kick,
        -- Kicker stats: delivered directly by connector (DSG derives
        -- penalties_made = goals - conversion_goals before writing JSON)
        coalesce(ms.conversions_made, 0)                as conversions_made,
        coalesce(ms.penalties_made, 0)                  as penalties_made,

        -- Defence
        coalesce(ms.tackles, 0)                         as tackles,
        coalesce(ms.turnovers_won, 0)                   as turnovers_won,
        -- Conditional defence stats
        coalesce(ms.lineouts_won, 0)                    as lineouts_won,
        coalesce(ms.lineouts_lost, 0)                   as lineouts_lost,
        coalesce(ms.turnovers_conceded, 0)              as turnovers_conceded,
        coalesce(ms.missed_tackles, 0)                  as missed_tackles,
        coalesce(ms.handling_errors, 0)                 as handling_errors,
        coalesce(ms.penalties_conceded, 0)              as penalties_conceded,
        -- Cards resolved by connector — stored flat in pipeline_stg_match_stats
        coalesce(ms.yellow_cards, 0)                    as yellow_cards,
        coalesce(ms.red_cards, 0)                       as red_cards,
        -- D-050: new scoring fields
        coalesce(ms.off_loads, 0)                       as off_loads,
        coalesce(ms.missed_conversion_goals, 0)         as missed_conversion_goals,
        coalesce(ms.missed_penalty_goals, 0)            as missed_penalty_goals

    from {{ source('postgres', 'pipeline_stg_match_stats') }} ms
    inner join player_id_map pid
        on pid.player_external_id = ms.player_external_id
    inner join match_round_map mrm
        on mrm.match_external_id = ms.match_external_id

    -- Only keep first match per player per round (CDC 6.6 double-match rule).
    where ms.is_first_match_of_round = true

),

-- ---------------------------------------------------------------------------
-- Step 4: join with weekly_lineups to get starter/captain/kicker context.
-- Only starters score (slot_type = 'starter'). bench and ir excluded.
-- Left join: starters with no match still appear with 0 points (bye week).
-- ---------------------------------------------------------------------------
lineup_stats as (

    select
        wl.roster_id,
        wl.round_id,
        wl.player_id                                    as player_uuid,
        wl.is_captain,
        wl.is_kicker,
        wl.is_kicker::integer                           as kicker_flag,
        rs.match_uuid,

        coalesce(rs.tries, 0)                           as tries,
        coalesce(rs.metres_carried, 0)                  as metres_carried,
        coalesce(rs.try_assists, 0)                     as try_assists,
        coalesce(rs.kick_assists, 0)                    as kick_assists,
        coalesce(rs.line_breaks, 0)                     as line_breaks,
        coalesce(rs.catch_from_kick, 0)                 as catch_from_kick,
        coalesce(rs.conversions_made, 0)                as conversions_made,
        coalesce(rs.penalties_made, 0)                  as penalties_made,
        coalesce(rs.tackles, 0)                         as tackles,
        coalesce(rs.turnovers_won, 0)                   as turnovers_won,
        coalesce(rs.lineouts_won, 0)                    as lineouts_won,
        coalesce(rs.lineouts_lost, 0)                   as lineouts_lost,
        coalesce(rs.turnovers_conceded, 0)              as turnovers_conceded,
        coalesce(rs.missed_tackles, 0)                  as missed_tackles,
        coalesce(rs.handling_errors, 0)                 as handling_errors,
        coalesce(rs.penalties_conceded, 0)              as penalties_conceded,
        coalesce(rs.yellow_cards, 0)                    as yellow_cards,
        coalesce(rs.red_cards, 0)                       as red_cards,
        -- D-050: new scoring fields
        coalesce(rs.off_loads, 0)                       as off_loads,
        coalesce(rs.missed_conversion_goals, 0)         as missed_conversion_goals,
        coalesce(rs.missed_penalty_goals, 0)            as missed_penalty_goals

    from {{ source('postgres', 'weekly_lineups') }} wl
    left join resolved_stats rs
        on rs.player_uuid = wl.player_id
        and rs.round_id   = wl.round_id
    where wl.slot_type = 'starter'

),

-- ---------------------------------------------------------------------------
-- Step 5: calculate individual point components per scoring action (D-039).
-- ---------------------------------------------------------------------------
point_components as (

    select
        ls.roster_id,
        ls.round_id,
        ls.player_uuid,
        ls.is_captain,
        ls.is_kicker,
        ls.match_uuid,

        -- Attack (D-039)
        round(ls.metres_carried * 0.1, 2)               as metres_pts,
        ls.tries              * 5.0                     as try_pts,
        ls.try_assists        * 2.0                     as try_assist_pts,
        ls.turnovers_won      * 2.0                     as turnover_won_pts,
        ls.line_breaks        * 1.0                     as line_break_pts,
        ls.kick_assists       * 1.0                     as kick_assist_pts,
        ls.catch_from_kick    * 0.5                     as catch_from_kick_pts,
        -- Kicker-only: multiplied by kicker_flag (1 for kicker, 0 for others)
        ls.conversions_made   * ls.kicker_flag * 2.0    as conversion_made_pts,
        ls.penalties_made     * ls.kicker_flag * 3.0    as penalty_made_pts,

        -- Defence (D-039)
        ls.tackles            * 0.5                     as tackle_pts,
        ls.lineouts_won       * 1.0                     as lineout_won_pts,
        ls.lineouts_lost      * (-0.5)                  as lineout_lost_pts,
        ls.turnovers_conceded * (-0.5)                  as turnover_conceded_pts,
        ls.missed_tackles     * (-0.5)                  as missed_tackle_pts,
        ls.handling_errors    * (-0.5)                  as handling_error_pts,
        ls.penalties_conceded * (-1.0)                  as penalty_conceded_pts,
        ls.yellow_cards       * (-2.0)                  as yellow_card_pts,
        ls.red_cards          * (-3.0)                  as red_card_pts,
        -- D-050: off_loads — all players, +1 pt each
        ls.off_loads          * 1.0                     as off_load_pts,
        -- D-050: missed kicks — kicker only (kicker_flag = 0 or 1)
        ls.missed_conversion_goals * ls.kicker_flag * (-0.5) as missed_conversion_pts,
        ls.missed_penalty_goals    * ls.kicker_flag * (-1.0) as missed_penalty_pts

    from lineup_stats ls

),

-- ---------------------------------------------------------------------------
-- Step 6: sum components, apply captain multiplier.
-- Captain formula (CDC 10.3 + D-039):
--   CEIL(raw_points * 1.5 * 2) / 2.0  → rounds UP to nearest 0.5
-- ---------------------------------------------------------------------------
scored as (

    select
        pc.*,
        (
            pc.metres_pts
            + pc.try_pts
            + pc.try_assist_pts
            + pc.turnover_won_pts
            + pc.line_break_pts
            + pc.kick_assist_pts
            + pc.catch_from_kick_pts
            + pc.conversion_made_pts
            + pc.penalty_made_pts
            + pc.tackle_pts
            + pc.lineout_won_pts
            + pc.lineout_lost_pts
            + pc.turnover_conceded_pts
            + pc.missed_tackle_pts
            + pc.handling_error_pts
            + pc.penalty_conceded_pts
            + pc.yellow_card_pts
            + pc.red_card_pts
            + pc.off_load_pts
            + pc.missed_conversion_pts
            + pc.missed_penalty_pts
        )::numeric(8, 2)                                as raw_points

),

final_scores as (

    select
        s.roster_id,
        s.round_id,
        s.player_uuid                                   as player_id,
        s.is_captain,
        s.is_kicker,
        s.match_uuid                                    as match_id,
        s.raw_points,

        case when s.is_captain then 1.5 else 1.0
        end::numeric(3, 2)                              as captain_multiplier,

        case
            when s.is_captain
                then ceil(s.raw_points * 1.5 * 2) / 2.0
            else s.raw_points
        end::numeric(8, 2)                              as total_points,

        -- Breakdown columns (used to build points_breakdown JSONB in fantasy_scores)
        s.metres_pts,
        s.try_pts,
        s.try_assist_pts,
        s.turnover_won_pts,
        s.line_break_pts,
        s.kick_assist_pts,
        s.catch_from_kick_pts,
        s.conversion_made_pts,
        s.penalty_made_pts,
        s.tackle_pts,
        s.lineout_won_pts,
        s.lineout_lost_pts,
        s.turnover_conceded_pts,
        s.missed_tackle_pts,
        s.handling_error_pts,
        s.penalty_conceded_pts,
        s.yellow_card_pts,
        s.red_card_pts,
        -- D-050
        s.off_load_pts,
        s.missed_conversion_pts,
        s.missed_penalty_pts

    from scored s

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
    try_pts,
    try_assist_pts,
    turnover_won_pts,
    line_break_pts,
    kick_assist_pts,
    catch_from_kick_pts,
    conversion_made_pts,
    penalty_made_pts,
    tackle_pts,
    lineout_won_pts,
    lineout_lost_pts,
    turnover_conceded_pts,
    missed_tackle_pts,
    handling_error_pts,
    penalty_conceded_pts,
    yellow_card_pts,
    red_card_pts,
    -- D-050
    off_load_pts,
    missed_conversion_pts,
    missed_penalty_pts

from final_scores