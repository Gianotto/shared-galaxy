-- Shared Galaxy — remember which save defines the room's galaxy
--
-- The room stores a digest, which answers "is this the same galaxy?" but cannot
-- answer "give me that galaxy". Grafting needs the second: when a player arrives
-- with a galaxy of their own, the server replaces it with the room's, and it
-- needs the room's actual starmap to do that.
--
-- It is the sha256 of a save already in the blob store — the one the first
-- player uploaded — so this costs no extra storage. Nulled rather than
-- restricted if that version is ever pruned: without a donor the server falls
-- back to refusing mismatched saves, which is where it stood before.

BEGIN;

ALTER TABLE room ADD COLUMN galaxy_sha256 char(64);

COMMENT ON COLUMN room.galaxy_sha256 IS
    'save whose <starmap> is grafted into arriving players (findings 17)';

INSERT INTO schema_version (version) VALUES (5);

COMMIT;
