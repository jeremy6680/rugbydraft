-- =============================================================================
-- RugbyDraft — Test seed: one complete league for dashboard testing
-- Seed: 002_test_league.sql
-- Date: 2026-04-04
-- Description: Creates a Six Nations 2026 competition with one active league,
--              one commissioner (you), league_members, standings, and a pending
--              draft so the dashboard can be tested with real data.
--
-- HOW TO RUN:
--   Run in Supabase SQL Editor (runs as service_role — bypasses RLS).
--
-- IDEMPOTENT: uses INSERT ... ON CONFLICT DO NOTHING throughout.
--             Safe to run multiple times.
-- =============================================================================

DO $$
DECLARE
    v_user_id         UUID := '28fcba9e-e7e9-43a1-b565-7f495185276f';

    -- Fixed UUIDs for repeatability (safe to re-run without duplicates)
    -- UUID only allows hex characters: 0-9 and a-f
    v_competition_id  UUID := '10000000-0000-0000-0000-000000000001';
    v_round_1_id      UUID := '20000000-0000-0000-0000-000000000001';
    v_round_2_id      UUID := '20000000-0000-0000-0000-000000000002';
    v_round_3_id      UUID := '20000000-0000-0000-0000-000000000003';
    v_round_4_id      UUID := '20000000-0000-0000-0000-000000000004';
    v_round_5_id      UUID := '20000000-0000-0000-0000-000000000005';
    v_league_id       UUID := '30000000-0000-0000-0000-000000000001';
    v_member_id       UUID := '40000000-0000-0000-0000-000000000001';
    v_draft_id        UUID := '50000000-0000-0000-0000-000000000001';

BEGIN

    -- -----------------------------------------------------------------------
    -- 1. Ensure the user profile exists in public.users
    --    (normally created by the on_auth_user_created trigger — this is a
    --     safety net in case you're running the seed before first login)
    -- -----------------------------------------------------------------------
    INSERT INTO public.users (id, email, display_name, locale)
    VALUES (
        v_user_id,
        'jerem9911@hotmail.com',
        'Commissaire Test',
        'fr'
    )
    ON CONFLICT (id) DO UPDATE
        SET display_name = EXCLUDED.display_name
        WHERE users.display_name IS NULL;

    -- -----------------------------------------------------------------------
    -- 2. Competition: Six Nations 2026
    -- -----------------------------------------------------------------------
    INSERT INTO public.competitions (
        id, name, slug, type, season,
        is_premium, status, total_rounds,
        default_nationality_limit
    )
    VALUES (
        v_competition_id,
        'Six Nations 2026',
        'six-nations-2026',
        'international',
        '2026',
        FALSE,
        'active',
        5,
        4
    )
    ON CONFLICT (id) DO NOTHING;

    -- -----------------------------------------------------------------------
    -- 3. Competition rounds (5 journées)
    -- -----------------------------------------------------------------------
    INSERT INTO public.competition_rounds (id, competition_id, round_number, label, start_date, end_date)
    VALUES
        (v_round_1_id, v_competition_id, 1, 'Journée 1', '2026-02-01', '2026-02-02'),
        (v_round_2_id, v_competition_id, 2, 'Journée 2', '2026-02-08', '2026-02-09'),
        (v_round_3_id, v_competition_id, 3, 'Journée 3', '2026-02-22', '2026-02-23'),
        (v_round_4_id, v_competition_id, 4, 'Journée 4', '2026-03-08', '2026-03-09'),
        (v_round_5_id, v_competition_id, 5, 'Journée 5 (finale)', '2026-03-15', '2026-03-16')
    ON CONFLICT (id) DO NOTHING;

    -- -----------------------------------------------------------------------
    -- 4. League
    -- -----------------------------------------------------------------------
    INSERT INTO public.leagues (
        id, name, competition_id, commissioner_id,
        visibility, access_code, settings, is_archived
    )
    VALUES (
        v_league_id,
        'La Ligue du Crunch',
        v_competition_id,
        v_user_id,
        'private',
        'TEST01',
        '{"pick_timer_seconds": 120, "nationality_limit": 4, "trade_veto_enabled": true, "min_managers": 2, "max_managers": 6}'::jsonb,
        FALSE
    )
    ON CONFLICT (id) DO NOTHING;

    -- -----------------------------------------------------------------------
    -- 5. League member (you, as commissioner)
    -- -----------------------------------------------------------------------
    INSERT INTO public.league_members (id, league_id, user_id, is_ghost_team)
    VALUES (v_member_id, v_league_id, v_user_id, FALSE)
    ON CONFLICT (id) DO NOTHING;

    -- -----------------------------------------------------------------------
    -- 6. League standing (rank 1, 0 points — draft not done yet)
    -- -----------------------------------------------------------------------
    INSERT INTO public.league_standings (
        league_id, member_id, wins, losses, draws, total_points, rank
    )
    VALUES (v_league_id, v_member_id, 0, 0, 0, 0.00, 1)
    ON CONFLICT (league_id, member_id) DO NOTHING;

    -- -----------------------------------------------------------------------
    -- 7. Draft (pending — dashboard shows the draft badge)
    -- -----------------------------------------------------------------------
    INSERT INTO public.drafts (
        id, league_id, status, pick_timer_seconds,
        total_picks, current_pick_number, is_assisted_mode
    )
    VALUES (
        v_draft_id,
        v_league_id,
        'pending',
        120,
        30,
        0,
        FALSE
    )
    ON CONFLICT (id) DO NOTHING;

    RAISE NOTICE 'Seed 002 OK — competition: %, league: %, member: %, draft: %',
        v_competition_id, v_league_id, v_member_id, v_draft_id;

END $$;