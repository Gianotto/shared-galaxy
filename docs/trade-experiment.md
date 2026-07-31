# Experimento de comércio

O experimento que decide a fase 3 do projeto. Está na seção 2.12 do documento de
projeto como a suposição mais cara ainda não testada:

> **comércio conciliável.** Vimos o TRADE aparecer e funcionar. Não medimos como
> a transação fica registrada no save, nem se dá para reconstruí-la na devolução.

Este documento é o roteiro para responder isso. Ele precisa de você jogando: a
simulação não roda sem o cliente, então não há como automatizar.

Enquanto ele não estiver respondido, a fase 3 é especulação. As fases 0, 1 e 2
não dependem dele e podem andar em paralelo.

---

## Antes de começar

**Trabalhe sempre em cópia.** Nenhuma ferramenta deste repositório escreve num
save de entrada, mas o jogo escreve. Faça uma partida dedicada ao experimento e
não use um save que te importe.

Anote a versão do jogo. Tudo aqui foi levantado no **1.0.4**; se a sua for
outra, diga no resultado, porque a resposta pode não valer.

Onde ficam os saves:

| Sistema | Caminho |
|---|---|
| Windows | `%APPDATA%\..\LocalLow\Bugbyte\Space Haven\savegames\` |
| Linux (nativo) | `~/.config/unity3d/Bugbyte/Space Haven/savegames/` |
| Linux (Steam via snap) | `~/snap/steam/common/.local/share/Steam/steamapps/common/SpaceHaven/savegames/` |
| Linux (Proton) | `.../steamapps/compatdata/979110/pfx/drive_c/users/steamuser/AppData/LocalLow/Bugbyte/Space Haven/savegames/` |

As ferramentas aceitam a pasta do save, a pasta que a contém, ou o arquivo
`game` direto.

---

## Atalho: os saves de teste já existem

Os saves das pesquisas anteriores servem direto, e economizam a montagem de dois
experimentos.

| Save | Serve para | Por quê |
|---|---|---|
| `Beyond Space` | **E2** | 1.543 créditos no `playerBank` e cinco naves de NPC com `<shipBank>` próprio (`ca` de 785 a 6.901). Dá para comprar. |
| `ship17 sem visao` | **E3** | já é o cenário montado: `CS DASHERS SCRAPPER` (sid=55) é NPC Civil completo, com `<asi>`, `<markers>` e `<shipBank ca="12309">`, e o `hostmap` está exatamente no desenho da seção 2.5 — `accessTrade="true"` com `accessVision="false"` e `accessShip="false"`. |

**Atenção no `ship17`: o `playerBank` está com `ca="0"`.** Sem crédito não dá
para comprar, então o experimento ali começa **vendendo**. Não é problema — a
venda responde a mesma pergunta e ainda testa uma coisa a mais, que é se o jogo
respeita o `ca` da nave como teto do que ela consegue pagar. Se quiser comprar
também, dê crédito ao jogador antes pelo editor de savegame.

Trabalhe em cópia dos dois, não neles.

## E1 — O piso de ruído

**Sem isto, nenhum experimento seguinte é interpretável.** Um save gravado duas
vezes já difere em milhares de pontos: relógios, posição de tripulante, fase
orbital, contadores. Se você não medir esse chão primeiro, a compra de dez
minérios vai estar enterrada no meio dele.

São **duas** medidas, e a diferença entre elas é informação por si só.

### E1a — o piso puro

Quanto muda num ciclo de salvar, sem nada acontecer no jogo.

1. Abra o jogo, carregue a partida, salve **imediatamente**, saia para o menu.
2. `python3 tools/save_snapshot.py CAMINHO/DO/SAVE E1a-1`
3. Carregue de novo, salve imediatamente de novo, saia.
4. `python3 tools/save_snapshot.py CAMINHO/DO/SAVE E1a-2`

```bash
python3 tools/save_diff.py \
    "$(python3 tools/save_snapshot.py --path E1a-1)" \
    "$(python3 tools/save_snapshot.py --path E1a-2)" \
    --learn-noise experiments/noise-puro.json
