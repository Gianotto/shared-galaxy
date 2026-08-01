-- Shared Galaxy — which storage on your ship is the shop
--
-- Consignment is one storage. The player points at it once, and from then on
-- manages the shop with the game's own interface: what they move in is for
-- sale, what they take out is not.
--
-- The id is the `<l id="…">` of the storage object in their own ship. It is
-- theirs and it survives between sessions — it dies when they dismantle the
-- storage, which is their choice and is handled as an empty shop rather than
-- as an error.
--
-- NULL means no shop: their storefront stands there with nothing to sell, which
-- is the correct default. Nobody's cargo goes on sale because a server decided
-- it should.

BEGIN;

ALTER TABLE membership ADD COLUMN shop_storage_id text;

COMMENT ON COLUMN membership.shop_storage_id IS
    'the <l id> of the storage this player sells from; NULL means nothing is '
    'for sale, which is the default because consent is the player moving cargo';

INSERT INTO schema_version (version) VALUES (11);

COMMIT;
