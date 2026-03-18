-- =============================================================================
-- RugbyDraft — RLS Policy Tests
-- File: db/tests/test_rls_policies.sql
-- Description: Validates that Row Level Security policies work as expected.
--              Run in Supabase SQL Editor (service_role context).
--              Tests simulate authenticated users via set_config / auth.uid().
-- =============================================================================

-- We use a transaction so all test data is rolled back at the end.
-- Nothing persists in the database after this script runs.
BEGIN;

-- =============================================================================
-- TEST SETUP — Create two fake users and one league
-- =============================================================================

-- Two fake UUIDs representing two distinct users
DO $$
DECLARE
    user_a_id     UUID := '00000000-0000-0000-0000-000000000001';
    user_b_id     UUID := '00000000-0000-0000-0000-000000000002';
    comp_id       UUID;
    league_a_id   UUID;
    member_a_id   UUID;
    member_b_id   UUID;
    roster_a_id   UUID;
    row_count     INT;
BEGIN

    -- -------------------------------------------------------------------------
    -- Insert fake auth users (bypasses RLS as service_role)
    -- We insert directly into auth.users to simulate real Supabase auth users
    -- -------------------------------------------------------------------------
    INSERT INTO auth.users (id, email, created_at, updated_at, raw_user_meta_data)
    VALUES
        (user_a_id, 'user_a@test.com', NOW(), NOW(), '{"locale":"fr"}'::jsonb),
        (user_b_id, 'user_b@test.com', NOW(), NOW(), '{"locale":"fr"}'::jsonb)
    ON CONFLICT (id) DO NOTHING;

    -- The handle_new_user trigger should have auto-created public.users rows.
    -- Verify trigger fired correctly:
    SELECT COUNT(*) INTO row_count FROM public.users WHERE id IN (user_a_id, user_b_id);
    ASSERT row_count = 2, 'FAIL: handle_new_user trigger did not create public.users rows';
    RAISE NOTICE 'PASS: handle_new_user trigger created % user profile(s)', row_count;

    -- -------------------------------------------------------------------------
    -- Create a competition and a league owned by user_a
    -- -------------------------------------------------------------------------
    INSERT INTO competitions (id, name, slug, type, season, total_rounds)
    VALUES (uuid_generate_v4(), 'Six Nations 2026', 'six-nations-2026', 'international', '2026', 5)
    RETURNING id INTO comp_id;

    INSERT INTO leagues (id, name, competition_id, commissioner_id)
    VALUES (uuid_generate_v4(), 'Ligue Test A', comp_id, user_a_id)
    RETURNING id INTO league_a_id;

    -- Add user_a as member of league_a
    INSERT INTO league_members (id, league_id, user_id)
    VALUES (uuid_generate_v4(), league_a_id, user_a_id)
    RETURNING id INTO member_a_id;

    -- Create a roster for user_a
    INSERT INTO rosters (id, league_id, member_id)
    VALUES (uuid_generate_v4(), league_a_id, member_a_id)
    RETURNING id INTO roster_a_id;

    -- user_b is NOT a member of league_a
    -- (we create user_b's member record in a separate league they own, not league_a)

    RAISE NOTICE '--- Setup complete. League A id: %, User A: %, User B: %',
        league_a_id, user_a_id, user_b_id;

    -- =============================================================================
    -- TEST 1: user_a can read their own league
    -- =============================================================================
    PERFORM set_config('request.jwt.claims',
        json_build_object('sub', user_a_id::text, 'role', 'authenticated')::text,
        true);
    SET LOCAL ROLE authenticated;

    SELECT COUNT(*) INTO row_count
    FROM leagues
    WHERE id = league_a_id;

    RESET ROLE;

    ASSERT row_count = 1, 'FAIL T1: user_a cannot read their own league';
    RAISE NOTICE 'PASS T1: user_a can read their own league';

    -- =============================================================================
    -- TEST 2: user_b CANNOT read user_a's league (not a member, not commissioner)
    -- =============================================================================
    PERFORM set_config('request.jwt.claims',
        json_build_object('sub', user_b_id::text, 'role', 'authenticated')::text,
        true);
    SET LOCAL ROLE authenticated;

    SELECT COUNT(*) INTO row_count
    FROM leagues
    WHERE id = league_a_id;

    RESET ROLE;

    ASSERT row_count = 0, 'FAIL T2: user_b can read a league they do not belong to';
    RAISE NOTICE 'PASS T2: user_b cannot read a league they do not belong to';

    -- =============================================================================
    -- TEST 3: user_a can read their own profile; user_b cannot read user_a's profile
    -- =============================================================================

    -- user_a reads own profile
    PERFORM set_config('request.jwt.claims',
        json_build_object('sub', user_a_id::text, 'role', 'authenticated')::text,
        true);
    SET LOCAL ROLE authenticated;

    SELECT COUNT(*) INTO row_count FROM users WHERE id = user_a_id;
    ASSERT row_count = 1, 'FAIL T3a: user_a cannot read own profile';
    RAISE NOTICE 'PASS T3a: user_a can read own profile';

    -- user_a tries to read user_b's profile — should return 0
    SELECT COUNT(*) INTO row_count FROM users WHERE id = user_b_id;
    RESET ROLE;

    ASSERT row_count = 0, 'FAIL T3b: user_a can read another user profile';
    RAISE NOTICE 'PASS T3b: user_a cannot read user_b profile';

    -- =============================================================================
    -- TEST 4: user_b CANNOT read league_members of league_a (not a member)
    -- =============================================================================
    PERFORM set_config('request.jwt.claims',
        json_build_object('sub', user_b_id::text, 'role', 'authenticated')::text,
        true);
    SET LOCAL ROLE authenticated;

    SELECT COUNT(*) INTO row_count
    FROM league_members
    WHERE league_id = league_a_id;

    RESET ROLE;

    ASSERT row_count = 0, 'FAIL T4: user_b can read members of a league they are not in';
    RAISE NOTICE 'PASS T4: user_b cannot read league_members of a foreign league';

    -- =============================================================================
    -- TEST 5: user_b CANNOT read rosters of league_a
    -- =============================================================================
    PERFORM set_config('request.jwt.claims',
        json_build_object('sub', user_b_id::text, 'role', 'authenticated')::text,
        true);
    SET LOCAL ROLE authenticated;

    SELECT COUNT(*) INTO row_count
    FROM rosters
    WHERE league_id = league_a_id;

    RESET ROLE;

    ASSERT row_count = 0, 'FAIL T5: user_b can read rosters of a league they are not in';
    RAISE NOTICE 'PASS T5: user_b cannot read rosters of a foreign league';

    -- =============================================================================
    -- TEST 6: competitions are readable by any authenticated user
    -- =============================================================================
    PERFORM set_config('request.jwt.claims',
        json_build_object('sub', user_b_id::text, 'role', 'authenticated')::text,
        true);
    SET LOCAL ROLE authenticated;

    SELECT COUNT(*) INTO row_count FROM competitions WHERE id = comp_id;
    RESET ROLE;

    ASSERT row_count = 1, 'FAIL T6: authenticated user cannot read competitions';
    RAISE NOTICE 'PASS T6: authenticated user can read competitions (public reference data)';

    -- =============================================================================
    -- TEST 7: fantasy_scores_staging is NOT readable by any authenticated user
    -- =============================================================================
    PERFORM set_config('request.jwt.claims',
        json_build_object('sub', user_a_id::text, 'role', 'authenticated')::text,
        true);
    SET LOCAL ROLE authenticated;

    -- This should return 0 rows (no permissive policy exists for authenticated role)
    SELECT COUNT(*) INTO row_count FROM fantasy_scores_staging;
    RESET ROLE;

    ASSERT row_count = 0, 'FAIL T7: authenticated user can read fantasy_scores_staging (should be blocked)';
    RAISE NOTICE 'PASS T7: fantasy_scores_staging is not readable by authenticated users';

    -- =============================================================================
    -- TEST 8: user_a CANNOT update user_b's profile
    -- =============================================================================
    PERFORM set_config('request.jwt.claims',
        json_build_object('sub', user_a_id::text, 'role', 'authenticated')::text,
        true);
    SET LOCAL ROLE authenticated;

    UPDATE users SET display_name = 'hacked' WHERE id = user_b_id;
    GET DIAGNOSTICS row_count = ROW_COUNT;
    RESET ROLE;

    ASSERT row_count = 0, 'FAIL T8: user_a could update user_b profile';
    RAISE NOTICE 'PASS T8: user_a cannot update user_b profile';

    -- =============================================================================
    -- ALL TESTS PASSED
    -- =============================================================================
    RAISE NOTICE '';
    RAISE NOTICE '=== ALL RLS TESTS PASSED ===';

END $$;

-- Roll back all test data — nothing persists
ROLLBACK;