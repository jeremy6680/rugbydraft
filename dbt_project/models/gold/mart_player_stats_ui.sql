-- =============================================================================
-- mart_player_stats_ui
-- =============================================================================
-- Gold model. One row per player per competition per period.
--
-- Powers the Stats page (CDC section 12). Provides pre-aggregated player
-- stats for four time periods: 1w, 2w, 4w, season.
--
-- The frontend filters by period on every fetch (approach D-044: period is
-- a server-side parameter; position/status/club are filtered client-side).
--
-- Stats aggregated (all actions from D-039 scoring system):
--   Attack : tries, try_assists, metres_carried, kick_assists, line_breaks,
--            catch_from_kick, conversions_made, penalties_made
--   Defence: tackles, turnovers_won, lineouts_won, lineouts_lost,
--            turnovers_conceded, missed_tackles, handling_errors,
--            penalties_conceded, yellow_cards, red_cards
--   Points : total_points (sum), avg_points (mean) — based on raw_points
--            from mart_fantasy_points (no captain multiplier applied).
--
-- Trend (CDC §12.3 "Tendance"):
--   Compares avg_points for current period vs the equivalent preceding period.
--   up     → current > prev * 1.10  (≥ 10% above)
--   down   → current < prev * 0.90  (≥ 10% below)
--   stable → otherwise (includes no data for previous period)
--
-- Periods:
--   1w     → last 1 round
--   2w     → last 2 rounds
--   4w     → last 4 rounds
--   season → all completed rounds in the competition
--
-- prev_season period: deferred — see NEXT_STEPS.md
--
-- Scoring system: v2 — see DECISIONS.md D-039
-- Materialized as: table (target: prod)
-- =============================================================================

{{
    config(
        materialized='table',
        description='Player stats aggregated by period for the Stats page. '
                    'One row per (player_id, competition_id, period). '
                    'Periods: 1w | 2w | 4w | season. '
                    'Scoring system v2 — D-039.'
    )
}}

-- ---------------------------------------------------------------------------
-- Step 1: resolve player external_id → UUID and pull base attributes.
-- ---------------------------------------------------------------------------
with player_base as (

    select
        p.id                as player_uuid,
        p.external_id       as player_external_id,
        p.nationality,
        p.club
    from {{ source('postgres', 'players') }} p
    where p.external_id is not null

),

-- ---------------------------------------------------------------------------
-- Step 2: enrich with silver player data (name, position).
-- ---------------------------------------------------------------------------
player_ref as (

    select
        pb.player_uuid,
        sp.player_name,
        sp.position_type,
        pb.nationality,
        pb.club
    from {{ source('postgres', 'pipeline_stg_players') }} sp
    inner join player_base pb
        on pb.player_external_id = sp.player_external_id

),

-- ---------------------------------------------------------------------------
-- Step 3: rank completed rounds per competition (most recent first).
-- We only aggregate stats for completed rounds (match status = finished).
-- ---------------------------------------------------------------------------
ranked_rounds as (

    select
        cr.id               as round_id,
        cr.competition_id,
        cr.round_number,
        -- Rank 1 = most recent completed round.
        row_number() over (
            partition by cr.competition_id
            order by cr.round_number desc
        )                   as recency_rank,
        -- Total rounds completed in this competition (for season period).
        count(*) over (
            partition by cr.competition_id
        )                   as total_rounds_completed

    from {{ source('postgres', 'competition_rounds') }} cr
    -- Only rounds where at least one match is finished.
    where exists (
        select 1
        from {{ source('postgres', 'real_matches') }} rm
        where rm.competition_round_id = cr.id
          and rm.status = 'finished'
    )

),

