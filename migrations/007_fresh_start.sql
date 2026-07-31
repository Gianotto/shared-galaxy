-- Shared Galaxy — a room can require that people arrive on a new game
--
-- Joining used to accept any save. Since the server grafts the room's galaxy in
-- (migration 005), an old colony joins as easily as a new one — and arrives
-- with its ship, crew, bank and research intact. Measured: a 178-day save
-- joined a room whose oldest member was on day 2.8, keeping 11 crew and 14093
-- credits.
--
-- That is not a bug in the graft; the graft is supposed to preserve exactly
-- those things. It is a rule the room was missing. Somebody who has played for
-- half a year does not start alongside somebody who just launched, and a room
-- that lets them is not a shared start.
--
-- So: a maximum age at the moment of joining, in days, decided by whoever
-- creates the room. It only ever applies at `join` — once you are in, you play
-- as long as you like.
--
-- The default is 5. A freshly created game is not zero: measured across saves
-- made minutes apart, the game starts a colony at about day 1.3. Five leaves
-- room to name a ship, look around and save, and refuses a colony.
--
-- NULL means no limit, for a room that wants veterans to bring what they have.

BEGIN;

ALTER TABLE room ADD COLUMN max_join_age_days numeric(10,2) DEFAULT 5;

COMMENT ON COLUMN room.max_join_age_days IS
    'oldest colony age accepted at join, in days; NULL means no limit. A new '
    'game starts at about day 1.3, so this is a "start together" rule';

INSERT INTO schema_version (version) VALUES (7);

COMMIT;
