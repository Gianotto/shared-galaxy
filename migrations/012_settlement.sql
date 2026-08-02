-- Shared Galaxy — routing a sale back to the person who made it
--
-- The game runs the whole economy against a ship the server invented. Somebody
-- opens trade with a neighbour's storefront, buys 40 steel plates and pays what
-- the game priced them at — all correct, from the game's point of view. But the
-- neighbour does not exist to the game: the storefront is a copy with a faction
-- bank. The credits stop there and die when the storefront is stripped at
-- check-in.
--
-- These two things carry the result back to a person.
--
-- lease.consignments is the photograph taken at checkout: for each storefront,
-- whose it is, what was on the shelf and what the bank held. Without it there
-- is nothing to compare the returned save against, and a sale is exactly a
-- difference between two moments.
--
-- settlement is what the comparison found, owed to the seller and not yet paid.
-- It is a separate table and not a column because it outlives the lease that
-- produced it: the seller collects at THEIR next checkout, which may be days
-- later, and may pay out several sessions' worth of sales at once.
--
-- Only the selling direction is recorded. If a visitor sells INTO a storefront
-- the stock rises and the bank falls — but that bank is a number the server
-- invented, not the neighbour's money. Debiting somebody for a purchase they
-- did not make, with money they never had, is worse than losing the trade.

BEGIN;

ALTER TABLE lease ADD COLUMN consignments jsonb NOT NULL DEFAULT '[]'::jsonb;

COMMENT ON COLUMN lease.consignments IS
    'photograph of each storefront at checkout: sid, seller, shelf and bank. '
    'A sale is the difference between this and what comes back';

CREATE TABLE settlement (
    id            bigserial PRIMARY KEY,
    room_id       text        NOT NULL REFERENCES room(id) ON DELETE CASCADE,
    seller_id     bigint      NOT NULL REFERENCES player(id) ON DELETE CASCADE,
    buyer_id      bigint      NOT NULL REFERENCES player(id) ON DELETE CASCADE,
    lease_id      bigint      REFERENCES lease(id) ON DELETE SET NULL,
    sid           text        NOT NULL,
    credits       integer     NOT NULL DEFAULT 0,
    goods         jsonb       NOT NULL DEFAULT '{}'::jsonb,
    notes         jsonb       NOT NULL DEFAULT '[]'::jsonb,
    created_at    timestamptz NOT NULL DEFAULT now(),
    paid_at       timestamptz,
    paid_lease_id bigint      REFERENCES lease(id) ON DELETE SET NULL
);

COMMENT ON TABLE settlement IS
    'a sale made against a storefront, owed to the seller until their next '
    'checkout; paid_at is when the credits and the missing goods were actually '
    'written into their save';

-- O saque e por vendedor e por sala, e so o que ainda nao foi pago.
CREATE INDEX settlement_unpaid ON settlement (room_id, seller_id)
    WHERE paid_at IS NULL;

INSERT INTO schema_version (version) VALUES (12);

COMMIT;
