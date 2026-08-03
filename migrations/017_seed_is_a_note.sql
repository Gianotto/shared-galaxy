-- Shared Galaxy — a seed e anotacao, e nao requisito
--
-- A coluna nasceu NOT NULL porque a seed era a receita: quem quisesse entrar
-- criava uma partida com ela e o servidor conferia se a galaxia batia.
--
-- Duas coisas mudaram desde entao. Quem chega recebe uma copia do molde, ou tem
-- a galaxia enxertada por cima da partida que trouxe, e nos dois casos a seed
-- nao participa. E o que identifica uma galaxia sao as estrelas dela, que o
-- save carrega, enquanto a seed digitada nao aparece em lugar nenhum do
-- arquivo: medido em quatro partidas diferentes, `game@seed` vem "0" em todas.
--
-- Entao o servidor nunca pode conferir uma seed, e exigi-la so obrigava quem
-- funda uma galaxia a inventar um numero e digita-lo de novo, exatamente, no
-- jogo. Ela fica como nota de quem fundou, para quem quiser recriar o mundo
-- por fora.

BEGIN;

ALTER TABLE room ALTER COLUMN seed DROP NOT NULL;

COMMENT ON COLUMN room.seed IS
    'the seed the founder says they used, kept as a note. The game does not '
    'record it in the save, so this is never verified and nothing depends on it';

INSERT INTO schema_version (version) VALUES (17);

COMMIT;
