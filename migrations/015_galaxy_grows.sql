-- Shared Galaxy — a galaxy grows, and the gate has to know that
--
-- A room compared saves by one number: the digest of every system's star. It
-- refused anything that did not match exactly, and the reasoning was that a
-- star does not drift while bodies materialise around it.
--
-- The star does not drift. The LIST does.
--
-- Measured on a real session that was refused at check-in: the save handed out
-- had 64 systems, the save returned had 65. System 65 — "Kalevala" — did not
-- exist in the delivered file at all; the game generated it when the player
-- travelled there. The 64 systems present in both had byte-identical stars:
-- zero divergence. Nothing was wrong with that save. The gate was wrong.
--
-- So the question "is this the room's galaxy" cannot be answered by equality
-- over a set that grows. It is answered by AGREEMENT: every system the two
-- saves have in common must carry the same star. A seed generates the same
-- system 12 every time, so a save that disagrees about system 12 came from a
-- different galaxy, and a save that simply knows about more systems has only
-- been explored further.
--
-- Comparing the seed instead would be simpler and does not work: the save
-- records seed="0" regardless of what the galaxy was generated from.
--
-- This column is the room's accumulated star map, {systemId: star}. It starts
-- from the first save and gains whatever later saves discover, so the room
-- learns the galaxy as its players do.

BEGIN;

ALTER TABLE room ADD COLUMN galaxy_stars jsonb;

COMMENT ON COLUMN room.galaxy_stars IS
    'accumulated {systemId: star} of this room''s galaxy. A save is accepted '
    'when it agrees on shared systems, not when it has exactly these — the '
    'game generates systems as players travel';

INSERT INTO schema_version (version) VALUES (15);

COMMIT;
