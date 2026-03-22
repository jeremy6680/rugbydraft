-- =============================================================================
-- mart_player_pool
-- =============================================================================
-- Gold model. One row per player per league.
--
-- Shows availability status of every eligible player in every active league.
--
-- Join chain:
--   pipeline_stg_players (player_external_id, player_name, position_type)
--   → players (external_id → uuid)                          [D-031]
--   → roster_slots + rosters (drafted status per league)
--   → pipeline_stg_player_availability (availability_status via external_id)
--
-- Silver column names (actual):
--   stg_players:              player_external_id, player_name, position_type,
--                             team_external_id
--   stg_player_availability:  player_external_id, availability_status,
--                             return_date, suspension_matches
--                             NOTE: no competition_id — scoped by team only
--
-- Materialized as: table (target: prod)
-- =============================================================================

{{
    config(
        materialized='table',
        description='Player availability per league. '
                    'pool_status: free | drafted | injured | suspended | doubtful.'
    )
}}

-- Step 1: resolve player external_id → UUID.
with player_id_map as (

    select
        p.id            as player_uuid,
        p.external_id   as player_external_id,
        p.nationality,
        p.club
    from {{ source('postgres', 'players') }} p
    where p.external_id is not null

),

-- Step 2: enrich player data from silver (name, position).
-- Silver has the canonical player name and position from the provider.
player_data as (

    select
        pid.player_uuid,
        sp.player_name,
        sp.position_type,
        sp.team_external_id,
        pid.nationality,
        pid.club
    from {{ source('postgres', 'pipeline_stg_players') }} sp
    inner join player_id_map pid
        on pid.player_external_id = sp.player_external_id

),

-- Step 3: find all players currently on a roster in each league.
drafted_players as (

    select
        rs.player_id    as player_uuid,
        r.league_id,
        lm.id           as member_id
    from {{ source('postgres', 'roster_slots') }} rs
    inner join {{ source('postgres', 'rosters') }} r
        on r.id = rs.roster_id
    inner join {{ source('postgres', 'league_members') }} lm
        on lm.id = r.member_id

),

-- Step 4: get availability status per player from silver.
-- stg_player_availability has no competition_id — availability is global
-- per player (a player injured is injured in all competitions).
player_availability as (

    select
        pid.player_uuid,
        pa.availability_status,
        pa.return_date,
        pa.suspension_matches
    from {{ source('postgres', 'pipeline_stg_player_availability') }} pa
    inner join player_id_map pid
        on pid.player_external_id = pa.player_external_id

),

-- Step 5: cross every active league with every player who has silver data.
-- Bounded cross-join: ~500 players × ~50 leagues = manageable.
league_player_cross as (

    select
        l.id                as league_id,
        l.competition_id,
        c.type              as competition_type,        
        pd.player_uuid,
        pd.player_name,
        pd.position_type,
        pd.nationality,
        pd.club

    from {{ source('postgres', 'leagues') }} l
    inner join {{ source('postgres', 'competitions') }} c
        on c.id = l.competition_id
    cross join player_data pd

    -- Only active leagues with players known to the provider.
    where c.status = 'active'
      and l.is_archived = false

),

-- Step 6: label each player per league with their availability status.
final as (

    select
        lpc.league_id,
        lpc.competition_id,
        lpc.player_uuid             as player_id,
        lpc.player_name,
        lpc.position_type,
        lpc.nationality,
        lpc.club,
        lpc.competition_type,

        case
            when dp.player_uuid is not null then true
            else false
        end                         as is_drafted,

        dp.member_id                as drafted_by_member_id,

        -- availability_status from silver: available | injured | suspended | doubtful
        -- NULL → no data from provider → treat as available
        coalesce(
            pa.availability_status, 'available'
        )                           as availability_status,

        pa.return_date,
        pa.suspension_matches,

        -- Combined pool status
        case
            when dp.player_uuid is not null             then 'drafted'
            when pa.availability_status = 'injured'     then 'injured'
            when pa.availability_status = 'suspended'   then 'suspended'
            when pa.availability_status = 'doubtful'    then 'doubtful'
            else                                             'free'
        end                         as pool_status

    from league_player_cross lpc

    left join drafted_players dp
        on dp.player_uuid = lpc.player_uuid
        and dp.league_id  = lpc.league_id

    left join player_availability pa
        on pa.player_uuid = lpc.player_uuid

)

select
    {{ dbt_utils.generate_surrogate_key(['league_id', 'player_id']) }}
                            as player_pool_id,
    league_id,
    competition_id,
    player_id,
    player_name,
    position_type,
    nationality,
    club,
    competition_type,
    is_drafted,
    drafted_by_member_id,
    availability_status,
    return_date,
    suspension_matches,
    pool_status

from final