-- Galáxia Compartilhada — o esqueleto da galáxia, para o mapa da sala
--
-- A sala já guarda a impressão digital, que serve para conferir entrada. Isso
-- não basta para desenhar: um digest não tem coordenada.
--
-- Aqui fica o que o mapa precisa e nada além — sistema, posição e nome. É
-- derivado do save do primeiro jogador, gravado uma vez quando a sala adota a
-- galáxia, e nunca mais: a seed reproduz o mundo gerado, então isto é constante
-- da sala, não estado de jogador.
--
-- A posição do sistema é a da ESTRELA dele. Os sistemas não têm coordenada
-- própria no save, e a estrela é o centro fixo: medido em dois saves da mesma
-- partida, com quase um dia e meio de jogo entre eles, nenhuma das 64 se moveu.
-- Os demais corpos orbitam e mudam sozinhos — por isso não entram.

BEGIN;

CREATE TABLE galaxy_system (
    room_id    text        NOT NULL REFERENCES room(id) ON DELETE CASCADE,
    system_id  text        NOT NULL,
    name       text,
    x          bigint      NOT NULL,
    y          bigint      NOT NULL,
    bodies     integer     NOT NULL DEFAULT 0,
    PRIMARY KEY (room_id, system_id)
);

-- Largura e altura da galáxia, para o mapa saber a escala sem adivinhar.
ALTER TABLE room ADD COLUMN galaxy_w bigint;
ALTER TABLE room ADD COLUMN galaxy_h bigint;

INSERT INTO schema_version (version) VALUES (2);

COMMIT;
