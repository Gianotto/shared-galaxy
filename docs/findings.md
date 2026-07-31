# Medições novas

O que foi medido depois que `savegame-format.md` e `shared-galaxy-server.md`
foram escritos, ao construir as ferramentas e rodá-las contra save real do jogo
1.0.4. Cada item diz de onde veio a evidência.

Duas destas correções mudam código de quem for implementar o servidor. Elas
foram aplicadas nos documentos originais; o resto está aqui porque não cabia lá.

Os saves usados: `ship17 sem visao` (o teste de névoa, 3 naves) e `Beyond Space`
(9 naves), mais `New haven-1`.

---

## 1. Um corpo celeste tem dois ids, e só um serve para a sala

**É a correção mais cara deste documento.** Todo corpo celeste tem:

| Atributo | O que é | Escopo |
|---|---|---|
| `id` | id de objeto do mapa estelar, tirado de `starmap/@objectIdCounter` | **local ao save** |
| `celeid` | id do corpo celeste, derivado da seed | **igual em toda a sala** |

E **`starmap/@pa` aponta para o `id`, não para o `celeid`.**

Medido em `ship17`: `@pa=226` casa com `<l type="Asteroid" id="226" celeid="1689">`,
e não existe nenhum corpo com `celeid=226` no save. Em `Beyond Space`: `@pa=231`
casa com `<l id="231" celeid="0">`. Nos dois casos o corpo apontado é onde a
frota `<f isPlayer="true">` realmente está.

Consequência de projeto, e ela é séria: a seção 1.4 diz que "uma coordenada e um
id de corpo celeste significam a mesma coisa para todos os jogadores da sala".
Isso vale para `celeid` e **não** vale para `id`. O servidor tem que falar
`celeid` ao dizer onde um jogador está, e traduzir para o `id` local na hora de
escrever `@pa` no save de cada um. Trocar os dois coloca o vizinho no setor
errado, e o erro é silencioso.

`starmap/@sys`, esse sim, é o `systemId` direto — conferido nos três saves.

Isso corrige também um comentário do `compare_galaxy.py` no repositório do
editor, que registra `sys` e `pa` como "contadores internos — não batem com a
quantidade de sistemas nem de corpos". Não batem mesmo com contagem nenhuma,
porque não são índices: são referências.

## 2. `<ship fog="true">` — faltava na receita

A seção 2.5 manda `fg="0"` em cada célula, `unex="1"` e `forceRoof="1"`. Há um
quarto atributo, na raiz `<ship>`.

Medido em 12 naves de dois saves:

| Dono | `fog` | `unex` | `forceRoof` |
|---|---|---|---|
| Player (2 naves) | `false` | ausente | ausente |
| NPC (9 naves) | `true` | `1` | `1` na maioria |

A única exceção é uma nave Mercante com `fog="false"`, provavelmente já abordada
— o que confirma a leitura de que o atributo marca "esta nave já foi explorada".

Importa porque a nave de origem de um retrato é sempre a nave do dono, que é
sempre `fog="false"`. Sem corrigir, o retrato nasce diferente de todo NPC
autêntico do save.

## 3. A carga negociável não mora no `<shipBank>`

O `<shipBank>` guarda **crédito** (`ca`) e **regra de preço** (`<markup>`,
`<discount>`). A carga fica em pilhas dentro dos `<inv>` de armazém:

```xml
<inv>
  <s elementaryId="2053" inStorage="4" onTheWayIn="0" onTheWayOut="0"/>
</inv>
```

O atributo é `elementaryId`, não `elementId`. Existem também `<cinv>`, `<pinv>`,
`<stored>` e `<items>`, ainda não separados.

Isso é exatamente o que o E3 do experimento de comércio vai medir: qual dos dois
o jogo lê e escreve numa transação.

## 4. O `hostmap` é indexado por nome de facção

92 linhas em `ship17`, cada uma um par, e **sem id nenhum**:

```xml
<l s1="Player" s2="Civilian" stance="Friendly" relationship="74" patience="100"
   accessTrade="true" accessShip="false" accessVision="false"
   accessServices="true" accessHire="true" s1SusOfS2="false" s2SusOfS1="false"
   playerOwesSettlement="0" settlementArrivedTurn="0" awareOfCrew="false"/>
```

`s1` e `s2` são **nomes** ("Player", "Civilian", "Merchant", "Military"), não os
ids numéricos de facção. Há mais permissões do que a seção 1.8 lista:
`accessServices`, e os campos `stance`, `patience`, `s1SusOfS2`, `s2SusOfS1`,
`awareOfCrew`.