-- ---------------------------------------------------------------------------
-- Step 4: join match stats with resolved player UUIDs and round context.
-- Only first match per player per round (CDC 6.6 double-match rule).
--
-- All columns from pipeline_stg_match_stats are TEXT (export_silver_to_pg.py
-- uses TEXT for all columns to avoid dtype-mapping issues). Cast to numeric
-- here — once — so all downstream CTEs work with correct types.
--
-- raw_points from mart_fantasy_points is used for the points columns
-- (not total_points which includes the captain multiplier — this page
-- is global and captain designation is roster-specific).
-- ---------------------------------------------------------------------------
player_round_stats as (

    select
        pid.player_uuid,
        mrm.competition_id,
        mrm.round_id,
        mrm.recency_rank,
        mrm.total_rounds_completed,

        -- Attack stats (D-039)
        coalesce(ms.tries::integer,              0)  as tries,
        coalesce(ms.try_assists::integer,        0)  as try_assists,
        coalesce(ms.metres_carried::integer,     0)  as metres_carried,
        coalesce(ms.kick_assists::integer,       0)  as kick_assists,
        coalesce(ms.line_breaks::integer,        0)  as line_breaks,
        coalesce(ms.catch_from_kick::integer,    0)  as catch_from_kick,
        -- Kicker stats: shown raw for all players (no kicker_flag here)
        coalesce(ms.conversions_made::integer,   0)  as conversions_made,
        coalesce(ms.penalties_made::integer,     0)  as penalties_made,

        -- Defence stats (D-039)
        coalesce(ms.tackles::integer,            0)  as tackles,
        coalesce(ms.turnovers_won::integer,      0)  as turnovers_won,
        coalesce(ms.lineouts_won::integer,       0)  as lineouts_won,
        coalesce(ms.lineouts_lost::integer,      0)  as lineouts_lost,
        coalesce(ms.turnovers_conceded::integer, 0)  as turnovers_conceded,
        coalesce(ms.missed_tackles::integer,     0)  as missed_tackles,
        coalesce(ms.handling_errors::integer,    0)  as handling_errors,
        coalesce(ms.penalties_conceded::integer, 0)  as penalties_conceded,
        coalesce(ms.yellow_cards::integer,       0)  as yellow_cards,
        coalesce(ms.red_cards::integer,          0)  as red_cards,

        -- Fantasy points — raw_points (no captain multiplier) for global page
        coalesce(fp.raw_points, 0)                   as fantasy_points

    from {{ source('postgres', 'pipeline_stg_match_stats') }} ms
    inner join player_base pid
        on pid.player_external_id = ms.player_external_id
    inner join {{ source('postgres', 'real_matches') }} rm
        on rm.external_id = ms.match_external_id
    inner join ranked_rounds mrm
        on mrm.round_id = rm.competition_round_id
    left join {{ ref('mart_fantasy_points') }} fp
        on fp.player_id = pid.player_uuid
        and fp.match_id = rm.id
    -- is_first_match_of_round is TEXT 'true'/'false' after export
    where ms.is_first_match_of_round = 'true'

),

-- ---------------------------------------------------------------------------
-- Step 5: expand rows into four periods using CROSS JOIN with a period table.
-- Each period defines how many recency_rank rounds to include.
-- ---------------------------------------------------------------------------
periods as (

    select '1w'     as period, 1    as max_rank, 1    as prev_max_rank, 1   as prev_min_rank
    union all
    select '2w'     as period, 2    as max_rank, 2    as prev_max_rank, 3   as prev_min_rank
    union all
    select '4w'     as period, 4    as max_rank, 4    as prev_max_rank, 5   as prev_min_rank
    union all
    -- Season: use total_rounds_completed as the upper bound.
    -- prev period is undefined for season — trend is always 'stable'.
    select 'season' as period, 9999 as max_rank, 0    as prev_max_rank, 0   as prev_min_rank

),

-- ---------------------------------------------------------------------------
-- Step 6: aggregate current period stats per (player, competition, period).
-- total_points = sum of raw fantasy points over the period.
-- avg_points   = mean of raw fantasy points over the period.
-- ---------------------------------------------------------------------------
current_period_stats as (

    select
        prs.player_uuid,
        prs.competition_id,
        p.period,
        p.max_rank,
        p.prev_max_rank,
        p.prev_min_rank,

        -- Rounds with data in this period
        count(*)                                            as rounds_played,

        -- Fantasy points
        round(sum(prs.fantasy_points)::numeric,  2)        as total_points,
        round(avg(prs.fantasy_points)::numeric,  2)        as avg_points,

        -- Attack totals (D-039)
        sum(prs.tries)::integer                            as tries,
        sum(prs.try_assists)::integer                      as try_assists,
        sum(prs.metres_carried)::integer                   as metres_carried,
        sum(prs.kick_assists)::integer                     as kick_assists,
        sum(prs.line_breaks)::integer                      as line_breaks,
        sum(prs.catch_from_kick)::integer                  as catch_from_kick,
        -- Kicker stats (raw — kicker_flag not applied here)
        sum(prs.conversions_made)::integer                 as conversions_made,
        sum(prs.penalties_made)::integer                   as penalties_made,

        -- Defence totals (D-039)
        sum(prs.tackles)::integer                          as tackles,
        sum(prs.turnovers_won)::integer                    as turnovers_won,
        sum(prs.lineouts_won)::integer                     as lineouts_won,
        sum(prs.lineouts_lost)::integer                    as lineouts_lost,
        sum(prs.turnovers_conceded)::integer               as turnovers_conceded,
        sum(prs.missed_tackles)::integer                   as missed_tackles,
        sum(prs.handling_errors)::integer                  as handling_errors,
        sum(prs.penalties_conceded)::integer               as penalties_conceded,
        sum(prs.yellow_cards)::integer                     as yellow_cards,
        sum(prs.red_cards)::integer                        as red_cards

    from player_round_stats prs
    cross join periods p
    -- Filter to rounds within the current period window.
    -- season: max_rank = 9999 captures all completed rounds.
    where prs.recency_rank <= p.max_rank

    group by
        prs.player_uuid,
        prs.competition_id,
        p.period,
        p.max_rank,
        p.prev_max_rank,
        p.prev_min_rank

),

