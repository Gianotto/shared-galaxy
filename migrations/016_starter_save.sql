-- Shared Galaxy — o save de partida da sala
--
-- A primeira entrada de alguem era a parte mais fragil do caminho inteiro. O
-- servidor nao consegue gerar uma colonia inicial, entao a partida tinha que
-- nascer no jogo: abrir o Space Haven, achar NEW GAME, escolher as opcoes,
-- criar a nave, salvar, fechar na hora certa. Cinco chances de errar antes de a
-- pessoa ver a galaxia compartilhada.
--
-- A sala ja guarda a partida de quem a criou: e o `galaxy_sha256`, capturado no
-- momento em que essa pessoa entrou. Ele serve como ponto de partida sem mais
-- nada ser feito, e e o padrao. A coluna existe para quem quiser trocar por
-- outra: uma sala pode preferir comecar com uma nave especifica.
--
-- A copia nao sai intocada. O nome da nave muda, senao o mapa da sala mostra
-- tres HSS YANNI, e o lugar muda, senao todo mundo nasce empilhado no mesmo
-- corpo celeste. A tripulacao continua a mesma, com os mesmos nomes, e isso e
-- uma perda real que fica registrada aqui em vez de descoberta depois.

BEGIN;

ALTER TABLE room ADD COLUMN starter_sha256 text;

COMMENT ON COLUMN room.starter_sha256 IS
    'save handed to newcomers, renamed and moved to a free body. NULL falls '
    'back to galaxy_sha256, the founder''s save at the moment they joined';

INSERT INTO schema_version (version) VALUES (16);

COMMIT;
