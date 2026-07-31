-- Galáxia Compartilhada — esquema inicial (fase 0, a custódia)
--
-- O servidor é dono da verdade: guarda o save de cada jogador, empresta a cada
-- sessão e recebe de volta. Aqui mora o metadado; o save em si fica no volume,
-- endereçado por sha256 (server/storage/blobs.py).
--
-- Duas coisas que explicam quase todo o desenho abaixo:
--
-- 1. Não há dado pessoal. A identidade é um token opaco que o servidor emite na
--    primeira conexão, e nem ele é guardado — só o hash. Não há e-mail, não há
--    senha, não há como recuperar conta sem o código que o cliente guardou.
-- 2. A sala é pública e listável desde o começo, então cota e limite não são
--    "depois": estão nas colunas desde a primeira migração.

BEGIN;

CREATE TABLE schema_version (
    version     integer     PRIMARY KEY,
    applied_at  timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Jogador
-- ---------------------------------------------------------------------------

CREATE TABLE player (
    id            bigserial   PRIMARY KEY,
    -- sha256 do token. O token em claro existe uma vez só, na resposta de
    -- POST /players, e nunca mais: quem perder não recupera, e isso está dito
    -- em letras grandes no cliente.
    token_hash    char(64)    NOT NULL UNIQUE,
    display_name  text        NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),
    last_seen_at  timestamptz,
    -- Cota anti-abuso de sala aberta. Criar token é grátis; criar sala não deve
    -- ser ilimitado.
    rooms_created integer     NOT NULL DEFAULT 0,
    blocked       boolean     NOT NULL DEFAULT false,
    CONSTRAINT display_name_sane CHECK (
        length(display_name) BETWEEN 1 AND 40)
);

-- ---------------------------------------------------------------------------
-- Sala
-- ---------------------------------------------------------------------------

CREATE TABLE room (
    id             text        PRIMARY KEY,   -- identificador curto e legível
    name           text        NOT NULL,
    -- A seed não fica no save (o atributo `seed` da raiz vem 0 em toda partida),
    -- então quem precisa saber a seed de uma sala é o servidor. É ela que o
    -- jogador digita ao criar a partida.
    seed           text        NOT NULL,
    -- As opções de criação importam tanto quanto a seed: mesma seed com opções
    -- diferentes não dá a mesma galáxia. Guardadas como vieram, para o cliente
    -- exibir exatamente o que o jogador tem que reproduzir.
    options        jsonb       NOT NULL DEFAULT '{}'::jsonb,
    -- A impressão digital que todo save de entrada tem que bater. Fica nula até
    -- o primeiro jogador entrar: é ele quem define de fato a galáxia da sala.
    galaxy_digest  char(16),
    -- Versão do FORMATO do save (`info/@version`, vale 21 no jogo 1.0.4). Se a
    -- Bugbyte mudar o formato, um save de outra versão é recusado na entrada em
    -- vez de aceito e corrompido depois.
    save_version   text,
    password_hash  text,
    owner_id       bigint      NOT NULL REFERENCES player(id) ON DELETE RESTRICT,
    lease_hours    integer     NOT NULL DEFAULT 12,
    retention_n    integer     NOT NULL DEFAULT 20,
    max_players    integer     NOT NULL DEFAULT 8,
    listed         boolean     NOT NULL DEFAULT true,
    created_at     timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT lease_hours_sane  CHECK (lease_hours BETWEEN 1 AND 168),
    CONSTRAINT retention_n_sane  CHECK (retention_n BETWEEN 1 AND 200),
    -- Vizinhos visíveis no mesmo setor competem por facção, e o jogo tem cerca
    -- de nove lados usáveis (docs/findings.md, item 11). O teto é generoso de
    -- propósito: o limite real é por setor, não por sala.
    CONSTRAINT max_players_sane  CHECK (max_players BETWEEN 1 AND 64)
);

CREATE INDEX room_listed_idx ON room (listed, created_at DESC);

-- ---------------------------------------------------------------------------
-- Versão de save
-- ---------------------------------------------------------------------------

CREATE TYPE save_kind AS ENUM ('canonical', 'checkpoint', 'delivered');

CREATE TABLE save_version (
    id          bigserial   PRIMARY KEY,
    room_id     text        NOT NULL REFERENCES room(id) ON DELETE CASCADE,
    player_id   bigint      NOT NULL REFERENCES player(id) ON DELETE CASCADE,
    sha256      char(64)    NOT NULL,
    bytes       bigint      NOT NULL,
    kind        save_kind   NOT NULL,
    -- Dia de jogo, lido do save. Serve ao mapa da sala e à conferência da 2.7:
    -- um save que volta com menos dias do que saiu é sinal, não erro do jogador.
    game_day    numeric(10,2),
    galaxy_digest char(16),
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX save_version_owner_idx
    ON save_version (room_id, player_id, created_at DESC);
-- A poda de blobs pergunta quais hashes ainda estão vivos.
CREATE INDEX save_version_sha_idx ON save_version (sha256);

-- ---------------------------------------------------------------------------
-- Participação
-- ---------------------------------------------------------------------------

CREATE TABLE membership (
    room_id      text        NOT NULL REFERENCES room(id) ON DELETE CASCADE,
    player_id    bigint      NOT NULL REFERENCES player(id) ON DELETE CASCADE,
    ship_name    text,       -- é o `sname` que distingue um jogador do outro na tela
    canonical_id bigint      REFERENCES save_version(id) ON DELETE SET NULL,
    -- Onde a frota do jogador está, na língua da sala: `celeid` é derivado da
    -- seed e igual em todo save; o `id` local não serve (findings.md, item 1).
    at_system    text,
    at_celeid    text,
    joined_at    timestamptz NOT NULL DEFAULT now(),
    last_seen_at timestamptz,
    PRIMARY KEY (room_id, player_id)
);

CREATE INDEX membership_where_idx ON membership (room_id, at_system, at_celeid);

-- ---------------------------------------------------------------------------
-- Empréstimo
-- ---------------------------------------------------------------------------

-- `open` = o save está com o jogador. `returned` = devolvido e conciliado.
-- `expired` = o prazo venceu e o estado voltou ao de quando foi retirado, que é
-- o que tapa o buraco de "só devolvo a sessão que foi boa".
CREATE TYPE lease_state AS ENUM ('open', 'returned', 'expired');

CREATE TABLE lease (
    id           bigserial   PRIMARY KEY,
    room_id      text        NOT NULL REFERENCES room(id) ON DELETE CASCADE,
    player_id    bigint      NOT NULL REFERENCES player(id) ON DELETE CASCADE,
    state        lease_state NOT NULL DEFAULT 'open',
    -- A versão que foi entregue. O servidor montou esse arquivo, então na
    -- devolução ele compara os dois em vez de adivinhar (seção 2.7).
    delivered_id bigint      NOT NULL REFERENCES save_version(id) ON DELETE RESTRICT,
    returned_id  bigint      REFERENCES save_version(id) ON DELETE SET NULL,
    issued_at    timestamptz NOT NULL DEFAULT now(),
    expires_at   timestamptz NOT NULL,
    closed_at    timestamptz
);

-- Um empréstimo aberto por jogador e sala. É o que impede a duplicação por
-- sessão paralela (seção 2.7), e o banco é o lugar certo para garantir isso.
CREATE UNIQUE INDEX lease_one_open_per_player
    ON lease (room_id, player_id) WHERE state = 'open';
CREATE INDEX lease_expiry_idx ON lease (state, expires_at);

-- ---------------------------------------------------------------------------

INSERT INTO schema_version (version) VALUES (1);

COMMIT;
