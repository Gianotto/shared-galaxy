-- Shared Galaxy — a shorter history
--
-- Twenty versions per player per room was chosen before there was anything to
-- weigh it against. Two things are now known.
--
-- FIRST: there is no rollback. No route restores an old version — not for a
-- player, not for a room owner, not for anybody. The history is server-side
-- only. So the worry that keeping many versions would soften the game does not
-- apply: nobody can reload a session that went badly, and a mistake that costs
-- a crew costs it.
--
-- SECOND: what the history actually protects against is US. A bad graft, a
-- storefront stripped wrong, a settlement written into the wrong save — every
-- one of those has happened during development, and each was caught because
-- the previous version was still there. That is a fault of this server, not of
-- the person playing, and making them pay for it would be indefensible.
--
-- Hence three, not one and not twenty. One would mean the only stored version
-- is the canonical itself: a bad check-in overwrites it and there is nothing
-- behind it. Three leaves two steps back, costs almost nothing on disk, and —
-- because there is no rollback route — changes nothing about how the game
-- plays.
--
-- Rooms already created keep whatever they were set to unless it is the old
-- default; a room owner who deliberately chose a number is not overruled here.

BEGIN;

ALTER TABLE room ALTER COLUMN retention_n SET DEFAULT 3;

UPDATE room SET retention_n = 3 WHERE retention_n = 20;

COMMENT ON COLUMN room.retention_n IS
    'how many versions of each save are kept, per player. Protects against '
    'faults in this server, not against the player: there is no rollback route';

-- E o teto de pessoas. A sala precisa abrir para 64 — e o tamanho de um
-- convite de Discord — e o padrao era 8 pela API e 32 pelo site. Duas rotas
-- criando salas com tetos diferentes, e ninguem descobriria antes de a 33a
-- pessoa chegar e nao caber.
ALTER TABLE room ALTER COLUMN max_players SET DEFAULT 64;

UPDATE room SET max_players = 64 WHERE max_players IN (8, 32);

INSERT INTO schema_version (version) VALUES (14);

COMMIT;
