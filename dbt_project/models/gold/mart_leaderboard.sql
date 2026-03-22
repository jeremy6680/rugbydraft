-- =============================================================================
-- mart_leaderboard
-- =============================================================================
-- Gold model. One row per member per league.
--
-- Calculates the current standings for every league:
--   - wins / losses / draws (from league_fixtures results)
--   - total fantasy points accumulated across all rounds
--   - current rank with tiebreakers (CDC 8.4)
--
-- Tiebreaker rules (CDC 8.4):
--   1. Head-to-head result between tied managers.
--   2. Total fantasy points accumulated on the season.
--
-- This model reflects the current state at the time of the last pipeline run.
-- The production table (league_standings) is updated via the atomic commit
-- pattern in the Airflow DAG.
--
-- Dependencies:
--   - mart_roster_scores       (total points per roster per round)
--   - league_fixtures          (matchup schedule and results)
--   - league_members           (roster <-> member mapping)
--   - rosters                  (member <-> roster mapping)
--
-- Materialized as: table
-- =============================================================================

{{
    config(
        materialized='table',
        description='League standings with wins/losses, total points, rank, '
                    'and tiebreakers (CDC 8.4): head-to-head then total points.'
    )
}}

-- Step 1: resolve round scores per member (not per roster) per league.
-- We join through rosters -> league_members to get member_id and league_id.
with member_round_scores as (

    select
        lm.league_id,
        lm.id               as member_id,
        rs.round_id,
        rs.round_total_points

    from {{ ref('mart_roster_scores') }} rs
    inner join {{ source('postgres', 'rosters') }} r
        on r.id = rs.roster_id
    inner join {{ source('postgres', 'league_members') }} lm
        on lm.id = r.member_id

),

-- Step 2: calculate matchup results from league_fixtures.
-- Each row in league_fixtures is one matchup (home vs away).
-- We compare the two managers' round scores to determine win/loss/draw.
matchup_results as (

    select
        lf.league_id,
        lf.round_number,
        lf.home_member_id,
        lf.away_member_id,

        home_scores.round_total_points  as home_points,
        away_scores.round_total_points  as away_points,

        -- Win/loss/draw determination.
        case
            when home_scores.round_total_points > away_scores.round_total_points
                then 'home_win'
            when home_scores.round_total_points < away_scores.round_total_points
                then 'away_win'
            when home_scores.round_total_points = away_scores.round_total_points
                and home_scores.round_total_points is not null
                then 'draw'
            else 'not_played'  -- scores not yet available for this round
        end as result

    from {{ source('postgres', 'league_fixtures') }} lf

    -- Join home member's score for this round.
    left join member_round_scores home_scores
        on home_scores.league_id = lf.league_id
        and home_scores.member_id = lf.home_member_id
        and home_scores.round_id = (
            -- Resolve round_id from round_number within the league's competition.
            select cr.id
            from {{ source('postgres', 'competition_rounds') }} cr
            inner join {{ source('postgres', 'leagues') }} l
                on l.competition_id = cr.competition_id
            where l.id = lf.league_id
              and cr.round_number = lf.round_number
            limit 1
        )

    -- Join away member's score for this round.
    left join member_round_scores away_scores
        on away_scores.league_id = lf.league_id
        and away_scores.member_id = lf.away_member_id
        and away_scores.round_id = (
            select cr.id
            from {{ source('postgres', 'competition_rounds') }} cr
            inner join {{ source('postgres', 'leagues') }} l
                on l.competition_id = cr.competition_id
            where l.id = lf.league_id
              and cr.round_number = lf.round_number
            limit 1
        )

    -- Only consider played rounds (not future fixtures).
    where lf.round_number <= (
        select max(cr2.round_number)
        from {{ source('postgres', 'competition_rounds') }} cr2
        inner join {{ source('postgres', 'leagues') }} l2
            on l2.competition_id = cr2.competition_id
        inner join {{ source('postgres', 'real_matches') }} rm
            on rm.competition_round_id = cr2.id
        where l2.id = lf.league_id
          and rm.status = 'finished'
    )

),

-- Step 3: pivot matchup results into per-member win/loss/draw counts.
-- Each matchup produces two rows: one for home, one for away.
member_record as (

    -- Home manager perspective.
    select
        league_id,
        home_member_id  as member_id,
        home_points     as points_for,
        away_points     as points_against,
        case when result = 'home_win' then 1 else 0 end as win,
        case when result = 'away_win' then 1 else 0 end as loss,
        case when result = 'draw'     then 1 else 0 end as draw
    from matchup_results
    where result != 'not_played'

    union all

    -- Away manager perspective.
    select
        league_id,
        away_member_id  as member_id,
        away_points     as points_for,
        home_points     as points_against,
        case when result = 'away_win' then 1 else 0 end as win,
        case when result = 'home_win' then 1 else 0 end as loss,
        case when result = 'draw'     then 1 else 0 end as draw
    from matchup_results
    where result != 'not_played'

),

-- Step 4: aggregate per member across all rounds.
member_totals as (

    select
        league_id,
        member_id,
        sum(win)            as wins,
        sum(loss)           as losses,
        sum(draw)           as draws,
        sum(points_for)     as total_points_for,
        sum(points_against) as total_points_against
    from member_record
    group by league_id, member_id

),

-- Step 5: calculate season total points per member (for tiebreaker 2).
-- This sums ALL rounds, not just matchup rounds (same result but explicit).
season_totals as (

    select
        league_id,
        member_id,
        coalesce(sum(round_total_points), 0) as season_total_points
    from member_round_scores
    group by league_id, member_id

),

-- Step 6: ensure all league members appear in the leaderboard, even those
-- with no matches played yet (new league, round 1 not yet scored).
all_members as (

    select
        lm.league_id,
        lm.id as member_id
    from {{ source('postgres', 'league_members') }} lm

),

-- Step 7: combine totals with all members (left join ensures no member is missing).
combined as (

    select
        am.league_id,
        am.member_id,
        coalesce(mt.wins, 0)                    as wins,
        coalesce(mt.losses, 0)                  as losses,
        coalesce(mt.draws, 0)                   as draws,
        coalesce(mt.total_points_for, 0)        as total_points_for,
        coalesce(mt.total_points_against, 0)    as total_points_against,
        coalesce(st.season_total_points, 0)     as season_total_points

    from all_members am
    left join member_totals mt
        on mt.league_id = am.league_id
        and mt.member_id = am.member_id
    left join season_totals st
        on st.league_id = am.league_id
        and st.member_id = am.member_id

),

-- Step 8: rank members within each league.
-- Primary sort: wins DESC.
-- Tiebreaker 1 (CDC 8.4): head-to-head is resolved at query time by the
--   frontend (this model does not encode H2H directly -- it would require
--   a self-join per pair which is expensive and better done ad hoc).
-- Tiebreaker 2 (CDC 8.4): season_total_points DESC.
-- Note: RANK() produces gaps (e.g. 1, 2, 2, 4). DENSE_RANK() avoids gaps.
-- We use DENSE_RANK() so position numbers are contiguous (1, 2, 2, 3).
ranked as (

    select
        *,
        dense_rank() over (
            partition by league_id
            order by wins desc, season_total_points desc
        ) as rank
    from combined

)

select
    {{ dbt_utils.generate_surrogate_key(['league_id', 'member_id']) }}
                            as leaderboard_id,
    league_id,
    member_id,
    wins,
    losses,
    draws,
    total_points_for,
    total_points_against,
    season_total_points,
    rank
from ranked