-- ---------------------------------------------------------------------------
-- Step 7: aggregate previous period avg_points for trend calculation.
-- Previous period = same duration, immediately before the current window.
-- Example: for 4w, prev = rounds with recency_rank 5–8.
-- Season has no previous period — trend is always 'stable'.
-- ---------------------------------------------------------------------------
prev_period_stats as (

    select
        prs.player_uuid,
        prs.competition_id,
        p.period,
        round(
            avg(prs.fantasy_points)::numeric, 2
        )                                               as prev_avg_points

    from player_round_stats prs
    cross join periods p
    -- Previous window: ranks between prev_min_rank and prev_max_rank.
    -- prev_max_rank = 0 for season → this CTE returns nothing for season.
    where p.prev_max_rank > 0
      and prs.recency_rank between p.prev_min_rank and p.prev_max_rank

    group by
        prs.player_uuid,
        prs.competition_id,
        p.period

),

-- ---------------------------------------------------------------------------
-- Step 8: availability per player (for availability_status in the stats page).
-- ---------------------------------------------------------------------------
player_availability as (

    select
        pid.player_uuid,
        pa.availability_status
    from {{ source('postgres', 'pipeline_stg_player_availability') }} pa
    inner join player_base pid
        on pid.player_external_id = pa.player_external_id

),

-- ---------------------------------------------------------------------------
-- Step 9: assemble final output with trend calculation.
-- ---------------------------------------------------------------------------
final as (

    select
        cp.player_uuid          as player_id,
        cp.competition_id,
        cp.period,
        pr.player_name,
        pr.position_type,
        pr.nationality,
        pr.club,

        -- Availability (null → no data from provider → treat as available)
        coalesce(
            av.availability_status, 'available'
        )                       as availability_status,

        cp.rounds_played,

        -- Fantasy points
        cp.total_points,
        cp.avg_points,

        -- Attack (D-039)
        cp.tries,
        cp.try_assists,
        cp.metres_carried,
        cp.kick_assists,
        cp.line_breaks,
        cp.catch_from_kick,
        cp.conversions_made,
        cp.penalties_made,

        -- Defence (D-039)
        cp.tackles,
        cp.turnovers_won,
        cp.lineouts_won,
        cp.lineouts_lost,
        cp.turnovers_conceded,
        cp.missed_tackles,
        cp.handling_errors,
        cp.penalties_conceded,
        cp.yellow_cards,
        cp.red_cards,

        -- Trend: compare avg_points vs previous period of same duration.
        -- season: no previous period → always 'stable'.
        -- If previous period has no data → 'stable'.
        case
            when cp.period = 'season'
                then 'stable'
            when pp.prev_avg_points is null
                then 'stable'
            when pp.prev_avg_points = 0
                then case
                    when cp.avg_points > 0 then 'up'
                    else 'stable'
                end
            when cp.avg_points > pp.prev_avg_points * 1.10
                then 'up'
            when cp.avg_points < pp.prev_avg_points * 0.90
                then 'down'
            else 'stable'
        end                     as trend

    from current_period_stats cp
    inner join player_ref pr
        on pr.player_uuid = cp.player_uuid
    left join prev_period_stats pp
        on pp.player_uuid    = cp.player_uuid
        and pp.competition_id = cp.competition_id
        and pp.period         = cp.period
    left join player_availability av
        on av.player_uuid = cp.player_uuid

)

select
    {{ dbt_utils.generate_surrogate_key(['player_id', 'competition_id', 'period']) }}
                                as player_stats_ui_id,
    player_id,
    competition_id,
    period,
    player_name,
    position_type,
    nationality,
    club,
    availability_status,
    rounds_played,

    -- Fantasy points
    total_points,
    avg_points,

    -- Attack (D-039)
    tries,
    try_assists,
    metres_carried,
    kick_assists,
    line_breaks,
    catch_from_kick,
    conversions_made,
    penalties_made,

    -- Defence (D-039)
    tackles,
    turnovers_won,
    lineouts_won,
    lineouts_lost,
    turnovers_conceded,
    missed_tackles,
    handling_errors,
    penalties_conceded,
    yellow_cards,
    red_cards,

    trend

from final

order by competition_id, period, avg_points desc