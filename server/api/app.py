"""
A API da custodia (fase 0).

Sete rotas: emitir token, listar salas, criar sala, entrar, retirar, devolver e
consultar estado. E o suficiente para o servidor ser dono da verdade — guarda o
save de cada jogador, empresta a cada sessao e recebe de volta.

O que este arquivo NAO faz de proposito:

- **nao decide.** As regras estao em `server/domain/rules.py`, em funcoes puras,
  e aqui so se aplica o que elas devolvem. Um handler que decide e um handler que
  ninguem testa.
- **nao guarda save.** Isso e da `server/storage/blobs.py`.
- **nao adivinha.** Toda recusa diz o motivo e, quando da, como corrigir.

Sobre autenticacao: o token vai no header `Authorization: Bearer <token>`. Nao
ha sessao, nao ha cookie, nao ha e-mail. O servidor guarda so o hash, entao um
vazamento do banco nao entrega conta nenhuma — mas tambem nao existe recuperar
token perdido, e o cliente e obrigado a avisar disso.
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import json
import os

import psycopg
from fastapi import Depends, FastAPI, Header, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, Response

from server.api import db
from server.domain import rules
from server.galaxy import fingerprint, presence
from server.storage import blobs
from server.web import pages
from server.storage.blobs import BlobStore, StorageError

# De quanto em quanto o servidor vence empréstimos por conta própria. Um prazo
# de 12h não precisa de precisão de minuto, e uma sala parada não deve custar
# consulta.
EXPIRY_EVERY = 300


@contextlib.asynccontextmanager
async def lifespan(_app):
    """Vence empréstimos sozinho, sem esperar alguém agir.

    Sem isto, um empréstimo só vence quando o próprio jogador tenta retirar de
    novo — e até lá a sala mostra ele como "jogando" para todo mundo, e o mapa
    da 2.11 mente. É a diferença entre uma sala viva e uma sala que parece viva.
    """
    async def laco():
        while True:
            await asyncio.sleep(EXPIRY_EVERY)
            try:
                with db.pool().connection() as conn:
                    venceram = db.expire_leases(conn)
                if venceram:
                    print(f"[prazo] {venceram} empréstimo(s) vencido(s)")
            except Exception as exc:      # noqa: BLE001
                # Um erro aqui não pode derrubar o servidor: quem está jogando
                # não tem nada a ver com a faxina.
                print(f"[prazo] falhou: {exc}")

    tarefa = asyncio.create_task(laco())
    try:
        yield
    finally:
        tarefa.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await tarefa


app = FastAPI(
    lifespan=lifespan,
    title="Galáxia Compartilhada",
    description="Servidor de custódia de savegames de Space Haven. "
                "Projeto independente, sem vínculo com a Bugbyte Ltd.",
    version="0.1.0",
)

BLOB_ROOT = os.environ.get("BLOB_ROOT", "/data/blobs")
INVITE_ONLY = os.environ.get("SGALAXY_INVITE_ONLY", "").strip()

_store: BlobStore | None = None


def store() -> BlobStore:
    global _store
    if _store is None:
        _store = BlobStore(BLOB_ROOT)
    return _store


# ---------------------------------------------------------------------------
# Autenticacao
# ---------------------------------------------------------------------------

def current_player(authorization: str = Header(default="")) -> dict:
    """O jogador dono do token, ou 401 com explicacao."""
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "informe o token em Authorization: Bearer <token>")
    token = rules.parse_recovery_code(authorization.split(None, 1)[1])
    with db.pool().connection() as conn:
        player = db.player_by_token(conn, rules.hash_token(token))
        if player is None:
            raise HTTPException(401, "token desconhecido. Se você perdeu o seu, "
                                     "não há como recuperá-lo: crie outro")
        if player["blocked"]:
            raise HTTPException(403, "esta conta está bloqueada")
        db.touch_player(conn, player["id"])
        return dict(player)


async def body_bytes(request: Request) -> bytes:
    """O save chega como corpo bruto, nao como formulario.

    O limite e conferido aqui em vez de deixar o processo comer 500 MB de
    memoria antes de recusar. Numa sala aberta isso nao e teoria.
    """
    total = request.headers.get("content-length")
    if total and int(total) > blobs.MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"save maior que o limite de "
                                 f"{blobs.MAX_UPLOAD_BYTES // (1024*1024)} MB")
    data = await request.body()
    if len(data) > blobs.MAX_UPLOAD_BYTES:
        raise HTTPException(413, "save maior que o limite")
    if not data:
        raise HTTPException(400, "o corpo da requisição está vazio; mande o "
                                 "zip do savegame")
    return data


# ---------------------------------------------------------------------------
# Jogador
# ---------------------------------------------------------------------------

@app.post("/api/v1/players", status_code=201)
def create_player(payload: dict | None = None):
    """Emite um token novo. E o unico cadastro que existe.

    Sem e-mail, sem senha, sem confirmacao. O token volta uma vez so — o cliente
    e responsavel por guardar, e por deixar claro que perder e perder.
    """
    payload = payload or {}
    if INVITE_ONLY and payload.get("invite", "").strip() != INVITE_ONLY:
        raise HTTPException(403, "este servidor exige convite para criar conta")

    name = str(payload.get("name") or "").strip() or "Anônimo"
    if len(name) > 40:
        raise HTTPException(400, "o nome tem no máximo 40 caracteres")

    token = rules.new_token()
    with db.pool().connection() as conn:
        player = db.create_player(conn, rules.hash_token(token), name)
    return {
        "playerId": player["id"],
        "name": player["display_name"],
        "token": token,
        "recoveryCode": rules.recovery_code(token),
        "warning": ("Guarde o código de recuperação agora. Ele é a única forma "
                    "de voltar a esta conta, e o servidor não tem cópia."),
    }


@app.get("/api/v1/me")
def whoami(player: dict = Depends(current_player)):
    return {"playerId": player["id"], "name": player["display_name"],
            "roomsCreated": player["rooms_created"]}


@app.delete("/api/v1/me")
def delete_me(confirm: str = "", player: dict = Depends(current_player)):
    """Apaga a conta e todo save dela. Sem etapa de arrependimento.

    A politica de dados promete "como apagar tudo e sair", e uma promessa
    dessas so vale se a rota existir. Apaga participacao, versoes e, em
    seguida, os blobs que ficaram sem dono.

    Sala criada por esta conta NAO e apagada junto: outros jogadores podem
    estar dentro dela, e sumir com a sala de terceiros para atender ao pedido
    de um seria destruir o save de quem nao pediu nada. A sala fica, sem dono
    ativo, e isso e dito na resposta.
    """
    if confirm != "apagar tudo":
        raise HTTPException(400,
                            'para confirmar, repita: ?confirm=apagar tudo. '
                            'Isto apaga sua conta e todos os seus saves, e não '
                            'há como desfazer')
    with db.pool().connection() as conn:
        rooms = conn.execute(
            "SELECT count(*) AS n FROM room WHERE owner_id = %s",
            (player["id"],)).fetchone()["n"]
        versions = conn.execute(
            "SELECT count(*) AS n FROM save_version WHERE player_id = %s",
            (player["id"],)).fetchone()["n"]
        # As tabelas dependentes caem por ON DELETE CASCADE; a sala tem
        # RESTRICT, entao o dono e desligado dela antes.
        conn.execute("UPDATE room SET listed = false WHERE owner_id = %s",
                     (player["id"],))
        conn.execute("DELETE FROM save_version WHERE player_id = %s",
                     (player["id"],))
        conn.execute("DELETE FROM membership WHERE player_id = %s",
                     (player["id"],))
        if rooms == 0:
            conn.execute("DELETE FROM player WHERE id = %s", (player["id"],))
        else:
            # Nao da para apagar o registro sem apagar as salas dele. O que da
            # e esvaziar tudo que e dado dele e bloquear o token.
            conn.execute(
                """UPDATE player SET display_name = 'conta apagada',
                                     token_hash = %s, blocked = true
                    WHERE id = %s""",
                (rules.hash_token(rules.new_token()), player["id"]))
        live = db.all_live_hashes(conn)
    freed = store().delete_unreferenced(live)
    return {"deleted": True, "versions": versions, "blobs": freed,
            "roomsKept": rooms,
            "message": ("conta e saves apagados." if rooms == 0 else
                        f"seus saves foram apagados e o token foi invalidado. "
                        f"{rooms} sala(s) criada(s) por você continuam de pé "
                        f"porque há outros jogadores dentro; elas saíram da "
                        f"listagem pública.")}


# ---------------------------------------------------------------------------
# Salas
# ---------------------------------------------------------------------------

@app.get("/api/v1/rooms")
def list_rooms():
    """Listagem publica: nome, jogadores, se tem senha. Sem a seed."""
    with db.pool().connection() as conn:
        rooms = db.list_rooms(conn)
    return {"rooms": [
        {"id": r["id"], "name": r["name"], "players": r["players"],
         "maxPlayers": r["max_players"], "hasPassword": r["has_password"],
         "createdAt": r["created_at"].isoformat()} for r in rooms]}


@app.post("/api/v1/rooms", status_code=201)
def create_room(payload: dict, player: dict = Depends(current_player)):
    ok, motivo = rules.can_create_room(player["rooms_created"], player["blocked"])
    if not ok:
        raise HTTPException(403, motivo)

    seed = str(payload.get("seed") or "").strip()
    if not seed:
        raise HTTPException(400, "informe a seed da galáxia. Ela não fica no "
                                 "save, então é o servidor que precisa guardá-la")
    name = str(payload.get("name") or "").strip() or f"Sala de {player['display_name']}"

    room = {
        "id": rules.new_room_id(),
        "name": name[:80],
        "seed": seed,
        "options": json.dumps(payload.get("options") or {}),
        "password_hash": (rules.hash_token(payload["password"])
                          if payload.get("password") else None),
        "owner_id": player["id"],
        "lease_hours": int(payload.get("leaseHours") or 12),
        "retention_n": int(payload.get("retentionN") or 20),
        "max_players": int(payload.get("maxPlayers") or 8),
    }
    with db.pool().connection() as conn:
        try:
            created = db.create_room(conn, room)
        except psycopg.errors.CheckViolation as exc:
            raise HTTPException(400, f"parâmetro fora da faixa aceita: {exc}") from exc
    return _room_public(created, can_see_recipe=True)


def _room_public(room: dict, can_see_recipe: bool) -> dict:
    """A sala como o cliente ve.

    A **receita** — seed e opcoes de criacao — sai para quem e da sala e para
    quem apresenta a senha dela. Nao da para esconder de quem quer entrar: sem a
    seed a pessoa nao consegue criar a partida, e sem criar a partida ela nao
    tem save para subir. A primeira versao escondia de nao-membros e tornava o
    fluxo impossivel.

    A listagem publica (`GET /rooms`) continua sem a receita: ali e vitrine, e
    uma sala com senha nao deve entregar a seed a quem so passou os olhos.
    """
    out = {
        "id": room["id"], "name": room["name"],
        "leaseHours": room["lease_hours"], "retentionN": room["retention_n"],
        "maxPlayers": room["max_players"],
        "hasPassword": room["password_hash"] is not None,
        "galaxyDigest": room["galaxy_digest"],
        "saveVersion": room["save_version"],
    }
    if can_see_recipe:
        out["seed"] = room["seed"]
        out["options"] = room["options"]
    return out


def _require_room(conn, room_id: str) -> dict:
    room = db.get_room(conn, room_id)
    if room is None:
        raise HTTPException(404, f"não existe sala {room_id}")
    return room


@app.get("/api/v1/rooms/{room_id}")
def room_detail(room_id: str, request: Request,
                player: dict = Depends(current_player)):
    """Os detalhes da sala, com a receita para quem pode reproduzi-la."""
    senha = request.headers.get("x-room-password", "")
    with db.pool().connection() as conn:
        room = _require_room(conn, room_id)
        membro = db.get_membership(conn, room_id, player["id"]) is not None
        aberta = room["password_hash"] is None
        confere = (room["password_hash"] is not None
                   and rules.hash_token(senha) == room["password_hash"])
        return _room_public(room, membro or aberta or confere)


@app.patch("/api/v1/rooms/{room_id}")
def update_room(room_id: str, payload: dict,
                player: dict = Depends(current_player)):
    """O dono ajusta a receita e as regras da sala.

    Existe porque a receita costuma ficar completa depois: a pessoa cria a
    sala, abre o jogo, e só então sabe o nome exato da nave inicial e das
    opções de cenário que marcou. Sem isto, corrigir um dado publicado exigiria
    apagar a sala — e apagar sala com gente dentro é o que não se faz.

    A seed NÃO é editável. Trocar a seed de uma sala com jogadores dentro
    invalidaria o save de todos eles de uma vez.
    """
    with db.pool().connection() as conn:
        room = _require_room(conn, room_id)
        if room["owner_id"] != player["id"]:
            raise HTTPException(403, "só o dono da sala pode mudar isto")

        campos, valores = [], {}
        if "name" in payload:
            campos.append("name = %(name)s")
            valores["name"] = str(payload["name"])[:80]
        if "options" in payload:
            campos.append("options = %(options)s")
            valores["options"] = json.dumps(payload["options"])
        for chave, coluna in (("leaseHours", "lease_hours"),
                              ("maxPlayers", "max_players"),
                              ("retentionN", "retention_n")):
            if chave in payload:
                campos.append(f"{coluna} = %({coluna})s")
                valores[coluna] = int(payload[chave])
        if "listed" in payload:
            campos.append("listed = %(listed)s")
            valores["listed"] = bool(payload["listed"])
        if not campos:
            raise HTTPException(400, "nada para mudar")

        valores["id"] = room_id
        try:
            atualizada = conn.execute(
                f"UPDATE room SET {', '.join(campos)} WHERE id = %(id)s "
                f"RETURNING *", valores).fetchone()
        except psycopg.errors.CheckViolation as exc:
            raise HTTPException(400, f"valor fora da faixa aceita: {exc}") from exc
    return _room_public(atualizada, can_see_recipe=True)


@app.get("/api/v1/rooms/{room_id}/state")
def room_state(room_id: str, player: dict = Depends(current_player)):
    """Quem está onde. É o que alimenta o mapa da sala e o cliente."""
    with db.pool().connection() as conn:
        _require_room(conn, room_id)
        roster = db.room_roster(conn, room_id)
    return {"roomId": room_id, "players": [
        {"playerId": r["player_id"], "name": r["display_name"],
         "shipName": r["ship_name"], "system": r["at_system"],
         "celeid": r["at_celeid"], "gameDay": float(r["game_day"]) if r["game_day"] else None,
         "playing": r["playing"],
         "lastSeen": r["last_seen_at"].isoformat() if r["last_seen_at"] else None}
        for r in roster]}


# ---------------------------------------------------------------------------
# Entrada
# ---------------------------------------------------------------------------

@app.post("/api/v1/rooms/{room_id}/join")
async def join_room(room_id: str, request: Request,
                    player: dict = Depends(current_player)):
    """Sobe o save recem-criado e, se a galaxia bater, adota como canonico.

    E o unico momento que exige o jogador: o servidor nao consegue gerar uma
    colonia inicial (secao 1.6), entao a partida e criada no jogo, normalmente.
    Uma vez so — depois disso o servidor e dono.
    """
    password = request.headers.get("x-room-password", "")
    data = await body_bytes(request)

    with db.pool().connection() as conn:
        room = _require_room(conn, room_id)
        if room["password_hash"] and rules.hash_token(password) != room["password_hash"]:
            raise HTTPException(403, "senha da sala incorreta")
        if db.get_membership(conn, room_id, player["id"]) is not None:
            raise HTTPException(409, "você já está nesta sala. Use /checkout "
                                     "para retirar o seu save")
        if db.count_players(conn, room_id) >= room["max_players"]:
            raise HTTPException(409, "a sala está cheia")

        # A conferencia acontece ANTES de gravar blob: lixo nao deve custar
        # disco numa sala aberta.
        try:
            with blobs.with_unpacked(data) as folder:
                described = fingerprint.describe(folder)
                here = presence.read(folder)
                day = here["gameDay"]
        except StorageError as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(400, f"não consegui ler este save: {exc}") from exc

        ok, motivo = rules.check_join(described, room)
        if not ok:
            raise HTTPException(409, motivo)

        meta = store().put(data)
        version = db.add_version(conn, {
            "room_id": room_id, "player_id": player["id"],
            "sha256": meta["sha256"], "bytes": meta["bytes"],
            "kind": "canonical", "game_day": day,
            "galaxy_digest": described["digest"]})
        if not room["galaxy_digest"]:
            with blobs.with_unpacked(data) as folder:
                db.save_galaxy_map(conn, room_id, presence.galaxy_map(folder))
        db.adopt_galaxy(conn, room_id, described["digest"],
                        described["saveVersion"])
        db.upsert_membership(conn, room_id, player["id"], here["shipName"],
                             version["id"])
        db.set_position(conn, room_id, player["id"], here["system"],
                        here["celeid"])

    return {"roomId": room_id, "versionId": version["id"],
            "galaxy": described, "gameDay": day, "presence": here,
            "message": "save adotado como canônico. A partir de agora o "
                       "servidor é dono dele."}


# ---------------------------------------------------------------------------
# Ciclo de sessao
# ---------------------------------------------------------------------------

@app.post("/api/v1/rooms/{room_id}/checkout")
def checkout(room_id: str, player: dict = Depends(current_player)):
    """Abre o emprestimo e devolve o save. O corpo da resposta e o zip."""
    with db.pool().connection() as conn:
        room = _require_room(conn, room_id)
        membership = db.get_membership(conn, room_id, player["id"])
        if membership is None:
            raise HTTPException(403, "você não está nesta sala. Use /join com "
                                     "um save criado na seed da sala")
        db.expire_leases(conn)
        existing = db.open_lease(conn, room_id, player["id"])
        ok, motivo = rules.can_checkout(existing, db.now())
        if not ok:
            raise HTTPException(409, motivo)

        version = db.get_version(conn, membership["canonical_id"])
        if version is None:
            raise HTTPException(500, "esta participação não tem save canônico; "
                                     "isso é bug do servidor, não seu")
        expires = rules.lease_expiry(db.now(), room["lease_hours"])
        try:
            lease = db.create_lease(conn, room_id, player["id"],
                                    version["id"], expires)
        except psycopg.errors.UniqueViolation as exc:
            # O indice parcial pegou uma corrida. E o desenho funcionando.
            raise HTTPException(409, "outra retirada deste save aconteceu ao "
                                     "mesmo tempo. Tente de novo") from exc
        data = store().get(version["sha256"])

    return Response(
        content=data, media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{room_id}-save.zip"',
            "X-Lease-Id": str(lease["id"]),
            "X-Lease-Expires": expires.isoformat(),
            "X-Version-Id": str(version["id"]),
        })


@app.post("/api/v1/rooms/{room_id}/checkin")
async def checkin(room_id: str, request: Request,
                  player: dict = Depends(current_player)):
    """Recebe o save final, valida, guarda e fecha o emprestimo."""
    data = await body_bytes(request)

    with db.pool().connection() as conn:
        room = _require_room(conn, room_id)
        db.expire_leases(conn)
        lease = conn.execute(
            """SELECT * FROM lease
                WHERE room_id = %s AND player_id = %s
                ORDER BY issued_at DESC LIMIT 1""",
            (room_id, player["id"])).fetchone()
        ok, motivo = rules.can_checkin(lease, db.now())
        if not ok:
            raise HTTPException(409, motivo)

        try:
            with blobs.with_unpacked(data) as folder:
                described = fingerprint.describe(folder)
                here = presence.read(folder)
                day = here["gameDay"]
        except StorageError as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(400, f"não consegui ler este save: {exc}") from exc

        # A galaxia nao pode ter mudado no meio de uma sessao. Se mudou, o save
        # nao e o que foi emprestado — outra partida, outro universo.
        if described["digest"] != room["galaxy_digest"]:
            raise HTTPException(409,
                                "a galáxia deste save não é a da sala. Este não "
                                "é o save que foi emprestado")

        meta = store().put(data)
        version = db.add_version(conn, {
            "room_id": room_id, "player_id": player["id"],
            "sha256": meta["sha256"], "bytes": meta["bytes"],
            "kind": "canonical", "game_day": day,
            "galaxy_digest": described["digest"]})
        # Os nomes de sistema que o jogador descobriu jogando entram no mapa
        # da sala. A posicao ja estava la desde a primeira entrada.
        with blobs.with_unpacked(data) as folder:
            db.save_galaxy_map(conn, room_id, presence.galaxy_map(folder))
        db.close_lease(conn, lease["id"], version["id"])
        db.upsert_membership(conn, room_id, player["id"], here["shipName"],
                             version["id"])
        db.set_position(conn, room_id, player["id"], here["system"],
                        here["celeid"])
        pruned = _prune(conn, room_id, player["id"], room["retention_n"])

    return {"roomId": room_id, "versionId": version["id"], "gameDay": day,
            "presence": here, "pruned": pruned,
            "message": "save recebido e guardado. Ele é o que os outros veem."}


def _prune(conn, room_id: str, player_id: int, retention_n: int) -> int:
    """Aplica a janela de retencao. Nunca toca na canonica nem na emprestada."""
    versions = db.player_versions(conn, room_id, player_id)
    protegidas = {r["id"] for r in conn.execute(
        """SELECT canonical_id AS id FROM membership
            WHERE room_id = %s AND player_id = %s AND canonical_id IS NOT NULL
           UNION
           SELECT delivered_id FROM lease
            WHERE room_id = %s AND player_id = %s AND state = 'open'""",
        (room_id, player_id, room_id, player_id)).fetchall()}
    podar = rules.versions_to_prune(versions, retention_n, protegidas)
    return db.delete_versions(conn, [v["id"] for v in podar])


# ---------------------------------------------------------------------------
# Saude e raiz
# ---------------------------------------------------------------------------

@app.get("/api/v1/health")
def health():
    try:
        with db.pool().connection() as conn:
            conn.execute("SELECT 1")
        return {"status": "ok", "storage": store().usage()}
    except Exception as exc:
        raise HTTPException(503, f"banco indisponível: {exc}") from exc


@app.get("/", response_class=HTMLResponse)
def index():
    """As salas abertas. É a vitrine: ver antes de decidir se quer entrar."""
    with db.pool().connection() as conn:
        rooms = db.list_rooms(conn)
    return pages.room_list([dict(r) for r in rooms])


@app.get("/sala/{room_id}", response_class=HTMLResponse)
def room_web(room_id: str):
    """A sala como página. Sem conta, sem instalar nada — é o degrau 2 da 2.11."""
    with db.pool().connection() as conn:
        room = db.get_room(conn, room_id)
        if room is None:
            raise HTTPException(404, f"não existe sala {room_id}")
        roster = db.room_roster(conn, room_id)
        galaxy = db.galaxy_map(conn, room_id)
    return pages.room_page(dict(room), [dict(r) for r in roster], galaxy)


@app.get("/privacidade", response_class=HTMLResponse)
def privacy():
    """A política de dados.

    A seção 2.11 do projeto manda escrever isto **antes** de existir, e em
    linguagem clara, onde a pessoa lê antes de instalar qualquer coisa. O
    editor de savegame promete que nada sai do computador; este servidor quebra
    essa promessa, e fingir que não seria o pior erro possível.
    """
    return _page("O que acontece com o seu save", """
