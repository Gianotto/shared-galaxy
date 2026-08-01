-- Shared Galaxy — what one player uncovers, the room sees
--
-- The room pools `visited`: the places somebody actually went to, and those
-- arrive charted. `isVisible` is not shared on its own — it comes along only
-- where a visit came with it. Whatever a member merely glimpsed from a distance
-- and never entered stays theirs. Someone who joins later inherits the room's
-- travels, not its telescope.
--
-- WHY A WHOLE SUBTREE AND NOT A FLAG
--
-- The galaxy materialises lazily (docs/findings.md, item 19). A freshly created
-- save carries 123 bodies for 64 systems: the stars, the asteroid fields and
-- the starting point. A planet somebody visited in system 40 does not exist at
-- all in the save of someone who never went — there is no flag to set. So the
-- body itself is kept, and inserted when it is missing.
--
-- It is small. Measured across real saves, a visited body is 600 to 3300 bytes
-- of XML, and the fifteen in a 178-day save came to 18 KB together.
--
-- `<fleets>` is stripped before storing: a visited body carries the ships
-- parked at it, and copying that would put other people's ships in somebody's
-- sector. Visible neighbours are phase 2, with a recipe and rules of their own.
--
-- THE KEY IS (systemId, x, y), for the reason in item 24: `celeid` names a KIND
-- of place, and the local `id` is handed out by a global counter as people
-- explore, so it means different places to different players.
--
-- First discoverer wins and is recorded. Nobody is credited twice for the same
-- rock, and the room can say who charted what.

BEGIN;

CREATE TABLE room_body (
    room_id    text        NOT NULL REFERENCES room(id) ON DELETE CASCADE,
    system_id  text        NOT NULL,
    x          text        NOT NULL,
    y          text        NOT NULL,
    body_xml   text        NOT NULL,
    first_by   bigint      REFERENCES player(id) ON DELETE SET NULL,
    first_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (room_id, system_id, x, y)
);

COMMENT ON TABLE room_body IS
    'places the room has visited, with the body subtree needed to chart them '
    'for members who have never been there (findings 19, 23, 24)';
COMMENT ON COLUMN room_body.body_xml IS
    'the <l> body element, with <fleets> stripped: the place travels, the '
    'ships parked at it do not';

CREATE INDEX room_body_room_idx ON room_body (room_id);

INSERT INTO schema_version (version) VALUES (8);

COMMIT;
