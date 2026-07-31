-- Shared Galaxy — a place stops being identified by `celeid`
--
-- `celeid` is a catalogue id: 123 bodies in one save carry 11 distinct values,
-- and every asteroid field is `celeid="0"` (docs/findings.md, item 24). It says
-- what KIND of place something is, never which place — so two different
-- asteroid fields in one system were recorded as the same visit.
--
-- The local `id` does not work either. Bodies materialised during exploration
-- draw from `starmap/@objectIdCounter`, a single global counter, so two players
-- who explore different systems allocate the same ids to different places.
--
-- What survives both tests is `(systemId, x, y)`: generated from the seed, does
-- not move, and gave 123 distinct keys for 123 bodies in every save checked. It
-- is the key the phase 2 discovery merge needs.
--
-- Existing `room_visit` rows keep the truth the map actually draws — the system
-- — and lose only the false precision below it. Rows that collapse into one are
-- merged, keeping the earliest arrival and summing the counts.

BEGIN;

ALTER TABLE membership
    ADD COLUMN at_x    text,
    ADD COLUMN at_y    text,
    ADD COLUMN at_body text;

COMMENT ON COLUMN membership.at_x IS
    'the fleet''s X on the starmap; with at_y and at_system it names the place';
COMMENT ON COLUMN membership.at_body IS
    'body type (Planet, AsteroidField…), for display only; null in open space';

ALTER TABLE membership DROP COLUMN at_celeid;

-- `celeid` is part of room_visit's PRIMARY KEY, so the key has to come apart
-- before the column can.
ALTER TABLE room_visit ADD COLUMN x text NOT NULL DEFAULT '';
ALTER TABLE room_visit ADD COLUMN y text NOT NULL DEFAULT '';

ALTER TABLE room_visit DROP CONSTRAINT room_visit_pkey;
ALTER TABLE room_visit DROP COLUMN celeid;

-- Several old rows can now be the same row. Merge instead of dropping: who
-- arrived first is the part worth keeping.
WITH merged AS (
    SELECT room_id, system_id, x, y,
           min(first_at) AS first_at,
           sum(visits)   AS visits,
           (array_agg(first_by ORDER BY first_at))[1] AS first_by
      FROM room_visit
     GROUP BY room_id, system_id, x, y
), wiped AS (
    DELETE FROM room_visit RETURNING 1
)
INSERT INTO room_visit (room_id, system_id, x, y, first_at, visits, first_by)
SELECT room_id, system_id, x, y, first_at, visits, first_by FROM merged;

ALTER TABLE room_visit ADD PRIMARY KEY (room_id, system_id, x, y);

INSERT INTO schema_version (version) VALUES (6);

COMMIT;
