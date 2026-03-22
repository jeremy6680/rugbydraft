-- =============================================================================
-- mart_player_value
-- =============================================================================
-- Gold model. One row per player per competition.
--
-- Default value score for autodraft and ghost team auto-selection.
-- Recency-weighted rolling average of total_points from the last 4 rounds,
-- with bonuses for availability and kicker history.
--
-- Silver column names (actual):
--   stg_players:             player_external_id, player_name, position_type
--   stg_player_availability: player_external_id, availability_status
--
-- Materialized as: table (target: prod)
-- =============================================================================

{{
    config(
        materialized='table',
        description='Default value score per player per competition. '
                    'Used by autodraft and ghost team auto-selection.'
    )
}}

-- Step 1: resolve player external_id → UUID.
with player_id_map as (

    select
        p.id            as player_uuid,
        p.external_id   as player_external_id
    from {{ source('postgres', 'players') }} p
    where p.external_id is not null

),

-- Step 2: rank the last 4 rounds per competition (most recent first).
recent_rounds as (

    select
        cr.id               as round_id,
        cr.competition_id,
        cr.round_number,
        row_number() over (
            partition by cr.competition_id
            order by cr.round_number desc
        )                   as recency_rank

    from {{ source('postgres', 'competition_rounds') }} cr

),

-- Step 3: collect fantasy scores from the last 4 rounds per player.
recent_scores as (

    select
        fp.player_id        as player_uuid,
        rr.competition_id,
        rr.recency_rank,
        fp.total_points,
        fp.is_kicker,
        -- Recency weight: most recent round counts double
        case when rr.recency_rank = 1 then 2.0 else 1.0 end as weight

    from {{ ref('mart_fantasy_points') }} fp
    inner join recent_rounds rr
        on rr.round_id = fp.round_id
        and rr.recency_rank <= 4

),

-- Step 4: weighted average per player per competition.
weighted_avg as (

    select
        player_uuid,
        competition_id,
        case
            when sum(weight) > 0
            then sum(total_points * weight) / sum(weight)
            else 0
        end::numeric(6, 2)  as weighted_avg_points,
        sum(case when is_kicker then 1 else 0 end) as kicker_appearances,
        count(*)                                    as rounds_with_data

    from recent_scores
    group by player_uuid, competition_id

),

-- Step 5: current availability per player from silver.
availability as (

    select
        pid.player_uuid,
        pa.availability_status
    from {{ source('postgres', 'pipeline_stg_player_availability') }} pa
    inner join player_id_map pid
        on pid.player_external_id = pa.player_external_id

),

-- Step 6: player name and position from silver.
player_ref as (

    select
        pid.player_uuid,
        sp.player_name,
        sp.position_type
    from {{ source('postgres', 'pipeline_stg_players') }} sp
    inner join player_id_map pid
        on pid.player_external_id = sp.player_external_id

),

-- Step 7: final value score combining weighted avg + bonuses.
value_scores as (

    select
        wa.player_uuid,
        wa.competition_id,
        wa.weighted_avg_points,
        wa.rounds_with_data,
        coalesce(av.availability_status, 'available')   as availability_status,

        -- Kicker score: proxy for how reliable this player is as a kicker.
        case
            when wa.rounds_with_data > 0
            then wa.weighted_avg_points
                    * (wa.kicker_appearances::numeric / wa.rounds_with_data)
            else 0
        end::numeric(6, 2)                              as kicker_score,

        -- Default value score for autodraft ordering.
        (
            wa.weighted_avg_points
            + case
                when coalesce(av.availability_status, 'available') = 'available' then 2.0
                when coalesce(av.availability_status, 'available') = 'doubtful'  then 0.5
                else 0.0
              end
            + case
                when wa.kicker_appearances >= 2 then 1.5
                when wa.kicker_appearances  = 1 then 0.75
                else 0.0
              end
        )::numeric(6, 2)                                as default_value_score

    from weighted_avg wa
    left join availability av
        on av.player_uuid = wa.player_uuid

)

select
    {{ dbt_utils.generate_surrogate_key(['vs.player_uuid', 'vs.competition_id']) }}
                                as player_value_id,
    vs.player_uuid              as player_id,
    vs.competition_id,
    pr.player_name,
    pr.position_type,
    vs.weighted_avg_points,
    vs.kicker_score,
    vs.default_value_score,
    vs.availability_status,
    vs.rounds_with_data

from value_scores vs
left join player_ref pr
    on pr.player_uuid = vs.player_uuid

order by vs.competition_id, vs.default_value_score desc