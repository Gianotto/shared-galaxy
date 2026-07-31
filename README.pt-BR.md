# Galáxia Compartilhada

*[Read in English](README.md)*

Um servidor que permite a vários jogadores de Space Haven dividirem a mesma
galáxia, cada um rodando o próprio jogo, **sem que uma linha do código do jogo
seja alterada**.

**O inglês é a versão canônica** deste projeto — a comunidade do jogo é
internacional. As versões em português acompanham, mas podem ficar um passo
atrás.

## Como isso é possível

Space Haven não tem modo headless, a simulação não é determinística, e o jogo é
dono do arquivo enquanto está aberto. Um servidor de multiplayer ao vivo está
fora de alcance, e este projeto não finge o contrário.

O que **está** ao alcance se apoia em fatos medidos carregando saves alterados
no jogo 1.0.4 e olhando o resultado:

- **A seed de criação reproduz a galáxia.** Mesma seed e mesmas opções dão os
  mesmos sistemas, os mesmos corpos celestes e o mesmo ponto de partida — mas
  tripulação diferente e nave diferente. Mesmo universo, gente diferente. Uma
  coordenada significa a mesma coisa para todos, e nenhum mapa precisa ser
  distribuído.
- **Uma nave pode receber dono.** `<ship>/<settings>` com `of` e `owner` decide
  de qual facção a nave é, então uma loja entra no seu setor como NPC legítimo.
- **O jogo entrega o comércio de graça.** Uma nave de outra facção parada no seu
  setor oferece HAIL, TRADE e MISSIONS sem nada construído, e funciona sem o
  outro jogador estar online. **Medido de ponta a ponta:** o `<shipBank>` da
  vendedora registra a venda, e os dois lados batem ao crédito. A interface de
  comércio entre jogadores não precisa ser inventada.

Então: o servidor guarda o save de cada jogador, empresta a cada sessão e recebe
de volta — colocando as lojas dos vizinhos entre uma sessão e outra. Tudo
acontece com o jogo fechado.

O projeto completo está em
[docs/shared-galaxy-server.pt-BR.md](docs/shared-galaxy-server.pt-BR.md), as
medições que o sustentam em
[docs/savegame-format.pt-BR.md](docs/savegame-format.pt-BR.md), o que foi
descoberto desde então em [docs/findings.pt-BR.md](docs/findings.pt-BR.md), e o
plano de implementação em [docs/plan.pt-BR.md](docs/plan.pt-BR.md).

## O que já funciona

**Fase 0 — a custódia.** O servidor guarda o save de cada jogador, empresta por
uma sessão com prazo, e recebe de volta. Não existe save scumming: há uma cópia
só e o servidor sabe qual. Um ciclo completo já rodou contra o jogo de verdade —
entrar, retirar, jogar, devolver — e o mapa da sala mostra quem está onde.

**O experimento de comércio está respondido.** Uma loja montada por estas
ferramentas foi carregada no jogo, apareceu fechada (`Normal (Unexplored)`),
negociou e conciliou: o comprador pagou 70 créditos, a banca da loja ganhou
exatamente 70, e cinco Placas de aço mudaram de lado. Os detalhes estão em
[docs/trade-experiment.pt-BR.md](docs/trade-experiment.pt-BR.md).

### O cliente

```bash
export SGALAXY_URL=https://seu-servidor
python3 tools/sgalaxy.py register "Seu Nome"
python3 tools/sgalaxy.py rooms
python3 tools/sgalaxy.py play SALA        # retira, abre o jogo, devolve — um comando
```

Só biblioteca padrão. O `play` recusa rodar com o Space Haven aberto: escrever
num save com o jogo rodando destrói a partida, e é a única coisa que o cliente
não pode errar nunca.

### As ferramentas

| | |
|---|---|
| `tools/sgalaxy.py` | o cliente: salas, sessões, e o ciclo inteiro |
| `tools/save_diff.py` | diff estrutural entre dois saves, com perfil de ruído aprendível |
| `tools/save_snapshot.py` | copia um savegame para uma pasta de trabalho rotulada |
| `tools/inject_npc_ship.py` | monta a loja de um vizinho dentro de um save |
| `sgalaxy/savefile.py` | leitura e escrita byte-idêntica de savegame (vendorado) |

`save_snapshot.py` e `save_diff.py` nunca escrevem num savegame.
`inject_npc_ship.py` escreve, e exige pasta de saída explícita.

### O servidor

```bash
cp .env.example .env      # defina POSTGRES_PASSWORD
docker compose up -d
```

Traz o próprio Postgres. Escuta só no loopback por padrão: um serviço que aceita
upload de estranhos não deve ficar público porque ninguém leu o compose.

## Testes

```bash
python3 -m unittest discover -s tests -t .          # ferramentas e regras
DATABASE_URL=postgresql://... python3 -m unittest discover -s tests -t .   # e o servidor
```

Rodam contra saves sintéticos e contra um Postgres de verdade — nunca contra
banco falso, porque a garantia que mais importa aqui (um empréstimo aberto por
jogador, que é o que impede duplicação por sessão paralela) é um índice único.
Teste que não pode rodar se declara pulado em vez de passar calado.

Eles provam que as ferramentas fazem o que dizem. Não provam nada sobre o jogo:
toda afirmação sobre o comportamento do Space Haven vem de save real, e o
[docs/findings.pt-BR.md](docs/findings.pt-BR.md) diz qual.

## Confiança

Este projeto pede que pessoas subam savegame para um servidor, e isso é um
pedido de verdade. A seção 2.11 do projeto trata disso de propósito: servidor
auto-hospedável, build público a partir de fonte público, política de dados
escrita antes do código existir, e franqueza sobre o que não dá para impedir.

O jogo roda na máquina do jogador, em arquivos que ele consegue editar. Nada
impede alguém de alterar o próprio save, e o desenho não finge o contrário: ele
é cooperativo, e o servidor **confere** em vez de adivinhar.

## Aviso legal

**Space Haven** é um jogo da [Bugbyte Ltd.](https://bugbyte.fi/) Este é um
projeto independente, feito por fã: não é oficial, não tem endosso e não tem
vínculo com ela.

Nada aqui altera o jogo — é leitura e escrita de savegame, o que jogadores fazem
à mão há anos. Veja o [NOTICE](NOTICE).

## Licença

MIT — veja [LICENSE](LICENSE).
