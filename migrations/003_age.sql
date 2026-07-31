-- Shared Galaxy — game day becomes colony age
--
-- Same number, better name. "Game day 2.79" describes the save; "age: 2.79
-- days" describes the colony, and on a room map that is what people compare —
-- who has been out here longest.

BEGIN;

ALTER TABLE save_version RENAME COLUMN game_day TO age_days;

INSERT INTO schema_version (version) VALUES (3);

COMMIT;