```

### E1b — o piso realista

O E2 não vai ser um ciclo puro: negociar leva tempo de jogo, a tripulação anda,
os módulos produzem. O ruído que o E2 vai carregar é este, e é maior.

Mesma coisa, mas **deixe o jogo correr mais ou menos o tempo que uma negociação
leva** — um minuto de relógio, sem dar ordem nenhuma — antes de salvar.

```bash
python3 tools/save_diff.py \
    "$(python3 tools/save_snapshot.py --path E1b-1)" \
    "$(python3 tools/save_snapshot.py --path E1b-2)" \
    --learn-noise experiments/noise.json
```

O `noise.json` do E1b é o que os outros experimentos usam. O `noise-puro.json`
fica de referência: a diferença entre os dois é exatamente o que "o tempo
passar" custa, e é o número que a conferência da seção 2.7 vai ter que tolerar.

**O que anotar:** quantas mudanças brutas apareceram e em que áreas. Esse número
é interessante por si só — ele diz o quanto o save se mexe sozinho, o que a
conferência da seção 2.7 vai ter que tolerar.

**Cuidado:** se o `--learn-noise` disser que gravou zero assinaturas, o jogo não
salvou entre um snapshot e outro. Confira com `--list`: dois snapshots com o
mesmo digest são idênticos.

**Refine o perfil.** Uma passada só de E1 aprende pouco. Repita duas ou três
vezes, com intervalos diferentes de jogo entre os saves, sempre acumulando num
perfil novo, e use o maior. Ruído de menos deixa lixo na resposta; ruído de mais
esconde a resposta.

---

## E2 — Comércio com NPC nativo

A pergunta: **a transação fica registrada como evento, ou só como estado final?**

Precisa de uma nave de outra facção parada no seu setor. Ela oferece HAIL, TRADE
e MISSIONS sem nada construído (seção 1.9).

1. Salve com a nave já no setor, antes de qualquer contato. Snapshot `E2-antes`.
2. No jogo, faça **uma compra só, de um item só, em quantidade redonda**. Anote:
   o que comprou, quanto, por quantos créditos, e de qual nave.
3. Salve. Snapshot `E2-depois`.
4. Compare:

   ```bash
   python3 tools/save_diff.py \
       "$(python3 tools/save_snapshot.py --path E2-antes)" \
       "$(python3 tools/save_snapshot.py --path E2-depois)" \
       --noise experiments/noise-puro.json --noise experiments/noise.json \
       --focus economy --verbose
   ```

   E **de novo sem `--noise`**, para conferir que o filtro não comeu parte da
   transação. As duas saídas juntas é que respondem.

**O que responder:**

- os créditos saíram do `playerBank`? o valor bate com o que você pagou?
- a carga apareceu num `<inv>` da sua nave?
- **o `<shipBank>` da nave vendedora mudou?** É a pergunta mais importante das
  cinco. Se ele registra a venda, o servidor consegue conciliar comparando com o
  banco que ele mesmo montou.
- existe algum nó de histórico, log ou recibo em algum lugar? Rode uma vez sem
  `--focus` para varrer o save inteiro e procure qualquer coisa que pareça
  registro de transação.

---

## E3 — Comércio com nave injetada

Agora com o `<shipBank>` que **nós** montamos, com estoque e créditos conhecidos.
É a configuração real do projeto.

```bash
python3 tools/inject_npc_ship.py --help
```

1. Injete uma nave numa cópia do save, com estoque conhecido e `ca` conhecido.
2. Snapshot `E3-antes`. Abra o jogo e confirme que a nave está lá e oferece TRADE.
3. Compre dela. Salve. Snapshot `E3-depois`. Compare igual ao E2.

**O que responder:**

- o estoque da nave injetada diminui, e isso **persiste** no save?
- o jogo respeita o `ca` como limite do que ela consegue comprar de você?
- o comportamento é igual ao do NPC nativo do E2, ou a nave injetada é tratada
  de forma diferente?

---

## E4 — Várias transações

A pergunta: **dá para distinguir três compras de uma compra grande?** É o que
decide se a conciliação é por transação ou por delta líquido.

Numa sessão só, sem salvar no meio: compre 10 de A, compre 10 de A de novo,
compre 5 de B, venda 20 de C. Anote a ordem. Salve, snapshot, compare.

Se o save só guardar o estado final, a resposta é que a conciliação é por delta
líquido — o que **basta**, porque o servidor montou o estado inicial e sabe
exatamente de onde partiu.

---

## E5 — Procedência

A pergunta que não está no documento de projeto e apareceu ao montar este
roteiro: **com dois vizinhos no mesmo setor, dá para saber de quem veio o que?**

Se o save só registra "o jogador ganhou 10 de minério", e havia duas naves
vendendo minério, o servidor não sabe quem creditar. Isso quebra a conciliação
com mais de um vizinho, que é o caso normal de uma sala.

Injete **duas** naves no mesmo setor, cada uma com um recurso que o jogador não
possui e que a outra também não tem — recursos marcadores. Compre das duas.
Compare.

Se a procedência não for inferível pelo save, a consignação precisa carregar o
marcador: cada vizinho expõe um conjunto disjunto de recursos, ou a conciliação
vira aproximação e o desenho precisa admitir isso.

---

## O que cada resultado implica

| Resultado do E2/E3 | Implicação |
|---|---|
| O `<shipBank>` persiste a venda | **Conciliação por delta líquido. A fase 3 sai como está no documento de projeto.** O servidor montou o banco, sabe o estado inicial, e a diferença é a transação. |
| O `<shipBank>` não persiste | A venda não é reconstruível pelo lado da nave. Resta inferir pelo `playerBank` e pela carga — o E5 vira obrigatório e cada vizinho passa a expor recursos marcadores disjuntos. |
| Nem estado final aproveitável | A fase 3 muda de natureza. O comércio nativo vira sabor, não economia, e a troca real acontece por consignação fora do jogo: o vizinho pede pela web, o servidor entrega no porão na retirada seguinte. Menos elegante, e não depende de nada disto. |

---

## Resultados

*A preencher conforme os experimentos forem rodando. Registre o que mediu, não o
que concluiu — a conclusão muda, a medida fica.*

### E1a — piso puro (medido em 2026-07-31, save `Beyond Space`)

Dois ciclos de carregar e salvar, **com o jogo pausado**, sem nenhuma ordem.

- **11.434 mudanças brutas**, que viram **103 assinaturas** de forma
- 11.432 delas carregam um id no caminho
- o jogo **recria os objetos de dentro das células ao carregar**: o `idCnt` de
  cada nave avança milhares (a nave 2 foi de 20.417 para 22.913), 676 `<l>`
  somem e 676 aparecem, 625 trocam de `id`
- áreas: `game/ships/ship/e/l` domina; por atributo, `hf` (3.676), `atm`/`atm2`
  (1.685), `x`/`y` (1.559), depois `id`, `rot`, `m`, `invw`, `fg`
- fora das naves, só sete formas mudam sozinhas, entre elas
  `masterData/@idCounter`, `space/@idCnt` e `hostmap/map/l @relationship` — a
  relação entre facções decai sozinha, como a seção 1.8 diz

**Pausado não quer dizer parado.** Ninguém estava simulando; o jogo estava
realocando ao carregar. É o que torna inútil qualquer identidade de objeto
dentro de `<e>` entre uma sessão e outra — inclusive para o servidor.

**Cuidado ao usar este perfil.** Sete das 103 assinaturas tocam a economia,
entre elas `feat/prod/inv/s @inStorage` (o buffer de uma máquina produzindo) e
`<inv>` inteiros aparecendo e sumindo. Isso significa que **o perfil pode
silenciar parte de uma transação de verdade.** No E2, rode o diff **duas vezes,
com e sem `--noise`**, e compare.

### E1b — piso realista (medido em 2026-07-31, mesmo save)

Dois ciclos com cerca de um minuto de jogo correndo, sem ordem nenhuma.

- **23.863 mudanças brutas**, que viram **323 formas** — o dobro do ciclo puro
- **228 formas** só aparecem quando o jogo roda; 8 só aparecem no ciclo puro
- o que o tempo traz: inventário de tripulante (arma, armadura), nutrição
  (`props/Food/stored` com carbs, fat, protein, toxins, vitamins), buffers de
  máquina em produção (`feat/prod/cinv`), itens em trânsito (`items/i @dstId`,
  `@grndTime`), e alvos de movimento (`targetX`, `targetY`)

**Use os dois perfis somados**, porque nenhum vê tudo:

```bash
--noise experiments/noise-puro.json --noise experiments/noise.json
```

### O filtro é seguro para a pergunta do E2

Conferido contra os dois perfis: os quatro sinais de que a resposta depende
**passam limpos**, nenhum deles é ruído.

| Sinal | Estado |
|---|---|
| `playerBank @ca` | passa |
| `shipBank @ca` | passa |
| pilha de armazém `@inStorage` | passa |
| pilha de armazém `@elementaryId` | passa |

**O risco que resta é um só:** `feat/inv|added` é ruído, ou seja, um `<inv>`
inteiro nascendo num armazém fica silenciado. Então **compre um recurso que a
nave já tenha em estoque** — assim a mudança é quantidade numa pilha existente,
que passa, em vez de um nó novo, que não passa.

### E2 — comércio com NPC nativo (medido em 2026-07-31, save `Beyond Space`)

Comprado: **1 Hyperium (elem 172) por 386 créditos**, da `MFB STRONGHOLD`
(sid=4336, Mercante).

**A resposta é sim, e é limpa. O `<shipBank>` registra a venda.**

| | antes | depois | delta |
|---|---|---|---|
| `playerBank @ca` | 1543 | 1157 | **−386** |
| `shipBank @ca` da sid=4336 | 6901 | 7287 | **+386** |

Os dois lados batem ao crédito. A mercadoria também: a vendedora foi de 3 para 2
de Hyperium, e o jogador ganhou 1.

**Não existe registro de transação em lugar nenhum.** Nenhum log, recibo ou
histórico — só o estado final dos dois lados. Como o servidor é quem monta o
`<shipBank>` do retrato, ele sabe o estado inicial exato, e a diferença é a
transação. **Conciliação por delta líquido, e a fase 3 sai como está no
documento de projeto.**

**Mas a mercadoria estava voando.** No momento do save o Hyperium **não tinha
chegado**: a pilha de destino do jogador estava com `onTheWayIn="1"` e
`inStorage` inalterado, e havia um `<i eid="172">` no `<items>` da nave, com
`mo="BeingMoved"` e `dstId`. O estoque da vendedora já tinha sido debitado.

Isso é regra de conciliação, não curiosidade: **quem somar só `inStorage` vê a
carga sumir.** O servidor tem que contar três lugares — `inStorage`,
`onTheWayIn`, e os itens em voo — ou vai acusar o jogador de perder mercadoria
que o próprio jogo ainda está entregando.

O filtro de ruído se comportou: 19.651 mudanças brutas viraram 46 com os dois
perfis, e 113 sem eles. Os quatro sinais que importavam sobreviveram, como
previsto. O ruído restante era salvagem de destroço acontecendo em paralelo
(restos de casco indo para os ônibus) e máquinas consumindo Energium e minério.

### E3 — comércio com nave injetada

### E4 — várias transações

### E5 — procedência

### Conclusão
