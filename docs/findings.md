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

## 8. Miudezas

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