O estado do `ship17` é precisamente o desenho da seção 2.5 item 8:
`accessTrade="true"` com `accessVision="false"` e `accessShip="false"`.

## 5. `id="-1"` quer dizer "sem id"

Todo elemento `<e>` dentro de uma nave — as centenas de peças de que ela é feita
— vem com `id="-1"`. Não é identidade, é sentinela.

Custou um defeito real: a primeira versão do `save_diff.py` tratava como
identidade, e dois saves que diferiam em 6 atributos produziram 366 diferenças,
358 delas fantasma. Quem for escrever qualquer coisa que case elementos entre
dois saves precisa saber disso.

Também vale a regra geral que saiu dali: uma identidade só serve se for única
entre os irmãos.

## 6. `hdsid` é referência à nave

No `<ai>` de cada tripulante, colado no `hsid` já conhecido, existe `hdsid`. Nas
duas naves onde aparece, o valor é sempre o `sid` da própria nave (6 ocorrências
numa, 1 na outra).

Quem copiar uma nave precisa renumerar `sid`, `homeSid`, `hsid` **e** `hdsid`.

## 7. O jogo recria os objetos de dentro das células ao carregar

Medido no E1a: dois ciclos de carregar e salvar `Beyond Space`, **com o jogo
pausado**, sem uma ordem dada, produzem **11.434 diferenças**.

Elas não são simulação. São realocação: o `idCnt` de cada nave avança milhares
de unidades por load (a nave 2 foi de 20.417 para 22.913), 676 `<l>` de dentro
de `<e>` somem e 676 aparecem, e 625 trocam de `id`. Por atributo: `hf` (3.676),
`atm`/`atm2` (1.685), `x`/`y` (1.559), `rot`, `m`, `invw`, `fg`.

Fora das naves, só sete formas mudam sozinhas, entre elas `masterData/@idCounter`,
`space/@idCnt` e `hostmap/map/l @relationship` — a relação entre facções decai
sozinha, o que confirma a seção 1.8 pelo lado da medição.

**Consequência para o servidor:** nenhum id de objeto de dentro de uma nave
sobrevive a um ciclo de sessão. O que o servidor guardar sobre o conteúdo de uma
nave tem que ser descrito por forma e conteúdo — que recurso, quanto, em que
tipo de módulo — nunca por id. Vale para a conciliação da seção 2.7 e para
qualquer ideia futura de rastrear objeto.

**Consequência para ferramenta:** um perfil de ruído baseado em caminho exato é
inútil, porque os caminhos aprendidos não existem na rodada seguinte. As 11.434
diferenças reduzem a **103 formas** quando os ids saem do caminho, e aí o perfil
transfere. É como o `save_diff.py` faz.

## 8. Uma transação é assíncrona: a carga viaja de ônibus

Medido no E2. O jogador comprou 1 Hyperium por 386 créditos de uma nave
Mercante. Os créditos se movem na hora e batem exatamente nos dois lados
(`playerBank` −386, `shipBank` da vendedora +386), e o estoque da vendedora já
sai debitado (3 → 2).

**A carga, não.** No momento do save ela estava em trânsito:

- a pilha de destino no armazém do comprador tinha `onTheWayIn="1"` e
  `inStorage` **inalterado**
- havia um `<i eid="172" mo="BeingMoved" dstId="...">` no `<items>` da nave
- os ônibus (`<crafts>`) carregavam manifestos `<o a="QUANTO" e="RECURSO"
  sid="NAVE_DESTINO">`

O jogo não teleporta mercadoria: um ônibus vai buscar. Entre fechar o negócio e
a carga encostar no armazém passa tempo de jogo, e um save tirado nesse meio —
que é o caso normal, porque autosave não espera — pega o estado partido.

**Consequência para a conciliação (seção 2.7):** somar `inStorage` é errado. O
servidor precisa contar os três lugares — `inStorage`, `onTheWayIn` e os itens
em voo — ou vai ver carga sumir e acusar de perda o que o próprio jogo ainda
está entregando. Vale também para a devolução: uma sessão pode terminar com
mercadoria comprada e não entregue.

## 9. `<markers>` não é necessário para comerciar

A seção 1.7 lista `<markers>` (pontos de atracagem) como um dos três nós que
naves de NPC costumam ter e a do jogador não. Depois do item 8 — a carga viaja
de ônibus — a pergunta virou séria: sem ponto de atracagem, o ônibus entrega?