<h2>O que sobe</h2>
<p><b>O savegame inteiro</b>, compactado: o arquivo <code>game</code>, as naves,
os setores e os binários que o jogo grava junto. Não é um resumo — é a sua
partida completa.</p>

<h2>Para onde</h2>
<p>Para este servidor, em <code>galaxy.bygianotto.com.br</code>, mantido por um
particular. Não há empresa por trás, não há terceiro recebendo cópia, e nada é
enviado para outro serviço.</p>

<h2>Quem enxerga</h2>
<p>Quem administra o servidor tem acesso técnico aos arquivos — não há
criptografia que impeça isso, e dizer o contrário seria mentira. Outros jogadores
da mesma sala verão, quando a etapa seguinte existir, apenas um <b>retrato</b>:
uma loja com o nome que você escolher e só a mercadoria que você consignar. O seu
porão de verdade não entra nessa cópia.</p>

<h2>Por quanto tempo</h2>
<p>As últimas 20 versões de cada save, por sala. As mais antigas são apagadas
sozinhas. Se você sair, apaga na hora.</p>

<h2>Que dado pessoal</h2>
<p><b>Nenhum.</b> Não pedimos e-mail, nome real, senha ou login de Steam. A sua
identidade aqui é um código aleatório que o servidor gera e do qual guarda só o
resumo criptográfico. A consequência é dura e é honesta: <b>quem perde o código
perde a conta</b>, e não há como recuperar.</p>

