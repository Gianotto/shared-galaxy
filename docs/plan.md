# Plano de implementação

Documento de trabalho. Complementa `shared-galaxy-server.md`, que é o projeto, e
`savegame-format.md`, que é o levantamento. Aqui está a ordem, as decisões
tomadas e o que cada etapa precisa entregar para a seguinte começar.

Escrito só em português por enquanto: o plano muda toda semana e manter tradução
de documento que churna é desperdício. A versão em inglês entra quando o
repositório for público, junto do README.

---

## Decisões tomadas

| Assunto | Decisão | Consequência |
|---|---|---|
| Escopo deste repo | servidor + mapa web da sala | o cliente é uma aba nova no `space_haven_editor`, não um app novo (2.11, degrau 3) |
| Stack | Python, FastAPI, Postgres | fora da disciplina stdlib do editor; aceito porque o servidor não roda na máquina do jogador |
| Persistência de save | arquivos comprimidos em volume, endereçados por sha256; Postgres só com metadado | backup trivial, auto-hospedagem sem drama, sem large objects |
| Identidade | token opaco emitido pelo servidor, sem e-mail nem senha | zero dado pessoal; perder o token perde o jogador, então o cliente força código de recuperação |
| Público | sala aberta e listável desde cedo | cota, limite de upload e rate limit entram na fase 0, não depois |
| Histórico | últimas N versões por jogador, N por sala, padrão 20 | armazenamento previsível; a conferência de 2.7 tem alcance limitado e isso é aceito |
| Prazo de retirada | 12 horas, configurável por sala | cobre sessão longa e uma noite de sono |
| Deploy | `docker compose up`, e só | mesmo caminho para a sala pública e para quem auto-hospeda |
| Idioma | código, API e rotas em inglês; documentação bilíngue | igual ao editor |
| Primeiro trabalho | experimento de comércio (2.12) | decide a fase 3 antes de qualquer código de servidor |

---

## Etapa A — O experimento de comércio

O documento diz que medir como uma transação de TRADE fica gravada no save é o
próximo experimento a fazer, e que ele decide a fase 3. É barato, não precisa de
servidor nenhum, e se der resultado ruim muda o desenho antes de existir código.