Entrega. A `MFB STRONGHOLD`, a nave que vendeu o Hyperium do E2, **não tem
`<markers>`**, e a transação foi executada e entregue. Medido em 9 naves:

| Nave | markers | shipBank |
|---|---|---|
| MFB STRONGHOLD (Mercante) | não | **sim** |
| CS DASHERS SCRAPPER (Civil) | sim (8) | sim |
| ACS ZAHKUL (Android) | sim (6) | sim |
| CB DUDDE (Civil) | sim (4) | sim |
| MAS MARGIN CALL (Militar) | sim (4) | sim |
| CNHS MORNING STAR (Cultista) | sim (4) | não |

Não há correlação com `<shipBank>` nos dois sentidos: existe nave com banca e
sem markers, e nave com markers e sem banca. O que manda para comércio é a
banca.

O formato, quando existe, é `<m m="8" x="11" y="11"/>` — coordenada dentro da
nave. Por isso clonar de um doador não serviria: os pontos são do casco de
quem os tem.

**Para o construtor de retratos:** não copiar `<markers>` é seguro.

## 10. A névoa não sobrevive a um load, e o `hostmap` não fecha o interior

**Refuta a seção 1.8 e o item 6 da receita 2.5.** Medido no E3, com nave montada
pela ferramenta e carregada no jogo.

A ferramenta gravou exatamente o que a receita manda:

| | gravado pela ferramenta | depois de o jogo carregar |
|---|---|---|
| `<ship fog>` | `true` | **`false`** |
| `<ship unex>` | `1` | **removido** |
| `<ship forceRoof>` | `1` | **removido** |
| células com `fg` | 616 em `0` | **616 em `191`** |

O jogo não só ignorou: ele **apagou** os dois atributos e restaurou cada célula
ao valor exato que ela tinha na nave de origem. Existe outra fonte de verdade
para a névoa, e ela não é nenhum desses campos. Não achamos qual — o `<roof>` da
nave injetada é estruturalmente igual ao de uma nave de NPC que continua
escondida.

E o `hostmap` **não** é o que manda, ao contrário do que a seção 1.8 conclui:

```
antes   Player x Civilian  accessTrade=true  accessShip=false  accessVision=false
depois  Player x Civilian  accessTrade=true  accessShip=false  accessVision=false
```

`accessVision="false"` atravessou o load intacto **e o interior está visível na
tela** — teto aberto, tripulação à mostra. A afirmação "desligar `accessVision`
fecha o interior na hora" não se sustenta.

**O que isso quebra e o que não quebra.** A proteção *econômica* da seção 2.6
continua inteira: só o que foi consignado está na nave, então só isso pode ser
comprado, e o painel de comércio mostrou exatamente o estoque montado. O que cai
é a privacidade *visual* — o vizinho vê a planta e a tripulação do retrato.

**Não é a relação entre facções.** Foi a primeira hipótese e o próprio save a
derruba: `CB DUDDE` e `VIZINHO E3` são as duas do lado `Civilian`, no mesmo
save, sob a mesma linha do `hostmap` — e a autêntica continua escondida enquanto
a injetada foi revelada. Mais: o Escravagista está em `Enemies` com relação −82
e está **revelado**, enquanto a Civil a −3 está escondida.

**O que as reveladas têm em comum é contato.** Nas dez naves do save:

| Estado | Naves |
|---|---|
| revelada (`fog=false`, sem `unex`, `fg` 191/255) | a do jogador; a que ele está sucateando; a Mercante com quem negociou no E2; a injetada |
| escondida (`fog=true`, `unex=1`, `forceRoof=1`, `fg=0`) | as quatro com que nunca houve contato |

A leitura que sobra: `fog` é **estado de exploração**, mantido pelo jogo a partir
de alguma coisa que não é nenhum dos campos que a receita mexe, e escrever nele
de fora não cola. O retrato de um vizinho nasce condenado, porque a nave de
origem é a nave *dele* — sempre explorada.

**Próximo teste, e é barato:** montar um retrato a partir de uma nave que já
seja NPC não explorado (a `CS DASHERS SCRAPPER` do `ship17`, com `fg=0`) em vez
de uma nave de jogador. Se ele continuar escondido, a regra é "a névoa vem da
história da nave de origem e não se falsifica", e o projeto tem uma restrição
real a aceitar.

**A pergunta sobre abordar tem resposta, e é melhor que uma trava.** Não existe
bloqueio mecânico: dá para entrar numa nave sem permissão, e dá para pegar item
numa nave ou estação alheia. O que acontece é que isso **declara guerra** e
derruba a reputação com aquela facção. (Conhecimento de jogo, não medido aqui; a
máquina disso está toda no `hostmap` e foi conferida — ver item 11.)

