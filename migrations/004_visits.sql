-- Shared Galaxy — where the room has actually been
--
-- An earlier version of the map coloured "named" systems as if they were
-- explored. Measured and false: the game names all 64 at once, early, not by
-- proximity (findings item 15).
--
-- This is the honest version. The server already learns each player's position
-- on every join and check-in, so it can accumulate where the room has been —
-- from recorded fact, not inference. It also grows into something a room wants:
-- a shared record of who opened up which corner of the galaxy first.

BEGIN;

CREATE TABLE room_visit (
    room_id     text        NOT NULL REFERENCES room(id) ON DELETE CASCADE,
    system_id   text        NOT NULL,
    -- The celestial body, in the room's shared language: `celeid` comes from
    -- the seed and means the same thing in everyone's save (findings item 1).
    celeid      text,
    first_by    bigint      REFERENCES player(id) ON DELETE SET NULL,
    first_at    timestamptz NOT NULL DEFAULT now(),
    visits      integer     NOT NULL DEFAULT 1,
    PRIMARY KEY (room_id, system_id, celeid)
);

CREATE INDEX room_visit_system_idx ON room_visit (room_id, system_id);

-- The room cap was 8, chosen without measuring. Storage is not the constraint:
-- twenty versions per player at ~300 KB compressed is 6 MB a head, so a hundred
-- players fit in well under a gigabyte.
--
-- The real limit is per SECTOR, not per room. Neighbours visible in the same
-- sector compete for factions, and the game has about nine usable sides
-- (findings item 11); and each storefront injected into your save costs ~166 KB.
-- Spread across a 64-system galaxy that rarely binds. Stacked on one asteroid it
-- binds immediately — and that is where the check belongs, in phase 2, not here.
ALTER TABLE room ALTER COLUMN max_players SET DEFAULT 32;
ALTER TABLE room DROP CONSTRAINT max_players_sane;
ALTER TABLE room ADD CONSTRAINT max_players_sane
    CHECK (max_players BETWEEN 1 AND 500);

INSERT INTO schema_version (version) VALUES (4);

COMMIT;