Mora em `tools/` **deste** repositório. A primeira versão deste plano mandava
para `space_haven_editor/tools/`, ao lado de `compare_galaxy.py`, por serem
análise de save. Mudei: o resultado do experimento é documento deste projeto, o
injetor vira o construtor de retratos da fase 2 — ou seja, vira código de
servidor — e o editor tem uma promessa própria a manter ("nada sai do seu
computador") que não combina com hospedar tooling de um projeto que sobe
arquivos. O preço é vendorar `savefile.py`, registrado em `sgalaxy/VENDOR.md`.

### A.1 — Instrumentação (eu escrevo)

**`tools/save_snapshot.py`** — copia uma pasta de save para um diretório de
trabalho com rótulo e carimbo de tempo. Trivial, mas é o que torna o resto
repetível.

**`tools/save_diff.py`** — a peça central. Diff estrutural entre dois snapshots,
por caminho XML, dizendo elementos criados, removidos e atributos alterados.
Precisa de uma lista de ruído conhecido para ser legível: fase orbital dos
corpos, temporizadores, `idCounter`, posição de tripulante. Sem isso o diff de
uma transação vem afogado em milhares de linhas.

**`tools/inject_npc_ship.py`** — monta a nave de vizinho num save, seguindo a
receita de 2.5: `sid` e `entId` novos do `masterData/@idCounter`, `settings/@of`
e `@owner` da facção, `<asi>` copiado de NPC, `<shipBank>` com estoque
controlado, `fg="0"`/`unex`/`forceRoof`, frota `<f>` no corpo celeste, permissões
no `hostmap`. É experimento agora e vira o construtor de retratos da fase 2
depois — vale escrever já com essa dupla vida em mente.

### A.2 — Roteiro (você joga)

Na ordem, porque cada um depende do anterior:

**E1 — piso de ruído.** Carregar um save, não fazer nada, salvar. O que muda de
qualquer jeito? Sem essa medida, nenhum diff posterior é interpretável. Alimenta
a lista de ruído do `save_diff.py`.

**E2 — comércio com NPC nativo.** Uma compra só, de um item só, com uma nave que
o próprio jogo colocou ali. Snapshot antes e depois. A pergunta: *a transação
fica registrada como evento, ou só como estado final?*

**E3 — comércio com nave injetada.** Mesma coisa, com o `<shipBank>` que nós
montamos, estoque e `ca` conhecidos. As perguntas: o estoque da nave injetada
diminui e isso persiste? os créditos entram no `playerBank`? o jogo respeita o
`ca` como limite de compra?

**E4 — várias transações.** Três compras e uma venda na mesma sessão. Dá para
distinguir três compras de uma compra grande? Isso decide se a conciliação é por
transação ou por delta líquido.

**E5 — procedência.** Duas naves injetadas no mesmo setor, cada uma com um
recurso marcador que o jogador não possui. Ao ver a carga no fim, dá para dizer
de quem veio? Se não der, a conciliação com vários vizinhos fica ambígua e o
desenho precisa de marcador por consignação.

### A.3 — O que cada resultado implica

- **Só estado final, mas o `<shipBank>` persiste:** conciliação por delta
  líquido. O servidor montou o `<shipBank>`, então sabe o estado inicial exato e
  a diferença é a transação. **Fase 3 sai como está no documento.**
- **O `<shipBank>` não persiste** (o jogo regenera o banco da nave ao carregar):
  a venda não é reconstruível pelo lado da nave. Resta inferir pelo `playerBank`
  e pela carga, o que só funciona com recursos marcadores — E5 vira obrigatório e
  a consignação passa a ser de item único por vizinho.
- **Nem estado final aproveitável:** fase 3 muda de natureza. O comércio nativo
  vira sabor, não economia, e a troca real acontece por consignação fora do jogo
  (o vizinho pede, o servidor entrega no porão na próxima retirada). Menos
  elegante, mas funciona e não depende de nada disso.

**Entregável da etapa A:** um documento `trade-experiment.md` com o protocolo, os
diffs medidos e a implicação escolhida. É o que destrava a fase 3 e o que muda
(ou confirma) a seção 2.12.

---

## Etapa B — Fase 0, a custódia

Começa em paralelo à etapa A assim que E1 e E2 estiverem medidos: nada na fase 0
depende do resultado do comércio.

### B.1 — Esqueleto do repositório

```
Shared-Galaxy/
  server/
    api/            rotas FastAPI
    domain/         sala, jogador, empréstimo, versão de save
    storage/        blobs em volume, endereçados por sha256
    galaxy/         impressão digital, vendorada do editor
    web/            páginas do mapa (Jinja2, sem build de frontend)
  migrations/
  compose.yml
  tests/
```

`git init`, licença e NOTICE iguais aos do editor, aviso legal de 2.13 no README
desde o primeiro commit.

### B.2 — Impressão digital da galáxia

O servidor precisa da lógica de `tools/compare_galaxy.py` para conferir o save de
entrada (2.3). Ela vive no editor e não vou criar dependência de pacote entre os
dois repositórios agora. **Vendorar** em `server/galaxy/fingerprint.py`, com um
teste que roda a mesma função dos dois lados sobre os mesmos saves e exige
resultado idêntico. Se divergirem um dia, o teste avisa.

### B.3 — Modelo de dados

- `player` — hash do token, apelido, criação
- `room` — id curto, seed, opções de criação, hash da senha (opcional),
  `lease_hours`, `retention_n`, dono
- `membership` — sala, jogador, versão canônica atual
- `save_version` — sala, jogador, sha256, tamanho, dia de jogo, tipo
  (`canonical` ou `checkpoint`), criação
- `lease` — sala, jogador, emitido em, expira em, versão entregue, estado

Poda: ao gravar uma versão nova, apaga as que passarem de `retention_n`, nunca a
canônica atual nem a emprestada.

### B.4 — API

Todas sob `/api/v1`, com o token no header.

| Rota | O que faz |
|---|---|
| `POST /players` | emite token novo, devolve código de recuperação |
| `GET /rooms` | listagem pública: nome, jogadores, tem senha |
| `POST /rooms` | cria sala com seed e opções |
| `POST /rooms/{id}/join` | sobe o save inicial; confere impressão digital; adota como canônico |
| `POST /rooms/{id}/checkout` | abre empréstimo de 12h e entrega o save montado |
| `POST /rooms/{id}/checkin` | recebe o save final, valida, guarda, fecha o empréstimo |
| `GET /rooms/{id}/state` | estado da sala em JSON, para o cliente |

Recusa de `join` explica o motivo — quase sempre opção de criação diferente
(2.3).

### B.5 — Sala aberta, portanto

- limite de tamanho de upload (32 MB cobre um save de 124 dias com folga)
- cota de salas criadas por token, e de jogadores por sala
- rate limit em `checkout` e `checkin`
- a conferência de impressão digital acontece **antes** de gravar blob, para lixo
  não custar disco
- `POST /players` com custo (proof-of-work leve ou captcha) só se aparecer abuso;
  não antecipar

### B.6 — Mapa web

Páginas server-rendered no mesmo FastAPI, sem build de frontend: listagem de
salas, página da sala com quem está onde, e o histórico de entradas e saídas. É
a vitrine do degrau 2 de 2.11 — alguém vê o mundo vivo e decide se quer entrar,
sem instalar nada.

### B.7 — Empréstimo e queda

- prazo de 12h; vencido, o estado volta ao de quando foi retirado
- `checkin` fora de empréstimo válido é recusado com explicação
- devolver um autosave depois de queda do jogo é o caminho normal, não exceção

**Entregável da etapa B:** save na nuvem, com histórico e sem save scumming.
Produto sozinho, como o documento diz, e é a etapa que ensina mais — sessão
abandonada, cliente travado, jogo que fecha sozinho.

---

## Etapa C — O cliente

Track paralela, no repositório do editor, como aba nova. Não bloqueia B: dá para
exercitar a API com `curl` e com o próprio navegador.

- autenticar, listar salas, entrar
- pasta de savegame dedicada por sala
- **lançar o jogo ele mesmo e esperar o processo terminar** — é o que garante
  nunca escrever com o jogo aberto (2.9)
- registro visível de tudo que subiu e de todo arquivo escrito (2.11)
- modo de ensaio: mostrar o que seria alterado sem alterar
- forçar o jogador a guardar o código de recuperação do token

---

## Etapa D — Fases 1 a 3

**Fase 1 — batimento.** O cliente observa os autosaves e manda um estado
reduzido: sistema, corpo celeste, dia de jogo, frota, manifesto consignado. Save
inteiro só na devolução — mandar 4,5 MB a cada autosave é desperdício. A sala
fica viva entre sessões e o mapa de B.6 passa a se mexer.

**Fase 2 — injeção de vizinho, sem comércio.** O `inject_npc_ship.py` da etapa A
vira construtor de retratos no servidor, e a montagem passa a acontecer no
`checkout`. Prova o momento que vende o projeto: você abre o jogo e a loja de
alguém está lá.

O retrato é uma **vitrine sobre casco de NPC do próprio save de destino**
(`--hull`), não uma cópia da nave do vizinho. Decidido depois do E3b: a névoa só
se sustenta se a nave de origem nunca foi explorada, e nave de jogador é sempre
explorada. Ver `findings.md` item 10 e a seção 2.5 do projeto. De quebra o casco
sai da instalação do próprio jogador, o que mantém a regra da seção 2.13, e o
retrato cabe em 166 KB em vez de 460.

**Fase 3 — consignação e conciliação.** Depende do resultado da etapa A. Banca de
feira, não porão: só o consignado entra no retrato, o `ca` limita o quanto a nave
compra, e a conciliação desconta do consignado e credita o vendedor.

Fora da fila, sem bloquear nada: o mod mínimo de 2.9 e a injeção ao vivo.

---

## Riscos que este plano assume

- **Perder o token perde o jogador.** Preço de não guardar dado pessoal. Mitigado
  só por insistência do cliente no código de recuperação.
- **Sala aberta sem contas convida a jogador descartável.** Criar token é grátis;
  se virar problema, a resposta é custo na criação, não cadastro.
- **Histórico de N versões limita a auditoria de 2.7.** Uma divergência antiga
  pode já ter saído da janela quando alguém for olhar.
- **Vendorar a impressão digital cria duas cópias da mesma lógica.** O teste
  cruzado é o que impede a deriva silenciosa.
- **Atualização do jogo reconfere tudo.** Vale ancorar a versão do jogo por sala
  desde a fase 0, para o servidor recusar save de versão diferente em vez de
  aceitar e corromper.
