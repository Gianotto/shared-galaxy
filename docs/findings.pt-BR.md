# Medições novas

*[Read in English](findings.md)*

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

**E a entrega tem duas etapas, não uma.** O ônibus larga a mercadoria **em
caixas no chão da nave**. Só depois um tripulante, um robô ou o jogador leva
para o depósito — *e só se houver espaço*. Sem espaço, a caixa fica no chão.

Confere com a estrutura: `<items>/<i>` tem `x`, `y` e **`grndTime`** — tempo de
chão. Na nave do jogador havia 7 caixas paradas, agrupadas na mesma coordenada,
com `grndTime` perto de 480 e nenhuma com `mo="BeingMoved"`. Não estavam
viajando: estavam largadas.

**Consequência para a conciliação (seção 2.7):** somar `inStorage` é errado, e
não é um erro transitório que se resolve sozinho. O servidor precisa contar
**três lugares** — `inStorage`, `onTheWayIn` e as caixas em `<items>` — porque
com o depósito cheio a mercadoria pode morar no chão pelo resto da partida.
Quem somar só a prateleira acusa de perda o que está a três metros dela.

Vale também para a devolução: uma sessão pode terminar com mercadoria comprada,
entregue e nunca guardada.

**Medido de forma limpa no E6.** A vitrine vendeu 5 Produtos químicos. No save
do comprador: **+1 em `inStorage` e +4 em caixas no `<items>`**. Os cinco estão
lá, em dois lugares. Contar só a prateleira erra por 80% nessa transação.

## 8b. A conciliação é por delta líquido, e o E4 sai por tabela

A sessão do E6 teve várias transações — o painel permite até quatro por
negociação — e o save guardou **só o estado final**. Nenhum log, nenhuma ordem,
nenhum recibo, nenhum vestígio de quantas foram ou em que ordem.

É exatamente o que a fase 3 supõe e o que o E4 do roteiro ia perguntar. O
servidor monta o `<shipBank>` e os armazéns do retrato, então conhece o estado
inicial ao número; a diferença na devolução é a transação, sem precisar
reconstruir passo a passo.

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

## 10. A névoa vem da nave de origem, e o `hostmap` não fecha o interior

Duas rodadas no jogo, mudando **uma** variável — a nave que serve de origem para
o retrato. Mesmo destino, mesma facção, mesma linha do `hostmap`, tudo mais
igual.

| Origem | Gravado pela ferramenta | Depois do load | Na tela |
|---|---|---|---|
| `HSS PERSEUS`, nave **de jogador** (`fg=191`, explorada) | `fog=true unex=1 forceRoof=1`, 616 células em `fg=0` | `fog=false`, `unex` e `forceRoof` **apagados**, 616 células de volta em `fg=191` | teto aberto, tripulação à mostra |
| `CS DASHERS SCRAPPER`, **NPC autêntico** (`fg=0`, nunca explorada) | `fog=true unex=1 forceRoof=1`, 1536 células em `fg=0` | **idêntico** | `State: Normal (Unexplored)`, silhueta cinza |

**A névoa é falsificável quando a origem já é não explorada, e não é quando a
origem é explorada.** O jogo tem outra fonte de verdade e reconstrói a partir
dela — restaurando, no caso do jogador, exatamente os `fg=191` de origem.

**Onde a fonte não está:** não é `fog`, `unex`, `forceRoof` nem o `fg` das
células, porque escrevemos os quatro nos dois casos. Não é o `hostmap`:
`accessVision="false"` atravessou o load intacto nas duas rodadas. Não é a
relação entre facções — no mesmo save, uma Civil autêntica sob a mesma linha
continua escondida enquanto o Escravagista em `Enemies` a −82 está revelado. E
não é nenhum atributo da raiz `<ship>`: os dois retratos têm exatamente o mesmo
conjunto de atributos. As únicas diferenças estruturais são `gasWarnings` de um
lado e `markers` do outro, nenhuma com cara de marca de exploração.

**A consequência de projeto é séria, e não é técnica.** O retrato de um vizinho
seria a nave *dele* — e a nave de um jogador é, por definição, explorada. Pela
regra medida, ela nasce revelada e não há como esconder. Restam dois caminhos, e
a escolha é de desenho:

1. **Aceitar a exposição visual.** O vizinho vê a planta e a tripulação do
   retrato. A proteção econômica continua inteira (só o consignado está lá) e a
   mecânica de guerra do item 11 protege contra roubo. Perde-se privacidade,
   ganha-se a graça de ver a nave do outro de verdade.
2. **O retrato deixa de ser a nave dele.** O servidor monta uma vitrine a partir
   de um casco de NPC — que nasce não explorado e portanto fica escondido — e
   transplanta só o que importa: o nome do dono, o estoque consignado e a banca.
   Resolve a névoa de graça, é mais barato de montar, e some com a questão da
   planta alheia. O custo é que a sala perde "aquela é a nave do Fulano".

A primeira mantém a promessa do projeto; a segunda mantém a privacidade. Não dá
para ter as duas com o que se sabe hoje.

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

## 12. O painel de comércio tem teto por recurso, não por estoque

Três rodadas para chegar aqui, e as três primeiras hipóteses morreram no caminho.