Para o projeto isso é bom em três camadas:

1. **O dissuasor é nativo e de graça.** O projeto não precisa inventar
   anti-roubo. Roubar o vizinho custa uma guerra.
2. **A prova fica gravada e o servidor enxerga.** Ele entregou o save e recebe de
   volta: um `stance` virando `Enemies`, uma queda de `relationship`, um
   `awareOfCrew="true"` são legíveis na devolução. É exatamente a "conferência,
   não adivinhação" da seção 2.7 — o roubo não é impedido, é **registrado**.
3. **A exposição visual do item 10 encolhe.** Ver a planta do vizinho sem poder
   levar nada de graça é estética, não brecha.

## 11. O `hostmap` é por facção, não por vizinho — e isso limita a sala

Consequência da mecânica de guerra acima, e não está no documento de projeto.

O retrato de um vizinho recebe uma facção do conjunto fixo do jogo. Neste save
existem dez lados: `Pirate`, `Slaver`, `Android`, `Civilian`, `Cultist`,
`Merchant`, `Military`, `HavenFoundation`, `FlamingSwords`, `NotSet`. A tabela de
relações é indexada por **par de lados** (item 4), nunca por nave.

Então:

- abordar o retrato de um vizinho declara guerra ao **lado inteiro** — a todos os
  NPCs autênticos daquele lado, e a **qualquer outro vizinho** que tenha caído na
  mesma facção
- o caminho inverso também vaza: um jogador que entre em guerra com os Civis por
  motivo normal de jogo passa a estar em guerra com o vizinho que representamos
  como Civil
- as permissões que o servidor liga na retirada (`accessTrade` etc.) valem para o
  lado inteiro, não só para o retrato

A seção 1.8 chama a tabela de "painel de controle do servidor sobre o que um
jogador pode fazer com o retrato do outro". É verdade **na granularidade de
facção**, e só.

**Limite prático de sala.** A seção 1.3 conclui, pelos contadores de id, que "não
há limite prático de jogadores por sala". Continua valendo para o save. Mas para
**vizinhos visíveis no mesmo setor** o limite é o número de facções distintas —
cerca de nove — porque a partir daí dois vizinhos compartilham lado e deixam de
ser distinguíveis pelo `hostmap`. Vizinhos em setores diferentes não competem por
isso.

A identidade visual continua vindo do `sname` (seção 1.10). O que colide é o
controle de permissão e a propagação de guerra, não o nome.

## 12. Um armazém tem capacidade, e o excesso não é ofertado

O retrato foi montado com 40 Produtos químicos e 30 Placas de aço, e a ferramenta
pôs os dois no **mesmo** armazém — 70 unidades. O painel de comércio do jogo
ofereceu 40 e **26**, ou seja 66 no total.

66 é a capacidade aparente do armazém, e o que passa dela fica no arquivo mas não
é ofertado. A venda debitou corretamente do total real (30 → 25), então o excesso
existe, só não está à venda.

**Para o construtor de retratos:** consignar sem respeitar capacidade entrega ao
vizinho menos do que o dono ofereceu, em silêncio. O estoque precisa ser
distribuído por armazém, com teto por armazém.

## 13. Miudezas

- **`balanced.bin`** existe na pasta do save e não está documentado. Os
  documentos citam `stats.bin` e `timeline.xml`; `timeline.xml` não apareceu em
  nenhum dos saves examinados.
- **`info/@version` é `21`**, a versão do formato do save — não a versão do jogo.
  Um save de 1.0.4 traz `<info version="21" date="3289920"
  realTimeDate="1785467969073"/>`. Se o servidor for ancorar versão por sala,
  como o plano recomenda, é este número que ele tem para trabalhar.
- **`fg` só existe em parte dos `<e>`.** Em `ship17`, 392 de 737 numa nave, 1536
  de 3501 noutra. Névoa é por célula de piso, não por elemento.
- **`playerBank`** tem a mesma forma do `<shipBank>`: `<playerBank s="Player"
  ca="0" cr="0" slp="10064" blp="9856"/>`.
- **Um mesmo `sid` pode aparecer duas vezes** na varredura de naves de um save
  (`sid=1459` em `Beyond Space`, uma vez com 0 tripulantes e outra com 6). Não
  investigado; provavelmente a mesma nave listada no setor e num arquivo de
  `ships/`.
