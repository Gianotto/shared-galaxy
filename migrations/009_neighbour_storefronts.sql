-- Shared Galaxy — remember which ships the server put in a save
--
-- A neighbour's storefront is assembled into the save handed out at checkout.
-- It has to come back out at check-in, and this is what makes that possible.
--
-- Without it the storefront becomes a permanent part of somebody's game: it
-- would be stored as their canonical, handed back at the next checkout, and
-- stack one more every session. Worse, a neighbour's ship would stay parked in
-- somebody's save long after that neighbour left the room.
--
-- The sids are assigned from the destination save's own counter at checkout, so
-- the server is the only one that knows them — there is nothing in the save
-- itself that marks a ship as ours, and inventing an attribute the game does
-- not know is a worse bet than writing the numbers down here.
--
-- Per lease, because that is exactly the span of one delivered save.

BEGIN;

ALTER TABLE lease ADD COLUMN injected_sids jsonb NOT NULL DEFAULT '[]'::jsonb;

COMMENT ON COLUMN lease.injected_sids IS
    'sids of the neighbour storefronts assembled into the delivered save; '
    'stripped again at check-in so they never become part of the player''s game';

INSERT INTO schema_version (version) VALUES (9);

COMMIT;