| Consignado | Ofertado | Casco |
|---|---|---|
| 40 Produtos químicos | **40** | nave de jogador |
| 30 Placas de aço | **26** | nave de jogador |
| 30 Placas de aço, sozinhas num armazém | **26** | outra nave de jogador |
| 10 Produtos químicos | **10** | casco de NPC |
| 30 Placas de aço | **26** | casco de NPC |

**É teto, não deslocamento.** Quantidade pequena sai inteira; as Placas param em
26 em três cascos diferentes, com e sem outro recurso junto.

**O que já foi descartado:**

- *capacidade de armazém* — armazéns autênticos guardam 1.530, 514, 278 unidades
- *teto por pilha* — Placas chegam a 47 numa pilha real, Infrabloco a 65
- *concentração num armazém só* — o mesmo 26 com o recurso sozinho
- *consumo pela tripulação* — nada de obra pendente, e nada sumiu do arquivo:
  o save seguiu com 30 e o `playerBank` intacto

**A explicação que sobra, e ela encaixa com o item 8:** o teto é de **transporte**,
não de estoque. A carga é entregue de ônibus, em caixas, e o painel oferta o que
cabe numa viagem. Placas de aço são volumosas e param em 26; Produtos químicos
são compactos e passam de 40. Nada some — o excesso simplesmente não está à
venda naquele momento.

**Como confirmar:** consignar 100 Produtos químicos. Se pararem num número
próprio deles — e não em 26 — o teto é por volume de recurso e a explicação
fecha.

**Para a consignação:** o dono precisa saber que consignar 100 de algo volumoso
não expõe 100. O servidor deve calcular e mostrar o que de fato fica à venda, em
vez de prometer o número cheio.

## 13. O Steam Cloud sincroniza o zip, não a pasta do save

Medido no `remotecache.vdf` do jogo (app 979110): o Steam rastreia **uma
entrada por partida**, e ela é sempre `savegames/<Nome>/cloudZipFile.zip`. A
pasta `save/`, onde moram o `game` e as naves, **não** é sincronizada.

Ou seja: o `save/` é o estado local, e o zip é a cópia da nuvem, refeita pelo
jogo ao gravar.

**Por que isso importa para o cliente.** Um `cloudZipFile.zip` velho ao lado de
um save recém-retirado é a combinação perigosa: se o Steam resolver restaurar —
outra máquina, um conflito de sincronia —, ele sobrescreve a sessão que o
servidor emprestou com uma partida antiga, e o jogador perde o progresso sem
entender por quê. O cliente passa a apagar o zip anterior ao escrever uma
retirada.

**Efeito colateral que o servidor detecta.** Se acontecer mesmo assim, o save
devolvido volta com dia de jogo **menor** do que o emprestado. A galáxia bate, o
jogador não fez nada de errado, e a conferência da seção 2.7 tem aí um sinal com
causa conhecida — vale distinguir esse caso de trapaça antes de sinalizar
alguém.

**O que o jogo precisa para listar um save.** A classe `GameData$SaveGame` tem
`scanForSaves`, `gameFile`, `infoFile` e `metaFile`: ele varre a pasta
procurando arquivos, não lê um índice. `cloud.xml` e `cloudZipFile.zip`
aparecem só no caminho de sincronia. Um save escrito sem eles deve aparecer
normalmente — a confirmar na primeira retirada.

## 14. O jogo tem mod loader nativo, e ele já traz o AspectJ

**Corrige a seção 2.9**, que diz: "da comunidade, não da Bugbyte. Não há API
oficial nem hooks providos pelo jogo."

`fi.bugbyte.spacehaven.steam.SpacehavenSteam` tem um método
`tryToLaunchModLoader`, e as strings da classe apontam para itens de Steam
Workshop:

```
/workshop/content/979110/3703674043/spacehaven-modloader.exe
/workshop/content/979110/3715831202/spacehaven-modloader
```

Ou seja: **o próprio jogo procura e lança um mod loader** distribuído pela
Workshop. Não é gambiarra de fora; é caminho que o executável conhece.

E o conteúdo do item 3703674043, já instalado nesta máquina, traz:

```
aspectj-1.9.19.jar
aspectjweaver-1.9.19.jar
spacehaven-modloader.exe
```

**O AspectJ vem junto.** A seção 2.9 estima o custo do mod como "o jogador
precisa instalar AspectJ, editar o `config.json` e ter Java 17". Os dois
primeiros somem: quem assina o mod loader na Workshop já recebe o weaver, e o
jogo o chama sozinho.

Isso derruba quase todo o argumento de fricção que fez o mod ser adiado. A
decisão de 2.9 — "o mod é opcional e não bloqueia fase nenhuma" — foi tomada
sobre um custo que não é o real.

**O que continua verdade da 2.9:** a simulação segue local e não determinística,
e cada atualização do jogo pode quebrar pointcuts, porque eles apontam para
assinaturas de método que ninguém prometeu manter.

**Não verificado:** como se registra um aspecto próprio no loader, e se ele
aceita qualquer weaving ou só o que os mods de dados usam. O outro item
instalado (3731405861) é mod de dados puro — `info.xml` mais `patches/*.xml` —
então o caminho de dados está confirmado e o de código, só inferido pela
presença do weaver.

## 15. Miudezas

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
