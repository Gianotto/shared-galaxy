-- Shared Galaxy — one account per address
--
-- Registration asks for a name and nothing else: no email, no password, no
-- confirmation. That is deliberate and it is what the privacy policy promises.
-- It also means a script can create accounts without limit, and each account
-- can create rooms, so the public room list fills with junk before a single
-- real person arrives.
--
-- WHAT IS STORED, AND WHAT IS NOT
--
-- Not the address. What is stored is HMAC-SHA256(pepper, address), where the
-- pepper is a server secret that never leaves the .env. Enough to answer "has
-- this address registered before", useless for answering "where was this
-- person" — a raw SHA-256 of an IPv4 would not be, because four billion
-- candidates is a few seconds of brute force.
--
-- NULL lifts the limit for that account, and that is the escape hatch, not a
-- bug. Households, university halls and every mobile carrier on CGNAT put many
-- real people behind one address; when that happens the fix is to clear the
-- column for the account that was blocked, not to argue with the person.
--
--     UPDATE player SET signup_ip_hash = NULL WHERE id = 42;
--
-- The limit itself is SGALAXY_MAX_PER_IP in the environment, so raising it for
-- a LAN party does not need a deploy.

BEGIN;

ALTER TABLE player ADD COLUMN signup_ip_hash text;

COMMENT ON COLUMN player.signup_ip_hash IS
    'HMAC of the address this account was created from, never the address '
    'itself; NULL means the per-address limit does not apply to this account';

CREATE INDEX player_signup_ip ON player (signup_ip_hash)
    WHERE signup_ip_hash IS NOT NULL;

INSERT INTO schema_version (version) VALUES (13);

COMMIT;
