# Galáxia Compartilhada

*[Read in English](README.md)*

Um servidor que permite a vários jogadores de Space Haven dividirem a mesma
galáxia, cada um rodando o próprio jogo, **sem que uma linha do código do jogo
seja alterada**.

**Fase inicial.** Ainda não existe servidor. O que está aqui é o projeto, os
fatos medidos em que ele se apoia, e as ferramentas do único experimento que
precisa ser respondido antes da parte interessante poder ser construída.

## Como isso é possível

Space Haven não tem modo headless, a simulação não é determinística, e o jogo é
dono do arquivo enquanto está aberto. Um servidor de multiplayer ao vivo está
fora de alcance, e este projeto não finge o contrário.

O que **está** ao alcance se apoia em três fatos, cada um medido carregando
saves alterados no jogo 1.0.4 e olhando o resultado:

- **A seed de criação reproduz a galáxia.** Mesma seed e mesmas opções dão os
  mesmos sistemas, os mesmos corpos celestes e o mesmo ponto de partida. Uma
  coordenada significa a mesma coisa para todos os jogadores da sala, e nenhum
  mapa precisa ser distribuído.
- **Uma nave pode receber dono.** `<ship>/<settings>` com `of` e `owner` decide
  de qual facção a nave é. A nave de outro jogador entra no seu save como NPC
  legítimo.
- **O jogo entrega o comércio de graça.** Uma nave de outra facção parada no seu
  setor oferece HAIL, TRADE e MISSIONS sem nada construído, e funciona sem o
  outro jogador estar online. A interface de comércio entre jogadores não
  precisa ser inventada.

Então: o servidor guarda o save de cada jogador, empresta a cada sessão e recebe
de volta — injetando as naves dos vizinhos entre uma sessão e outra. Tudo
acontece com o jogo fechado.

O projeto completo está em
[docs/shared-galaxy-server.md](docs/shared-galaxy-server.md), e as medições que o
sustentam em [docs/savegame-format.md](docs/savegame-format.md). O plano de
implementação, em [docs/plan.md](docs/plan.md).

## O que existe agora

Ferramentas para o experimento de comércio — a suposição que decide se o
comércio entre jogadores é conciliável por um servidor:

| | |
|---|---|
| `tools/save_snapshot.py` | copia um savegame para uma pasta de trabalho rotulada |
| `tools/save_diff.py` | diff estrutural entre dois saves, com perfil de ruído aprendível |
| `tools/inject_npc_ship.py` | injeta a nave de outro jogador como NPC legítimo |
| `sgalaxy/savefile.py` | leitura e escrita byte-idêntica de savegame (vendorado) |

Python 3.10+, só biblioteca padrão. Nada para instalar.

```bash
python3 tools/save_snapshot.py caminho/do/save antes
# jogue, comercie, salve
python3 tools/save_snapshot.py caminho/do/save depois
python3 tools/save_diff.py "$(python3 tools/save_snapshot.py --path antes)" \
                           "$(python3 tools/save_snapshot.py --path depois)"
```

O roteiro a seguir é [docs/trade-experiment.md](docs/trade-experiment.md). Ele
precisa de uma pessoa jogando: a simulação não roda sem o cliente.

`tools/save_snapshot.py` e `tools/save_diff.py` nunca escrevem num savegame.
`tools/inject_npc_ship.py` escreve, e exige pasta de saída explícita — mas ainda
não foi verificado contra um save real. **Use só em cópia.**

## Testes

```bash
python3 -m unittest discover -s tests -t .
```

Rodam contra saves sintéticos e provam que as ferramentas fazem o que dizem —
que o diff acha o que mudou e não inventa mudança onde um diff posicional
ingênuo inventaria. Não provam nada sobre o jogo. Toda afirmação sobre o
comportamento do Space Haven depende de save real.

## Confiança

Este projeto vai, em algum momento, pedir que pessoas subam savegame para um
servidor, e isso é um pedido de verdade. O documento de projeto trata disso de
propósito (seção 2.11): servidor auto-hospedável, build público a partir de
fonte público, política de dados escrita antes do código existir, e franqueza
sobre o que não dá para impedir — o jogo roda na máquina do jogador, o save dá
para editar, e por isso o desenho é cooperativo e o servidor confere em vez de
adivinhar.

## Aviso legal

**Space Haven** é um jogo da [Bugbyte Ltd.](https://bugbyte.fi/) Este é um
projeto independente, feito por fã: não é oficial, não tem endosso e não tem
vínculo com ela.

Nada aqui altera o jogo. Veja o [NOTICE](NOTICE).

## Licença

MIT — veja [LICENSE](LICENSE).
