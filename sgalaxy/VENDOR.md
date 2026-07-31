# Código vendorado

Arquivos copiados de outro repositório em vez de importados. A cópia é
deliberada: os dois projetos têm ciclos de vida diferentes e não quero criar
dependência de pacote entre eles enquanto nenhum dos dois está publicado.

O preço é deriva silenciosa, e a defesa contra ela é o teste cruzado descrito
abaixo — não a disciplina de quem lembrar de sincronizar.

## `savefile.py`

| | |
|---|---|
| Origem | <https://github.com/Gianotto/Space-Haven-SaveGameEditor> |
| Caminho | `shedit/savefile.py` |
| Commit | `1dc0eebcc25de41f51b72febfe271eaff319acdb` (2026-07-30) |
| Licença | MIT, mesmo autor, mesma licença deste repositório |
| Alterações locais | nenhuma |

Leitura e escrita byte-idêntica de savegame. A escrita byte-idêntica é a razão
de existir da cópia: um serializador próprio que reproduz o estilo do jogo
(sem espaço antes de `/>`, ordem de atributos preservada, escapes mínimos, sem
declaração XML) mais um trailer de bytes crus recuperado por diferença.

Enquanto este repositório só lê saves, uma divergência com o upstream é
inofensiva. A partir do momento em que ele **escreve** — o injetor de nave, e
depois o construtor de retratos da fase 2 — uma divergência corrompe partida de
jogador. Por isso o teste cruzado é obrigatório antes da fase 2.

### Teste cruzado

`tests/test_fingerprint_parity.py` roda a impressão digital das duas cópias
sobre os mesmos saves e exige o mesmo digest, mais o mesmo esqueleto de sistemas,
corpos, setores e nuvens. Rodando contra três saves reais em 2026-07-31: idêntico.

Precisa do repositório do editor ao lado (ou `SPACEHAVEN_EDITOR` apontando para
ele) e de savegames (ou `SPACEHAVEN_SAVES`). Sem os dois, o teste **se declara
pulado** em vez de passar calado — um teste que não rodou não é um teste que
passou, e o CI não tem save nenhum.

A consequência de uma divergência aqui não é cosmética: o servidor recusaria
saves legítimos na entrada de uma sala (seção 2.3) sem ninguém entender por quê.

### Divergência deliberada, desde 2026-07-31

O digest do servidor **não é mais o do editor**, e isso é decisão, não deriva.

O `compare_galaxy.py` monta a impressão digital a partir de corpos, setores e
nuvens. Medido depois: a galáxia é materializada preguiçosamente, um sistema por
vez, conforme o jogador olha ou chega. Um salto de hiperespaço acrescentou 14
corpos a um único sistema — três planetas, cinco luas e seis campos de
asteroides. Aquele digest, portanto, identifica **o quanto da galáxia foi
explorado**, não qual galáxia é.

Para uma sala isso é fatal: o servidor recusaria a devolução de qualquer jogador
que viajasse. O digest passou a cobrir só o tamanho do mapa e a **estrela** de
cada sistema — que existe desde o primeiro save, é o centro fixo e carrega a
semente do gerador. Conferido estável em quatro estados da mesma partida e
diferente entre galáxias.

**O editor tem o mesmo defeito**, no uso dele: comparar um save recém-criado com
um jogado da mesma galáxia vai dizer que são diferentes. Vale corrigir lá também.

O teste de paridade agora trava a divergência em vez de proibi-la, e continua
exigindo que as duas cópias **leiam** a mesma coisa.

### Ainda pendente: paridade de escrita

O teste acima cobre leitura. Falta o de **escrita byte-idêntica** — carregar o
mesmo save com as duas cópias, serializar, e exigir bytes iguais entre si e com
o original. É o que protege o injetor, que é a única ferramenta daqui que
escreve, e continua obrigatório antes da fase 2 ir para as mãos de jogador.