<h2>Como apagar tudo e sair</h2>
<p>Uma chamada, e não há etapa de arrependimento:</p>
<pre>curl -X DELETE "https://galaxy.bygianotto.com.br/api/v1/me?confirm=apagar%20tudo" \
     -H "Authorization: Bearer SEU-TOKEN"</pre>
<p>Apaga a sua conta e todos os seus saves. Salas que você criou e onde há outros
jogadores continuam de pé — sumir com elas destruiria o save de quem não pediu
nada —, mas saem da listagem e o seu token é invalidado.</p>

<h2>O que não dá para prometer</h2>
<p>O jogo roda na sua máquina, em arquivos que você consegue editar. Não há como
impedir que alguém altere o próprio save, e o projeto não finge que há: o
desenho é cooperativo, e o servidor <b>confere</b> em vez de adivinhar. Quem
promete segurança absoluta é quem não pensou no assunto.</p>

<p><a href="/">voltar</a></p>""")


def _page(title: str, body: str) -> str:
    tab = title if "Galáxia" in title else f"{title} — Galáxia Compartilhada"
    return f"""<!doctype html><html lang="pt-BR"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{tab}</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ max-width: 40rem; margin: 3rem auto; padding: 0 1.2rem;
         font: 16px/1.6 system-ui, sans-serif; }}
  h1 {{ font-size: 1.5rem; }} h2 {{ font-size: 1.1rem; margin-top: 2rem; }}
  pre {{ overflow-x: auto; padding: .8rem; border-radius: .4rem;
        background: rgba(127,127,127,.12); font-size: .85rem; }}
  footer {{ margin-top: 3rem; font-size: .85rem; opacity: .75; }}
</style>
<h1>{title}</h1>
{body}
<footer><p><b>Space Haven</b> é um jogo da
<a href="https://bugbyte.fi/">Bugbyte Ltd.</a> Este é um projeto independente,
feito por fã: não é oficial, não tem endosso e não tem vínculo com ela. Nada
aqui altera o jogo — tudo é leitura e escrita de savegame, o que jogadores fazem
à mão há anos.</p></footer></html>"""
