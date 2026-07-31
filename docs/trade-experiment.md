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

1. Abra o jogo, carregue a partida, **não faça nada**, salve.
2. Tire o primeiro snapshot:

   ```bash
   python3 tools/save_snapshot.py CAMINHO/DO/SAVE E1-antes
   ```

3. Carregue de novo, espere alguns segundos de jogo, salve de novo.
4. Segundo snapshot e aprendizado do ruído:

   ```bash
   python3 tools/save_snapshot.py CAMINHO/DO/SAVE E1-depois
   python3 tools/save_diff.py \
       "$(python3 tools/save_snapshot.py --path E1-antes)" \
       "$(python3 tools/save_snapshot.py --path E1-depois)" \
       --learn-noise experiments/noise.json
   ```

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
       --noise experiments/noise.json --focus economy --verbose
   ```

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

### E1 — piso de ruído

- versão do jogo:
- mudanças brutas entre dois saves sem ação:
- áreas mais barulhentas:
- assinaturas no perfil:

### E2 — comércio com NPC nativo

- o que foi comprado, quanto, por quanto:
- `playerBank` mudou?
- `<inv>` da nave do jogador mudou?
- `<shipBank>` do vendedor mudou?
- algum registro de transação em qualquer lugar do save?

### E3 — comércio com nave injetada

### E4 — várias transações

### E5 — procedência

### Conclusão
