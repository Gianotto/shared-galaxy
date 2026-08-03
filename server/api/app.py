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
import copy
import json
import secrets
import logging
import os

import psycopg
from fastapi import Depends, FastAPI, Form, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from server.api import db
from server.domain import addresses
from server.domain import rules
from server.galaxy import fingerprint, presence
from sgalaxy import discovery as discovering
from sgalaxy import graft as grafting
from sgalaxy import settle
from sgalaxy import shop as shopping
from sgalaxy import starter
from sgalaxy import storefront
from sgalaxy.savefile import SaveFile
from server.storage import blobs
from server.web import i18n, pages
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


log = logging.getLogger("sgalaxy")

app = FastAPI(
    lifespan=lifespan,
    title="Galáxia Compartilhada",
    description="Servidor de custódia de savegames de Space Haven. "
                "Projeto independente, sem vínculo com a Bugbyte Ltd.",
    version="0.1.0",
)

BLOB_ROOT = os.environ.get("BLOB_ROOT", "/data/blobs")
INVITE_ONLY = os.environ.get("SGALAXY_INVITE_ONLY", "").strip()

# Quantas contas por endereco. Um por padrao; a variavel existe para uma LAN
# ou um alojamento nao precisarem de deploy para caber.
MAX_PER_IP = int(os.environ.get("SGALAXY_MAX_PER_IP", "1") or "1")

# O segredo que transforma endereco em impressao. Sem ele nao ha limite por
# endereco NENHUM — preferimos registrar aberto a guardar endereco de gente em
# claro, e a mensagem no log diz o que fazer.
IP_PEPPER = os.environ.get("SGALAXY_IP_PEPPER", "").strip()


def _address_has_room(conn, request: Request) -> tuple[bool, str | None]:
    """Este endereco ainda pode criar conta? Devolve `(pode, impressao)`."""
    impressao = addresses.fingerprint(addresses.client_ip(request),
                                      IP_PEPPER)
    if impressao is None:
        if not IP_PEPPER:
            log.warning("SGALAXY_IP_PEPPER is not set: accounts are NOT "
                        "limited per address")
        return True, None
    if db.accounts_from(conn, impressao) >= MAX_PER_IP:
        return False, impressao
    return True, impressao

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
        raise HTTPException(401, "send the token in Authorization: Bearer <token>")
    token = rules.parse_recovery_code(authorization.split(None, 1)[1])
    with db.pool().connection() as conn:
        player = db.player_by_token(conn, rules.hash_token(token))
        if player is None:
            raise HTTPException(401, "unknown token. If you lost yours there is no way "
                                     "to recover it: create another")
        if player["blocked"]:
            raise HTTPException(403, "this account is blocked")
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
        raise HTTPException(400, "the request body is empty; send the savegame zip")
    return data


# ---------------------------------------------------------------------------
# Jogador
# ---------------------------------------------------------------------------

@app.post("/api/v1/players", status_code=201)
def create_player(request: Request, payload: dict | None = None):
    """Emite um token novo. E o unico cadastro que existe.

    Sem e-mail, sem senha, sem confirmacao. O token volta uma vez so — o cliente
    e responsavel por guardar, e por deixar claro que perder e perder.
    """
    payload = payload or {}
    if INVITE_ONLY and not secrets.compare_digest(
            str(payload.get("invite") or "").strip(), INVITE_ONLY):
        raise HTTPException(403, "this server requires an invite to create an "
                                 "account")

    name = str(payload.get("name") or "").strip() or "Anonymous"
    if len(name) > 40:
        raise HTTPException(400, "the name is at most 40 characters")

    token = rules.new_token()
    with db.pool().connection() as conn:
        pode, impressao = _address_has_room(conn, request)
        if not pode:
            raise HTTPException(429, "an account has already been created from "
                                     "this connection. If it is yours, use your "
                                     "recovery code instead of making another")
        player = db.create_player(conn, rules.hash_token(token), name,
                                  impressao)
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
    if confirm != "delete everything":
        raise HTTPException(400,
                            'to confirm, repeat it back: '
                            '?confirm=delete everything. This deletes your '
                            'account and every save you have, and there is no '
                            'undo')
    with db.pool().connection() as conn:
        rooms = conn.execute(
            "SELECT count(*) AS n FROM room WHERE owner_id = %s",
            (player["id"],)).fetchone()["n"]
        versions = conn.execute(
            "SELECT count(*) AS n FROM save_version WHERE player_id = %s",
            (player["id"],)).fetchone()["n"]
        # O MOLDE DE UMA GALAXIA PODE SER O SAVE DESTA PESSOA, e ai ele nao
        # pode sobreviver a ela. Medido: o molde da Frontier era a partida do
        # Fernando. Como a galaxia aponta para o blob, a poda o protegia, e o
        # jogo de alguem que pediu para apagar tudo continuaria sendo entregue
        # a cada pessoa nova. A galaxia adota outro na proxima entrada, ou fica
        # sem molde e quem chega cria a partida no jogo.
        soltos = conn.execute(
            """UPDATE room SET starter_sha256 = NULL
                WHERE starter_sha256 IN (SELECT sha256 FROM save_version
                                          WHERE player_id = %s)
             RETURNING id""", (player["id"],)).fetchall()
        if soltos:
            log.info("dropped the starting save of %s galaxy(ies) with the "
                     "account that made it", len(soltos))

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
            "roomsKept": rooms, "startersDropped": len(soltos),
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
    with db.pool().connection() as conn:
        ok, motivo = rules.can_create_room(db.rooms_owned(conn, player["id"]),
                                           player["blocked"])
    if not ok:
        raise HTTPException(403, motivo)

    # A SEED SAIU. O jogo grava `seed="0"` em todo save, medido em quatro
    # partidas diferentes, entao a seed digitada nunca chegou ao servidor e
    # nunca pode ser conferida. Guardar um numero que ninguem verifica so
    # levantava a duvida "preciso dela?" em quem lia a pagina.
    #
    # Ninguem precisa. Quem chega recebe uma copia do molde, e quem traz a
    # propria partida tem a galaxia enxertada por cima. O que identifica uma
    # galaxia sao as estrelas dela. A coluna continua no banco pelas galaxias
    # que ja tinham uma anotada.
    seed = ""
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
        "retention_n": int(payload.get("retentionN") or 3),
        "max_players": int(payload.get("maxPlayers") or 64),
        # Todo mundo comeca junto. `None` explicito libera veterano a trazer o
        # que tem; ausente usa o padrao da coluna.
        "max_join_age_days": (None if payload.get("maxJoinAgeDays", 0) is None
                              else float(payload.get("maxJoinAgeDays") or 5)),
    }
    with db.pool().connection() as conn:
        try:
            created = db.create_room(conn, room)
        except psycopg.errors.CheckViolation as exc:
            raise HTTPException(400, f"parameter out of the accepted range: {exc}") from exc
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
        "maxJoinAgeDays": (float(room["max_join_age_days"])
                           if room.get("max_join_age_days") is not None
                           else None),
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
        raise HTTPException(404, f"there is no room {room_id}")
    return room


@app.delete("/api/v1/rooms/{room_id}")
def delete_room(room_id: str, confirm: str = "",
                player: dict = Depends(current_player)):
    """Apaga a galaxia. So quem a criou, e sem desfazer.

    Isto destroi o save de todo mundo que estava dentro, nao so o de quem pede.
    Por isso a confirmacao repete o nome da galaxia: um `--force` qualquer se
    digita por reflexo, e o nome exige ler o que esta prestes a sumir.

    Com sessao aberta ela nao sai. Alguem esta jogando, e apagar por baixo
    transforma a devolucao dessa pessoa num erro sem explicacao.
    """
    with db.pool().connection() as conn:
        room = _require_room(conn, room_id)
        if room["owner_id"] != player["id"]:
            raise HTTPException(
                403, "only whoever created this galaxy can delete it")

        db.expire_leases(conn)
        abertas = conn.execute(
            "SELECT count(*) AS n FROM lease WHERE room_id = %s AND "
            "state = 'open'", (room_id,)).fetchone()["n"]
        if abertas:
            raise HTTPException(
                409, "somebody is playing this galaxy right now. Deleting it "
                     "would turn their check-in into an error they cannot act "
                     "on. Wait for the session to come back")

        if confirm.strip() != room["name"]:
            membros = conn.execute(
                "SELECT count(*) AS n FROM membership WHERE room_id = %s",
                (room_id,)).fetchone()["n"]
            raise HTTPException(
                400, f"to confirm, repeat the galaxy's name back: "
                     f"?confirm={room['name']}. This deletes the saves of "
                     f"{membros} player(s), including people who are not you, "
                     f"and there is no undo")

        relatorio = db.delete_room(conn, room_id)
        vivos = db.all_live_hashes(conn)
    liberados = store().delete_unreferenced(vivos)
    return {"deleted": room_id, "name": room["name"], "blobs": liberados,
            **relatorio,
            "message": f"galaxy {room['name']} is gone, with "
                       f"{relatorio['versions']} stored save(s)"}


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
            raise HTTPException(403, "only the room owner can change this")

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
        if "maxJoinAgeDays" in payload:
            campos.append("max_join_age_days = %(max_join_age_days)s")
            valores["max_join_age_days"] = (
                None if payload["maxJoinAgeDays"] is None
                else float(payload["maxJoinAgeDays"]))
        if "listed" in payload:
            campos.append("listed = %(listed)s")
            valores["listed"] = bool(payload["listed"])
        if not campos:
            raise HTTPException(400, "nothing to change")

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
        galaxia = db.galaxy_map(conn, room_id)
    # O NOME DO SISTEMA, que e o que a pessoa ve no mapa estelar do jogo. O
    # `at_system` e um id interno e o `at_body` e um nome de tipo: nenhum dos
    # dois aparece na tela dela, e foi por isso que sairam do site.
    nomes = {str(sistema["systemId"]): (sistema.get("name") or "")
             for sistema in (galaxia.get("systems") or [])}

    def onde(quem):
        if not quem["at_system"]:
            return None
        return (nomes.get(str(quem["at_system"]))
                or f'system {quem["at_system"]}')

    return {"roomId": room_id, "players": [
        {"playerId": r["player_id"], "name": r["display_name"],
         "shipName": r["ship_name"], "system": r["at_system"],
         "systemName": onde(r),
         "x": r["at_x"], "y": r["at_y"], "body": r["at_body"], "ageDays": float(r["age_days"]) if r["age_days"] else None,
         "playing": r["playing"],
         "lastSeen": r["last_seen_at"].isoformat() if r["last_seen_at"] else None}
        for r in roster]}


# ---------------------------------------------------------------------------
# Entrada
# ---------------------------------------------------------------------------

@app.post("/api/v1/rooms/{room_id}/start", status_code=201)
def start_in_room(room_id: str, request: Request,
                  player: dict = Depends(current_player)):
    """Entra na sala com o save de partida dela, sem passar pelo jogo.

    A alternativa ao `join`, e a que deveria ser o caminho normal. O `join`
    exige uma partida criada no Space Haven, e criar uma e cinco passos manuais
    onde tudo pode dar errado. Aqui a sala entrega uma copia da partida de quem
    a fundou, com nome de nave proprio e num corpo celeste livre.

    Nao ha enxerto: a galaxia ja e a da sala, porque a copia veio de dentro
    dela. Nao ha regra de idade: a partida e do dia em que a sala nasceu.
    """
    with db.pool().connection() as conn:
        room = _require_room(conn, room_id)
        senha = request.headers.get("x-room-password", "")
        if room["password_hash"] and rules.hash_token(senha) != room["password_hash"]:
            raise HTTPException(403, "wrong room password")
        if db.get_membership(conn, room_id, player["id"]) is not None:
            raise HTTPException(409, "you are already in this room. Use "
                                     "/checkout to play")
        if db.count_players(conn, room_id) >= room["max_players"]:
            raise HTTPException(409, "the room is full")

        molde = room.get("starter_sha256") or _adopt_starter(conn, room)
        if not molde:
            raise HTTPException(
                409, "this room has no starting save yet: nobody has joined, "
                     "so there is no game to copy. The first person has to "
                     "bring one with `join`")

        # Onde ja ha gente, para a nave nova nao nascer dentro de outra.
        ocupados = {(m["at_x"], m["at_y"]) for m in db.room_roster(conn, room_id)
                    if m["at_x"] and m["at_y"]}
        nome = f"HSS {player['display_name'].upper()[:24]}"

        try:
            with blobs.with_unpacked(store().get(molde)) as folder:
                sf = SaveFile(folder)
                # O MOLDE E CONFERIDO ANTES DE SER COPIADO. Uma sala entregou
                # um molde cujo `<roof>` nao era um teto, e quem recebia a
                # copia via o casco fechado sem ter como saber por que.
                ruim = starter.problems(sf)
                if ruim:
                    raise HTTPException(
                        409, "this room has no usable starting save: "
                             + "; ".join(ruim)
                             + ". Whoever runs the room can set a better one")
                rel = starter.personalise(sf, nome, ocupados)
                sf.save(backup=False)
                described = fingerprint.describe(folder)
                here = presence.read(folder)
                data = blobs.pack_save(folder)
        except HTTPException:
            raise
        except Exception as exc:      # noqa: BLE001
            log.warning("could not build a starting save: %s", exc)
            raise HTTPException(
                500, f"could not build a starting save: {exc}") from exc

        meta = store().put(data)
        version = db.add_version(conn, {
            "room_id": room_id, "player_id": player["id"],
            "sha256": meta["sha256"], "bytes": meta["bytes"],
            "kind": "canonical", "age_days": here["ageDays"],
            "galaxy_digest": described["digest"]})
        db.upsert_membership(conn, room_id, player["id"], here["shipName"],
                             version["id"])
        db.set_position(conn, room_id, player["id"], here["system"],
                        here["x"], here["y"], here["body"])
        db.record_visit(conn, room_id, player["id"], here["system"],
                        here["x"], here["y"])

    return {"roomId": room_id, "versionId": version["id"],
            "ageDays": here["ageDays"], "presence": here,
            "shipName": rel["shipName"], "placedAt": rel["at"],
            "warnings": rel["warnings"],
            "message": ("you are in. The room handed you a starting game; "
                        "use `play` to check it out.")}


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
            raise HTTPException(409, "you are already in this room. Use /checkout "
                                     "to check your save out")
        if db.count_players(conn, room_id) >= room["max_players"]:
            raise HTTPException(409, "the room is full")

        # A conferencia acontece ANTES de gravar blob: lixo nao deve custar
        # disco numa sala aberta.
        try:
            with blobs.with_unpacked(data) as folder:
                described = fingerprint.describe(folder)
                here = presence.read(folder)
        except StorageError as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(400, f"could not read this save: {exc}") from exc

        # Idade primeiro: enxerto nenhum conserta uma colônia de meio ano, e
        # tentar enxertar antes de recusar seria trabalho jogado fora.
        ok, motivo = rules.check_join_age(here["ageDays"], room)
        if not ok:
            raise HTTPException(409, motivo)

        ok, motivo = rules.check_join(described, room)
        if not ok:
            # A galáxia não bate. Antes isso era o fim: a pessoa tinha que
            # recriar a partida acertando cada opção de cenário, sem conseguir
            # conferir nenhuma depois. Agora o servidor conserta — enxerta a
            # galáxia da sala no save dela e adota o resultado.
            #
            # Só o que é da galáxia é substituído; nave, tripulação, banco e
            # pesquisa continuam do jogador (findings 17 e 18).
            if not room["galaxy_sha256"] or "save format" in motivo:
                raise HTTPException(409, motivo)
            try:
                data, described, here = _graft_into(room, data)
            except Exception as exc:      # noqa: BLE001
                raise HTTPException(
                    409, f"{motivo} — and grafting the room's galaxy in "
                         f"failed: {exc}") from exc
            grafted = True
        else:
            grafted = False

        # Depois do enxerto, `here` foi relido do save que vai ser guardado. A
        # idade tem que sair dele também, e não do que chegou.
        day = here["ageDays"]

        meta = store().put(data)
        version = db.add_version(conn, {
            "room_id": room_id, "player_id": player["id"],
            "sha256": meta["sha256"], "bytes": meta["bytes"],
            "kind": "canonical", "age_days": day,
            "galaxy_digest": described["digest"]})
        if not room["galaxy_digest"]:
            with blobs.with_unpacked(data) as folder:
                db.save_galaxy_map(conn, room_id, presence.galaxy_map(folder))
        db.adopt_galaxy(conn, room_id, described["digest"],
                        described["saveVersion"], meta["sha256"])

        # O MOLDE NASCE COM A GALAXIA. A primeira partida que chega e o unico
        # momento em que existe um comeco de verdade: dali em diante todo save
        # e uma colonia em andamento, e copiar uma dessas daria a quem chega
        # depois uma partida que ja foi jogada.
        #
        # So entra se servir. Uma galaxia entregou um molde cuja nave o jogo
        # desenhava de casco fechado, e quem recebia nao tinha como saber que
        # o defeito estava no molde.
        molde_nota = None
        if not room.get("starter_sha256"):
            with blobs.with_unpacked(data) as folder:
                ruins = starter.problems(SaveFile(folder))
            if ruins:
                # NAO GUARDAR CALADO. Quem funda uma galaxia cria a partida e
                # sobe na hora, e e justamente esse save que o jogo ainda nao
                # terminou: o teto da nave so aparece depois de a partida andar
                # um pouco. Guardar assim mesmo entrega casco fechado a todo
                # mundo que chegar, e ninguem descobre a tempo.
                molde_nota = (
                    "this game is too new to be the starting point for other "
                    "people: " + "; ".join(ruins)
                    + ". Play a few minutes and check the save back in, and "
                      "that becomes what newcomers begin from")
                log.warning("not adopting %s as the starting save: %s",
                            meta["sha256"][:12], "; ".join(ruins))
            else:
                db.set_starter(conn, room_id, meta["sha256"])
                molde_nota = ("this game is now the starting point for "
                              "everybody who joins after you")
        db.upsert_membership(conn, room_id, player["id"], here["shipName"],
                             version["id"])
        db.set_position(conn, room_id, player["id"], here["system"],
                        here["x"], here["y"], here["body"])
        db.record_visit(conn, room_id, player["id"], here["system"],
                        here["x"], here["y"])
        _harvest_discovery(conn, room_id, player["id"], data)

    return {"roomId": room_id, "versionId": version["id"],
            "galaxy": described, "ageDays": day, "presence": here,
            "grafted": grafted,
            "starter": molde_nota,
            "message": ("the room's galaxy was grafted into your save, and the "
                        "result is now canonical — check out to get it back. "
                        "Your ship, crew, bank and research are untouched."
                        if grafted else
                        "save adopted as canonical. The server owns it from "
                        "now on.")}


def _player_ship_of(data: bytes):
    """A nave do jogador dentro de um zip de save, com a arvore do jogo.

    Havendo mais de uma, a de mais tripulacao — e a casa (secao 1.10).
    """
    with blobs.with_unpacked(data) as folder:
        sf = SaveFile(folder)
        candidatas = [ship for _doc, ship in sf.ships()
                      if (ship.find("settings") is not None
                          and ship.find("settings").get("of")
                          == presence.PLAYER_FACTION)]
        if not candidatas:
            return None, None
        melhor = max(candidatas,
                     key=lambda sh: len(sh.findall(".//characters/c")))
        return sf.main, copy.deepcopy(melhor)


@app.get("/api/v1/rooms/{room_id}/shop")
def shop_state(room_id: str, player: dict = Depends(current_player)):
    """Os armazens da nave do jogador, e qual deles e a loja.

    Os armazens saem do save canonico guardado — o servidor nao adivinha o que
    ha na nave de ninguem, ele le o que a pessoa devolveu.
    """
    with db.pool().connection() as conn:
        _require_room(conn, room_id)
        membership = db.get_membership(conn, room_id, player["id"])
        if membership is None:
            raise HTTPException(403, "you are not in this room")
        versao = db.get_version(conn, membership["canonical_id"])
    if versao is None:
        raise HTTPException(409, "this membership has no canonical save yet")

    _game, nave = _player_ship_of(store().get(versao["sha256"]))
    if nave is None:
        raise HTTPException(409, "could not find your ship in the stored save")

    armazens = shopping.storages(nave)
    escolhida = membership["shop_storage_id"]
    return {
        "roomId": room_id,
        "shopStorageId": escolhida,
        "storages": [{
            "id": a["id"], "at": [a["x"], a["y"]],
            "stacks": a["stacks"], "units": a["units"],
            "isShop": a["id"] == escolhida,
            "resources": a["contents"],
        } for a in armazens],
        "message": ("nothing is for sale: pick a storage and move cargo into "
                    "it with the game's own interface"
                    if not escolhida else
                    "what is in that storage is what your neighbours can buy"),
    }


@app.put("/api/v1/rooms/{room_id}/shop")
def set_shop(room_id: str, payload: dict, player: dict = Depends(current_player)):
    """Escolhe o armazem que e a loja, ou desliga a loja com `null`.

    O id e conferido contra o save guardado. Aceitar um id que nao existe daria
    uma loja que nunca enche, e a pessoa passaria a sessao inteira sem entender
    por que ninguem compra nada dela.
    """
    escolhida = payload.get("storageId")
    with db.pool().connection() as conn:
        _require_room(conn, room_id)
        membership = db.get_membership(conn, room_id, player["id"])
        if membership is None:
            raise HTTPException(403, "you are not in this room")
        if escolhida is not None:
            versao = db.get_version(conn, membership["canonical_id"])
            if versao is None:
                raise HTTPException(409, "this membership has no canonical save")
            _game, nave = _player_ship_of(store().get(versao["sha256"]))
            existentes = {a["id"] for a in shopping.storages(nave or [])} \
                if nave is not None else set()
            if str(escolhida) not in existentes:
                raise HTTPException(
                    400, f"there is no storage {escolhida} on your ship. "
                         f"The ones there are: "
                         f"{', '.join(sorted(existentes)) or 'none'}")
            escolhida = str(escolhida)
        db.set_shop_storage(conn, room_id, player["id"], escolhida)

    return {"roomId": room_id, "shopStorageId": escolhida,
            "message": ("your shop is closed; nothing of yours is for sale"
                        if escolhida is None else
                        f"storage {escolhida} is your shop. What you move into "
                        f"it is what your neighbours can buy")}


# ---------------------------------------------------------------------------
# Ciclo de sessao
# ---------------------------------------------------------------------------

def _harvest_discovery(conn, room_id: str, player_id: int,
                       data: bytes) -> int:
    """Recolhe o que este save conhece para a sala.

    Roda em toda chegada de save — entrada, checkpoint e devolucao. Um
    checkpoint e o que faz a descoberta aparecer para os outros DURANTE a
    sessao, em vez de so quando ela acaba.

    Falhar aqui nao pode custar o save de ninguem: descoberta e enfeite
    coletivo, e a custodia e o que nao pode quebrar.
    """
    try:
        with blobs.with_unpacked(data) as folder:
            achados = discovering.visited(SaveFile(folder))
        return db.record_discoveries(conn, room_id, player_id, achados)
    except Exception as exc:      # noqa: BLE001
        log.warning("could not read discovery from a save: %s", exc)
        return 0


def _share_discovery(room_id: str, data: bytes) -> tuple:
    """Poe a descoberta da sala no save que esta sendo entregue.

    Muda so os bytes entregues; o que esta guardado continua como veio. O
    digest da galaxia nao se mexe porque ele conta ESTRELAS (findings 19), e
    era exatamente para sobreviver a esta divergencia que ele foi mudado.
    """
    with db.pool().connection() as conn:
        sala = db.room_discoveries(conn, room_id)
    if not sala:
        return data, {"flagged": 0, "inserted": 0, "skipped": 0}
    try:
        with blobs.with_unpacked(data) as folder:
            sf = SaveFile(folder)
            report = discovering.merge(sf, sala)
            if not (report["flagged"] or report["inserted"]):
                return data, report
            sf.save(backup=False)
            return blobs.pack_save(folder), report
    except Exception as exc:      # noqa: BLE001
        # Entregar o save sem a descoberta e muito melhor que nao entregar.
        log.warning("could not share discovery into a save: %s", exc)
        return data, {"flagged": 0, "inserted": 0, "skipped": 0, "error": str(exc)}


# Quantos vizinhos cabem num setor. Uma sala de sessenta e quatro pessoas junta
# muita gente no sistema inicial, e um setor com vinte vitrines nao e uma sala
# viva, e um estacionamento. Tres cabe na tela e no save.
MAX_NEIGHBOURS = 3

# A faccao das vitrines e quanto elas carregam. Fase 2 e o vizinho aparecer;
# fase 3 e ele negociar, e ai o estoque vira consignacao.
NEIGHBOUR_FACTION = "Civilian"
NEIGHBOUR_CREDITS = "5000"


def _adopt_starter(conn, room: dict) -> str | None:
    """Escolhe o molde desta galaxia: a partida valida mais nova que existe.

    O molde nasce com a galaxia, e a captura acontece no `join`. Uma galaxia
    criada antes disso existir fica sem molde para sempre, e o mesmo acontece
    quando a primeira partida a chegar e prematura demais para servir — o que
    e comum, porque um save gravado logo apos o NEW GAME ainda nao tem o teto
    da nave montado.

    Entao procuramos: a versao de menor idade de jogo que passa na conferencia.
    Menor idade porque um molde deve ser um comeco; passar na conferencia
    porque entregar uma partida que o jogo desenha errado ja custou uma sessao.
    """
    # IDADE TEM TETO. "A de menor idade que passe" nao basta: quando a unica
    # partida restante era uma colonia de dezessete dias, ela foi adotada, e
    # quem entrou depois recebeu a nave madura de outra pessoa como ponto de
    # partida. Um molde e um comeco, e o teto e o mesmo que decide se uma
    # partida e madura demais para entrar na galaxia.
    teto = float(room.get("max_join_age_days") or 5)
    candidatas = conn.execute(
        """SELECT id, sha256, age_days FROM save_version
            WHERE room_id = %s AND kind = 'canonical' AND age_days <= %s
            ORDER BY age_days, id LIMIT 12""",
        (room["id"], teto)).fetchall()
    for linha in candidatas:
        try:
            with blobs.with_unpacked(store().get(linha["sha256"])) as folder:
                if starter.problems(SaveFile(folder)):
                    continue
        except Exception as exc:      # noqa: BLE001
            log.warning("could not read version %s: %s", linha["id"], exc)
            continue
        db.set_starter(conn, room["id"], linha["sha256"])
        log.info("adopted version %s (age %s) as the starting save for %s",
                 linha["id"], linha["age_days"], room["id"])
        return linha["sha256"]
    return None


def _room_stars(conn, room: dict) -> dict:
    """As estrelas que esta sala conhece, montando na primeira vez.

    Salas criadas antes da coluna existir nao tem nada guardado; a galaxia
    doadora e que responde por elas, e o resultado fica gravado para nao ser
    recalculado a cada retirada.
    """
    guardadas = room.get("galaxy_stars")
    if guardadas:
        return guardadas
    if not room.get("galaxy_sha256"):
        return {}
    try:
        with blobs.with_unpacked(store().get(room["galaxy_sha256"])) as folder:
            estrelas = fingerprint.stars_of(folder)
    except Exception as exc:      # noqa: BLE001
        log.warning("could not read the room's galaxy: %s", exc)
        return {}
    db.set_galaxy_stars(conn, room["id"], estrelas)
    return estrelas


def _check_galaxy(conn, room: dict, folder: str) -> None:
    """O save que chegou e desta galaxia? Levanta 409 se nao for.

    Substitui a comparacao de digest, que era igualdade sobre um conjunto que
    CRESCE. Medido numa sessao recusada de verdade: 64 sistemas na entrega, 65
    na devolucao, e as 64 estrelas em comum identicas byte a byte. O save
    estava certo — o portao e que estava errado, e custou a sessao de alguem.

    Os sistemas novos entram no que a sala conhece: ela aprende a galaxia no
    ritmo em que as pessoas a exploram.
    """
    minhas = fingerprint.stars_of(folder)
    delas = _room_stars(conn, room)
    ok, motivo = fingerprint.agree(delas, minhas)
    if not ok:
        raise HTTPException(409, f"{motivo}. This is not the save that was "
                                 f"lent out")
    novas = {k: v for k, v in minhas.items() if k not in delas}
    if novas and delas:
        db.set_galaxy_stars(conn, room["id"], {**delas, **novas})


def _neighbour_ship(conn, membership: dict) -> tuple:
    """A NAVE DE VERDADE deste vizinho, e o que ele pos a venda.

    Sai do save canonico guardado, entao e o que ele tinha quando devolveu — o
    estoque da vitrine muda de uma sessao dele para a outra, nao em tempo real.
    Nao ha como ser diferente: o save dele so chega aqui quando ele devolve.

    POR QUE A NAVE DELE, E NAO UM CASCO QUALQUER

    A primeira versao montava a vitrine sobre uma nave NPC do proprio save de
    destino, e o resultado era honesto mas mudo: aparecia uma nave civil
    sorteada, com o nome do vizinho colado nela. Quem chegava nao reconhecia
    nada. A nave de alguem em Space Haven e desenhada modulo por modulo ao
    longo de dezenas de horas — e a coisa mais reconhecivel que uma pessoa tem
    para mostrar.

    O `<l id>` de dentro de uma nave e LOCAL a ela: duas naves do mesmo save
    medido compartilhavam oito. Entao a copia entra sem colidir com o que ja
    estava la, e `renumber_ship` cuida do `sid` e dos `entId` da tripulacao,
    que sao globais.

    Devolve `(nave, a_venda)`; a nave e None quando este vizinho ainda nao
    devolveu save nenhum, e ai quem chama cai no casco local.
    """
    if not membership.get("canonical_id"):
        return None, {}
    versao = db.get_version(conn, membership["canonical_id"])
    if versao is None:
        return None, {}
    try:
        _game, nave = _player_ship_of(store().get(versao["sha256"]))
        if nave is None:
            return None, {}
        loja = membership.get("shop_storage_id")
        return nave, (shopping.on_sale(nave, loja) if loja else {})
    except Exception as exc:      # noqa: BLE001
        log.warning("could not read a neighbour's ship: %s", exc)
        return None, {}


def _neighbours_of(conn, room_id: str, player_id: int) -> list:
    """Quem mais esta no mesmo sistema, com lugar conhecido."""
    eu = db.get_membership(conn, room_id, player_id)
    if eu is None or not eu["at_system"]:
        return []
    fora = []
    for outro in db.room_roster(conn, room_id):
        if outro["player_id"] == player_id:
            continue
        if outro["at_system"] != eu["at_system"]:
            continue
        if not (outro["at_x"] and outro["at_y"]):
            continue
        fora.append(outro)
    # Mais antigos na sala primeiro: um teto tem que ser estavel, senao o
    # vizinho de ontem some hoje sem nada ter mudado.
    fora.sort(key=lambda r: r["joined_at"])
    return fora[:MAX_NEIGHBOURS]


def _place_neighbours(conn, room_id: str, player_id: int,
                      data: bytes) -> tuple:
    """Monta as vitrines dos vizinhos no save que esta sendo entregue.

    A vitrine e montada sobre um casco NPC **do proprio save de destino**
    (findings item 10): a neblina so se sustenta se o casco nunca foi
    explorado, e a nave de um jogador sempre foi. De quebra, nada da maquina de
    outro jogador atravessa.

    Devolve `(zip, sids, consignacoes, relatorio)`. Os `sids` sao o que o
    `checkin` vai tirar de volta — sem isso a vitrine vira parte permanente da
    partida da pessoa. As `consignacoes` sao a foto de cada prateleira, que e
    contra o que a apuracao compara o que voltou.

    Falhar aqui nunca custa a sessao: sem vitrine a sala continua jogavel, e
    entregar um save quebrado seria muito pior que entregar um save sozinho.
    """
    vizinhos = _neighbours_of(conn, room_id, player_id)
    relatorio = {"placed": 0, "skipped": [], "neighbours": []}
    if not vizinhos:
        return data, [], [], relatorio

    sids: list = []
    consignacoes: list = []
    try:
        with blobs.with_unpacked(data) as folder:
            sf = SaveFile(folder)
            for outro in vizinhos:
                nome = f"{outro['ship_name'] or 'ship'} ({outro['display_name']})"
                try:
                    # A NAVE DELE, se ja tivermos uma. E o que faz a vitrine
                    # ser reconhecivel: quem chega ve o desenho que a pessoa
                    # construiu, nao uma nave civil sorteada com o nome dela
                    # colado. `<l id>` e local a nave, entao a copia entra sem
                    # colidir com o que ja estava no setor.
                    #
                    # O QUE ELE POS A VENDA vira a carga. Sem isto a loja abre
                    # com prateleira vazia: o jogo gera uma lista do que ELE
                    # quer comprar, e a pessoa clica em "new trade" e nao acha
                    # nada para levar.
                    molde, a_venda = _neighbour_ship(conn, outro)
                    # SO o casco local esconde o interior de verdade: a neblina
                    # so se sustenta num casco que nunca foi explorado, e a
                    # nave de um jogador sempre foi (findings item 10). Com a
                    # nave dele, o interior fica a vista — e é o preço de ela
                    # ser reconhecivel.
                    modo_casco = False
                    if molde is None:
                        cascos = storefront.live_npc_ships(sf)
                        if not cascos:
                            relatorio["skipped"].append(
                                f"{outro['display_name']}: no ship of theirs "
                                f"stored yet, and no live NPC ship here to "
                                f"stand in for it")
                            continue
                        molde, modo_casco = cascos[0], True
                    estoque = ",".join(f"{r}:{q}" for r, q in
                                       sorted(a_venda.items())) or None
                    rel = storefront.inject_ship(
                        sf, molde, faction=NEIGHBOUR_FACTION,
                        credits=NEIGHBOUR_CREDITS, name=nome,
                        hull_mode=modo_casco,
                        crew_side=NEIGHBOUR_FACTION, stock=estoque,
                        at=(outro["at_x"], outro["at_y"]),
                        system_id=outro["at_system"])
                    novo_sid = rel["fleet"]["createdShipId"]
                    sids.append(novo_sid)
                    # A FOTO. Uma venda e a diferenca entre dois momentos, e
                    # este e o primeiro deles. Sem isto o check-in recebe uma
                    # prateleira sem nada com que compara-la.
                    nave_nova = storefront.find_by_sid(sf, novo_sid)
                    consignacoes.append({
                        "sid": str(novo_sid),
                        "seller_id": outro["player_id"],
                        "stock": {r: int(q) for r, q in a_venda.items()},
                        "credits": (storefront.bank_credits(nave_nova)
                                    if nave_nova is not None else None),
                    })
                    relatorio["placed"] += 1
                    relatorio["neighbours"].append(nome)
                    relatorio.setdefault("stock", {})[nome] = a_venda
                except Exception as exc:      # noqa: BLE001
                    relatorio["skipped"].append(
                        f"{outro['display_name']}: {exc}")
            if not sids:
                return data, [], [], relatorio
            sf.save(backup=False)
            return blobs.pack_save(folder), sids, consignacoes, relatorio
    except Exception as exc:      # noqa: BLE001
        log.warning("could not place neighbours: %s", exc)
        return data, [], [], {"placed": 0, "skipped": [str(exc)],
                              "neighbours": []}


def _pay_settlements(conn, room_id: str, player_id: int, membership: dict,
                     lease_id: int, data: bytes) -> tuple:
    """Paga ao vendedor, no save que esta saindo, o que venderam por ele.

    A outra metade de `_settle_neighbours`. A venda aconteceu na partida de
    outra pessoa, dias atras talvez, contra uma nave que o servidor inventou —
    e este e o unico momento em que ela vira dinheiro para quem vendeu, porque
    e o unico momento em que temos o save dele aberto.

    Duas escritas, e as duas importam:

        creditos  ->  game/playerBank        o que o comprador pagou
        carga     ->  o armazem-loja dele    o que saiu da prateleira

    So creditar seria imprimir dinheiro: a mercadoria continuaria no deposito e
    o dono teria sido pago por ela. So debitar seria confisco.

    Marcado como pago apenas depois de o save ter sido efetivamente reescrito.
    Se qualquer coisa falhar aqui, o acerto continua em aberto e sai no proximo
    `checkout` — perder uma venda por engano e muito pior que paga-la tarde.
    """
    pendentes = db.unpaid_settlements(conn, room_id, player_id)
    relatorio = {"paid": 0, "credits": 0, "goods": {}, "shortfall": {}}
    if not pendentes:
        return data, relatorio

    loja = membership.get("shop_storage_id")
    try:
        with blobs.with_unpacked(data) as folder:
            sf = SaveFile(folder)
            jogo = sf.main
            nave = _ship_in(sf)
            if nave is None:
                log.warning("settlements pending but no player ship in the save")
                return data, relatorio

            creditos = sum(int(linha["credits"]) for linha in pendentes)
            if creditos:
                shopping.pay(jogo, creditos)
            relatorio["credits"] = creditos

            for linha in pendentes:
                for recurso, quantia in (linha["goods"] or {}).items():
                    relatorio["goods"][recurso] = (
                        relatorio["goods"].get(recurso, 0) + int(quantia))

            # A carga sai do armazem-loja, e SO dele. Se a pessoa moveu o
            # estoque entre a venda e agora, sai menos — e isso e reportado,
            # nao coberto por outro movel. A loja e o unico lugar autorizado.
            if loja:
                for recurso, quantia in relatorio["goods"].items():
                    saiu = shopping.take(nave, loja, recurso, int(quantia))
                    if saiu < int(quantia):
                        relatorio["shortfall"][recurso] = int(quantia) - saiu
            elif relatorio["goods"]:
                relatorio["shortfall"] = dict(relatorio["goods"])

            sf.save(backup=False)
            data = blobs.pack_save(folder)
    except Exception as exc:      # noqa: BLE001
        log.warning("could not pay settlements: %s", exc)
        return data, {"paid": 0, "credits": 0, "goods": {}, "shortfall": {},
                      "error": str(exc)}

    db.mark_settlements_paid(conn, [linha["id"] for linha in pendentes],
                             lease_id)
    relatorio["paid"] = len(pendentes)
    return data, relatorio


def _ship_in(sf: SaveFile):
    """A nave do jogador dentro de um save ja aberto — a de mais tripulacao."""
    candidatas = [ship for _doc, ship in sf.ships()
                  if (ship.find("settings") is not None
                      and ship.find("settings").get("of")
                      == presence.PLAYER_FACTION)]
    if not candidatas:
        return None
    return max(candidatas, key=lambda sh: len(sh.findall(".//characters/c")))


def _settle_neighbours(conn, room_id: str, buyer_id: int, lease: dict,
                       data: bytes) -> dict:
    """Apura o que foi vendido em cada vitrine, ANTES de remove-las.

    A ordem nao e detalhe: `_strip_neighbours` apaga a prova. Depois dela a
    prateleira nao existe mais e nao ha o que comparar.

    Nada aqui pode custar a devolucao. Se a apuracao falhar, o save volta do
    mesmo jeito e o que se perde e uma venda — o contrario, recusar o save de
    alguem por causa da nossa contabilidade, seria muito pior.
    """
    consignacoes = (lease or {}).get("consignments") or []
    relatorio = {"settled": 0, "credits": 0, "goods": {}, "notes": []}
    if not consignacoes:
        return relatorio
    try:
        with blobs.with_unpacked(data) as folder:
            sf = SaveFile(folder)
            for foto in consignacoes:
                nave = storefront.find_by_sid(sf, foto["sid"])
                achado = settle.reconcile(
                    foto,
                    storefront.read_stock(nave) if nave is not None else None,
                    storefront.bank_credits(nave) if nave is not None else None)
                relatorio["notes"] += achado["notes"]
                if not achado["sold"] and not achado["credits"]:
                    continue
                db.record_settlement(
                    conn, room_id, foto["seller_id"], buyer_id, lease["id"],
                    foto["sid"], achado["credits"], achado["sold"],
                    achado["notes"])
                relatorio["settled"] += 1
                relatorio["credits"] += achado["credits"]
                for recurso, quantia in achado["sold"].items():
                    relatorio["goods"][recurso] = (
                        relatorio["goods"].get(recurso, 0) + quantia)
    except Exception as exc:      # noqa: BLE001
        log.warning("could not settle storefront sales: %s", exc)
        relatorio["notes"].append(str(exc))
    return relatorio


def _strip_neighbours(lease: dict, data: bytes, sids=None) -> bytes:
    """Tira as vitrines antes de guardar o que voltou.

    E o par obrigatorio de `_place_neighbours`. Sem ele a nave de um vizinho
    ficaria guardada como parte da partida de quem devolveu, e voltaria
    empilhada a cada sessao.
    """
    sids = sids or (lease or {}).get("injected_sids") or []
    if not sids:
        return data
    try:
        with blobs.with_unpacked(data) as folder:
            sf = SaveFile(folder)
            rel = storefront.remove_storefronts(sf, sids)
            if not rel["ships"] and not rel["fleets"]:
                return data
            sf.save(backup=False)
            return blobs.pack_save(folder)
    except Exception as exc:      # noqa: BLE001
        # Guardar com a vitrine dentro e ruim; recusar a devolucao e pior.
        log.warning("could not strip neighbour storefronts: %s", exc)
        return data


def _graft_into(room: dict, data: bytes) -> tuple:
    """Puts the room's galaxy into an arriving player's save.

    Unpacks both — the room's donor and the newcomer's — grafts, and repacks.
    Two saves open on disk at once, briefly; both are cleaned up.

    Returns the new zip, its galaxy description and the player's presence read
    from it, so the caller stores what it actually kept.
    """
    donor_blob = store().get(room["galaxy_sha256"])
    with blobs.with_unpacked(donor_blob) as donor_dir:
        with blobs.with_unpacked(data) as player_dir:
            donor, player = SaveFile(donor_dir), SaveFile(player_dir)
            grafting.graft(donor, player)
            player.save(backup=False)
            described = fingerprint.describe(player_dir)
            here = presence.read(player_dir)
            repacked = blobs.pack_save(player_dir)
    if described["digest"] != room["galaxy_digest"]:
        raise RuntimeError(
            f"the graft produced galaxy {described['digest']}, not the room's "
            f"{room['galaxy_digest']}")
    return repacked, described, here


@app.post("/api/v1/rooms/{room_id}/checkout")
def checkout(room_id: str, player: dict = Depends(current_player)):
    """Abre o emprestimo e devolve o save. O corpo da resposta e o zip."""
    with db.pool().connection() as conn:
        room = _require_room(conn, room_id)
        membership = db.get_membership(conn, room_id, player["id"])
        if membership is None:
            raise HTTPException(403, "you are not in this room. Use /join with "
                                     "a save created on the room's seed")
        db.expire_leases(conn)
        existing = db.open_lease(conn, room_id, player["id"])
        ok, motivo = rules.can_checkout(existing, db.now())
        if not ok:
            raise HTTPException(409, motivo)

        version = db.get_version(conn, membership["canonical_id"])
        if version is None:
            raise HTTPException(500, "this membership has no canonical save; that is a "
                                     "server bug, not yours")
        expires = rules.lease_expiry(db.now(), room["lease_hours"])
        try:
            lease = db.create_lease(conn, room_id, player["id"],
                                    version["id"], expires)
        except psycopg.errors.UniqueViolation as exc:
            # O indice parcial pegou uma corrida. E o desenho funcionando.
            raise HTTPException(409, "another checkout of this save happened "
                                     "at the same time. Try again") from exc
        data = store().get(version["sha256"])

    # A descoberta da sala entra no que sai, nao no que fica guardado. Quem
    # nunca foi ao sistema 40 recebe o mapa de quem foi.
    data, partilha = _share_discovery(room_id, data)

    # E os vizinhos do mesmo sistema aparecem no setor. Os sids ficam no
    # emprestimo porque e o `checkin` que tem de tira-los de volta.
    with db.pool().connection() as conn:
        # O que venderam por ele enquanto esteve fora vira dinheiro e sai do
        # deposito AGORA: e o unico momento em que o save dele esta aberto.
        data, acertos = _pay_settlements(conn, room_id, player["id"],
                                         membership, lease["id"], data)

        data, sids, consignacoes, vizinhanca = _place_neighbours(
            conn, room_id, player["id"], data)
        if sids:
            db.set_injected_sids(conn, lease["id"], sids)
            db.set_consignments(conn, lease["id"], consignacoes)

    return Response(
        content=data, media_type="application/zip",
        headers={
            "X-Discovery-Flagged": str(partilha["flagged"]),
            "X-Discovery-Inserted": str(partilha["inserted"]),
            "X-Neighbours": str(vizinhanca["placed"]),
            # Quais naves o servidor montou. O mod usa isto para calar o
            # chamado automatico delas sem calar os NPCs de verdade: o jogo so
            # sabe chamar por faccao, nunca por nave.
            "X-Neighbour-Sids": ",".join(str(x) for x in sids),
            # Qual armazem e a loja, para o mod poder mostrar SHOP: ON no
            # armazem certo. Sem isto o canal e so de saida, e a cada sessao o
            # botao esqueceria o que a pessoa escolheu na anterior.
            "X-Shop-Storage": str(membership["shop_storage_id"] or ""),
            # O que foi vendido por voce enquanto esteve fora, ja creditado
            # neste save. O cliente mostra, e o mod escreve no log do jogo.
            "X-Sales-Paid": str(acertos["paid"]),
            "X-Sales-Credits": str(acertos["credits"]),
            "Content-Disposition": f'attachment; filename="{room_id}-save.zip"',
            "X-Lease-Id": str(lease["id"]),
            "X-Lease-Expires": expires.isoformat(),
            "X-Version-Id": str(version["id"]),
        })


@app.post("/api/v1/rooms/{room_id}/checkpoint")
async def checkpoint(room_id: str, request: Request,
                     player: dict = Depends(current_player)):
    """Recebe um autosave no meio da sessao, sem fechar o emprestimo.

    POR QUE ISTO EXISTE

    Uma sessao dura horas e so chega ao servidor no fim. Ate la, o mapa da sala
    mostra onde a pessoa estava quando saiu da vez passada, e uma queda de luz
    custa a sessao inteira. O autosave ja acontece — isto so o aproveita.

    O QUE ELE NAO FAZ

    Nao mexe no canonico, nao fecha o emprestimo e nao muda de quem e a vez. E
    historico e presenca, nao entrega: quem decide o que fica e o `checkin`, e e
    isso que mantem a regra de uma sessao por vez intacta.

    A galaxia continua sendo conferida. Um checkpoint de outra partida seria
    outra pessoa jogando outra coisa, e entraria no mapa como se fosse esta.
    """
    data = await body_bytes(request)

    with db.pool().connection() as conn:
        room = _require_room(conn, room_id)
        db.expire_leases(conn)
        lease = conn.execute(
            """SELECT * FROM lease
                WHERE room_id = %s AND player_id = %s AND state = 'open'
                ORDER BY issued_at DESC LIMIT 1""",
            (room_id, player["id"])).fetchone()
        if lease is None:
            raise HTTPException(
                409, "no open lease: a checkpoint belongs to a session that is "
                     "running. Check the save out first")

        data = _strip_neighbours(
            lease, data, db.all_injected_sids(conn, room_id, player["id"]))

        try:
            with blobs.with_unpacked(data) as folder:
                described = fingerprint.describe(folder)
                here = presence.read(folder)
                day = here["ageDays"]
                _check_galaxy(conn, room, folder)
        except HTTPException:
            raise
        except StorageError as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(400, f"could not read this save: {exc}") from exc

        meta = store().put(data)
        version = db.add_version(conn, {
            "room_id": room_id, "player_id": player["id"],
            "sha256": meta["sha256"], "bytes": meta["bytes"],
            "kind": "checkpoint", "age_days": day,
            "galaxy_digest": described["digest"]})
        # A presenca anda junto: e o que faz o mapa da sala se mexer durante a
        # sessao em vez de so no fim dela.
        db.set_position(conn, room_id, player["id"], here["system"],
                        here["x"], here["y"], here["body"])
        db.record_visit(conn, room_id, player["id"], here["system"],
                        here["x"], here["y"])
        novos = _harvest_discovery(conn, room_id, player["id"], data)
        # OS NOMES DE SISTEMA CHEGAM AQUI TAMBEM. O jogo so batiza um sistema
        # quando alguem chega perto, e uma galaxia recem-fundada nao tem nome
        # nenhum: o mapa da pagina ficava anonimo ate a primeira devolucao. O
        # banco preenche nome vazio e nunca sobrescreve um que ja existe, entao
        # atualizar a cada autosave so acrescenta.
        with blobs.with_unpacked(data) as folder:
            db.save_galaxy_map(conn, room_id, presence.galaxy_map(folder))
        pruned = _prune(conn, room_id, player["id"], room["retention_n"])

    return {"roomId": room_id, "versionId": version["id"], "ageDays": day,
            "presence": here, "pruned": pruned, "bytes": meta["bytes"],
            "discovered": novos,
            "message": "checkpoint stored. The room can see where you are."}


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

        # A APURACAO VEM PRIMEIRO, e a ordem nao e detalhe: `_strip_neighbours`
        # apaga a prateleira, e depois disso nao ha o que comparar. Aqui e no
        # `checkin`, nao no `checkpoint`: um checkpoint e o meio da sessao, e
        # apurar la contaria a mesma venda duas vezes.
        vendas = _settle_neighbours(conn, room_id, player["id"], lease, data)

        # As vitrines saem ANTES de qualquer leitura: o que for guardado, o
        # que entrar no mapa e o que a proxima retirada entregar tem de ser a
        # partida da pessoa, sem as naves que o servidor emprestou.
        #
        # E o historico inteiro, nao so este emprestimo: uma vitrine que
        # escapou de uma sessao anterior nunca mais seria procurada.
        data = _strip_neighbours(
            lease, data, db.all_injected_sids(conn, room_id, player["id"]))

        try:
            with blobs.with_unpacked(data) as folder:
                described = fingerprint.describe(folder)
                here = presence.read(folder)
                day = here["ageDays"]
                # A galaxia tem que ser a mesma — mas ela CRESCE enquanto se
                # joga, e comparar por igualdade recusava save legitimo.
                _check_galaxy(conn, room, folder)
        except HTTPException:
            raise
        except StorageError as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(400, f"could not read this save: {exc}") from exc

        meta = store().put(data)
        version = db.add_version(conn, {
            "room_id": room_id, "player_id": player["id"],
            "sha256": meta["sha256"], "bytes": meta["bytes"],
            "kind": "canonical", "age_days": day,
            "galaxy_digest": described["digest"]})
        # Os nomes de sistema que o jogador descobriu jogando entram no mapa
        # da sala. A posicao ja estava la desde a primeira entrada.
        with blobs.with_unpacked(data) as folder:
            db.save_galaxy_map(conn, room_id, presence.galaxy_map(folder))
        # A SEGUNDA CHANCE DE QUEM FUNDOU. O save do `join` costuma ser novo
        # demais para servir de molde, e este e o proximo que chega da mesma
        # pessoa, ja com a partida andada. Sem isto a galaxia so ganharia molde
        # quando alguem passasse por `/start`, que e tarde: a essa altura ja ha
        # gente esperando.
        if not room.get("starter_sha256"):
            with blobs.with_unpacked(data) as folder:
                if not starter.problems(SaveFile(folder)):
                    db.set_starter(conn, room_id, meta["sha256"])
                    log.info("version %s became the starting save for %s",
                             version["id"], room_id)

        db.close_lease(conn, lease["id"], version["id"])
        db.upsert_membership(conn, room_id, player["id"], here["shipName"],
                             version["id"])
        db.set_position(conn, room_id, player["id"], here["system"],
                        here["x"], here["y"], here["body"])
        db.record_visit(conn, room_id, player["id"], here["system"],
                        here["x"], here["y"])
        novos = _harvest_discovery(conn, room_id, player["id"], data)
        pruned = _prune(conn, room_id, player["id"], room["retention_n"])

    return {"roomId": room_id, "versionId": version["id"], "ageDays": day,
            "presence": here, "pruned": pruned, "discovered": novos,
            "sales": vendas,
            "message": "save received and stored. It is what the others see now."}


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
    quantas = db.delete_versions(conn, [v["id"] for v in podar])
    # E VARRE OS ARQUIVOS. A poda tirava a linha e deixava o blob: medido, 69
    # arquivos orfaos ocupando 19,6 MB de um total de 21,9. So a exclusao de
    # conta varria, entao o lixo se acumulava indefinidamente num servidor onde
    # ninguem sai.
    if quantas:
        try:
            store().delete_unreferenced(db.all_live_hashes(conn))
        except Exception as exc:      # noqa: BLE001
            log.warning("could not sweep unreferenced saves: %s", exc)
    return quantas


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
        raise HTTPException(503, f"database unavailable: {exc}") from exc


@app.get("/", response_class=HTMLResponse)
def index(request: Request, lang: str = ""):
    """As salas abertas. É a vitrine: ver antes de decidir se quer entrar."""
    idioma = i18n.pick(request.headers.get("accept-language", ""), lang)
    with db.pool().connection() as conn:
        rooms = db.list_rooms(conn)
    return pages.room_list([dict(r) for r in rooms], idioma)


@app.get("/galaxy/{room_id}", response_class=HTMLResponse)
def room_web(room_id: str, request: Request, lang: str = "",
             new: str = ""):
    """A sala como página. Sem conta, sem instalar nada — é o degrau 2 da 2.11."""
    idioma = i18n.pick(request.headers.get("accept-language", ""), lang)
    with db.pool().connection() as conn:
        room = db.get_room(conn, room_id)
        if room is None:
            raise HTTPException(404, f"no room {room_id}")
        roster = db.room_roster(conn, room_id)
        galaxy = db.galaxy_map(conn, room_id)
        visits = db.room_visits(conn, room_id)
    return pages.room_page(dict(room), [dict(r) for r in roster], galaxy,
                           idioma, visits, just_made=bool(new))


@app.get("/galaxy/{room_id}/join", response_class=HTMLResponse)
def join_web(room_id: str, request: Request, lang: str = ""):
    """Como entrar nesta sala, para quem chegou por um convite.

    O resto do site mostra a sala viva e depois deixa a pessoa sozinha. Quem
    chega por um link no Discord nao tem como adivinhar que existe um cliente,
    onde ele esta, nem que entrar e uma coisa que se faz uma vez so.
    """
    idioma = i18n.pick(request.headers.get("accept-language", ""), lang)
    with db.pool().connection() as conn:
        room = db.get_room(conn, room_id)
        if room is None:
            raise HTTPException(404, f"no room {room_id}")
        quantos = db.count_players(conn, room_id)
    return pages.join_page(dict(room), idioma, quantos,
                           quantos >= room["max_players"])


# Os caminhos antigos. Uma galaxia se chamava sala, e antes disso o endereco
# era em portugues. Links ja compartilhados num Discord nao morrem por causa de
# uma troca de vocabulario nossa.
@app.get("/sala/{room_id}", response_class=HTMLResponse)
def room_web_pt(room_id: str):
    from fastapi.responses import RedirectResponse
    return RedirectResponse(f"/galaxy/{room_id}?lang=pt", status_code=308)


@app.get("/room/{room_id}", response_class=HTMLResponse)
def room_web_old(room_id: str, lang: str = ""):
    from fastapi.responses import RedirectResponse
    return RedirectResponse(f"/galaxy/{room_id}?lang={lang}", status_code=308)


@app.get("/room/{room_id}/join", response_class=HTMLResponse)
def join_web_old(room_id: str, lang: str = ""):
    from fastapi.responses import RedirectResponse
    return RedirectResponse(f"/galaxy/{room_id}/join?lang={lang}",
                            status_code=308)


@app.get("/new-room", response_class=HTMLResponse)
def new_room_old(lang: str = ""):
    from fastapi.responses import RedirectResponse
    return RedirectResponse(f"/new-galaxy?lang={lang}", status_code=308)


# ---------------------------------------------------------------------------
# Onboarding pela web
# ---------------------------------------------------------------------------
#
# O cliente de linha de comando deixa de ser a porta de entrada. Quem chega pelo
# Discord registra e cria sala no navegador, e só instala alguma coisa quando
# for de fato jogar.

COOKIE = "sgalaxy_token"


def _web_player(request: Request) -> dict | None:
    """Quem está conectado, pelo cookie. Sem cookie não é erro: é visitante."""
    token = request.cookies.get(COOKIE, "")
    if not token:
        return None
    with db.pool().connection() as conn:
        row = db.player_by_token(conn, rules.hash_token(token))
    return dict(row) if row and not row["blocked"] else None


def _set_session(response, token: str) -> None:
    # HttpOnly tira o token do alcance de qualquer script; SameSite=Strict barra
    # POST vindo de outro site, que é a proteção de CSRF destes formulários.
    response.set_cookie(COOKIE, token, httponly=True, samesite="strict",
                        max_age=60 * 60 * 24 * 365, path="/")


@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request, lang: str = ""):
    idioma = i18n.pick(request.headers.get("accept-language", ""), lang)
    return pages.register_form(idioma, needs_invite=bool(INVITE_ONLY))


@app.post("/register", response_class=HTMLResponse)
def register_submit(request: Request, name: str = Form(""),
                    invite: str = Form(""), lang: str = ""):
    idioma = i18n.pick(request.headers.get("accept-language", ""), lang)
    pede = bool(INVITE_ONLY)
    limpo = name.strip()[:40]
    if not limpo:
        return HTMLResponse(
            pages.register_form(idioma, "?", needs_invite=pede),
            status_code=400)
    # O convite e conferido com `compare_digest`: a comparacao ingenua vaza o
    # prefixo certo pelo tempo, e um codigo curto cai rapido assim.
    if pede and not secrets.compare_digest(invite.strip(), INVITE_ONLY):
        return HTMLResponse(
            pages.register_form(idioma, i18n.t("invite_wrong", idioma),
                                needs_invite=True),
            status_code=403)

    token = rules.new_token()
    with db.pool().connection() as conn:
        pode, impressao = _address_has_room(conn, request)
        if not pode:
            return HTMLResponse(
                pages.register_form(idioma, i18n.t("one_per_ip", idioma),
                                    needs_invite=pede),
                status_code=429)
        player = db.create_player(conn, rules.hash_token(token), limpo,
                                  impressao)
    resposta = HTMLResponse(pages.registered_page(
        player["display_name"], rules.recovery_code(token), idioma))
    _set_session(resposta, token)
    return resposta


@app.get("/new-galaxy", response_class=HTMLResponse)
def new_room_page(request: Request, lang: str = ""):
    idioma = i18n.pick(request.headers.get("accept-language", ""), lang)
    player = _web_player(request)
    return pages.new_room_form(idioma, player["display_name"] if player else None)


@app.post("/new-galaxy")
def new_room_submit(request: Request, name: str = Form(""),
                    seed: str = Form(""), lang: str = ""):
    idioma = i18n.pick(request.headers.get("accept-language", ""), lang)
    player = _web_player(request)
    if player is None:
        return HTMLResponse(pages.new_room_form(idioma, None), status_code=403)

    with db.pool().connection() as conn:
        ok, motivo = rules.can_create_room(db.rooms_owned(conn, player["id"]),
                                           player["blocked"])
    if not ok:
        return HTMLResponse(
            pages.new_room_form(idioma, player["display_name"], motivo),
            status_code=403)
    if not seed.strip():
        return HTMLResponse(
            pages.new_room_form(idioma, player["display_name"],
                                "the seed is required"),
            status_code=400)

    room = {
        "id": rules.new_room_id(),
        "name": name.strip()[:80] or f"{player['display_name']}'s room",
        "seed": seed.strip()[:40],
        "options": json.dumps({}),
        "password_hash": None,
        "owner_id": player["id"],
        # Os mesmos numeros da rota de API. Estavam divergentes: uma sala
        # criada pelo site nascia com teto de 32 pessoas, metade do que um
        # convite de Discord precisa, e ninguem descobriria isso antes de a
        # 33a chegar.
        "lease_hours": 12, "retention_n": 3, "max_players": 64,
        "max_join_age_days": 5,
    }
    with db.pool().connection() as conn:
        created = db.create_room(conn, room)
    return RedirectResponse(f"/galaxy/{created['id']}?lang={idioma}&new=1",
                            status_code=303)


@app.get("/how-it-works", response_class=HTMLResponse)
def how_web(request: Request, lang: str = ""):
    """O conceito inteiro: save como unidade de troca, o emprestimo, o que
    viaja entre jogadores, a vitrine e o mod."""
    idioma = i18n.pick(request.headers.get("accept-language", ""), lang)
    return pages.how_page(idioma)


@app.get("/client", response_class=HTMLResponse)
def client_web(request: Request, lang: str = ""):
    """Como instalar e chamar o cliente, em cada sistema."""
    idioma = i18n.pick(request.headers.get("accept-language", ""), lang)
    return pages.client_page(idioma)


@app.get("/recovery", response_class=HTMLResponse)
def recovery_web(request: Request, lang: str = ""):
    """O que e o codigo de recuperacao e como usa-lo."""
    idioma = i18n.pick(request.headers.get("accept-language", ""), lang)
    return pages.recovery_page(idioma)


@app.get("/account/delete", response_class=HTMLResponse)
def delete_web(request: Request, lang: str = ""):
    idioma = i18n.pick(request.headers.get("accept-language", ""), lang)
    return pages.delete_form(idioma)


@app.post("/account/delete", response_class=HTMLResponse)
def delete_submit(request: Request, code: str = Form(""),
                  confirm: str = Form(""), lang: str = ""):
    """Apagar a conta pelo navegador.

    A politica prometia isto e entregava uma linha de `curl` com cabecalho de
    autorizacao — util para quem ja sabe o que e um cabecalho de autorizacao, e
    para mais ninguem. Uma promessa de apagar dados que exige competencia
    tecnica para ser exercida nao e bem uma promessa.

    A confirmacao e digitada por extenso, igual a da API, porque nao ha
    desfazer e um clique unico e pouco para uma porta so de ida.
    """
    idioma = i18n.pick(request.headers.get("accept-language", ""), lang)
    if confirm.strip() != "delete everything":
        return HTMLResponse(
            pages.delete_form(idioma, i18n.t("delete_bad_confirm", idioma)),
            status_code=400)

    token = rules.parse_recovery_code(code)
    with db.pool().connection() as conn:
        dono = db.player_by_token(conn, rules.hash_token(token))
    if dono is None:
        return HTMLResponse(
            pages.delete_form(idioma, i18n.t("delete_bad_code", idioma)),
            status_code=404)

    resultado = delete_me(confirm="delete everything", player=dono)
    resposta = HTMLResponse(pages.deleted_page(resultado, idioma))
    # A sessao do navegador morre junto: deixar o cookie de uma conta que nao
    # existe mais so produz erro na proxima pagina.
    resposta.delete_cookie(COOKIE)
    return resposta


@app.get("/privacy", response_class=HTMLResponse)
def privacy(request: Request, lang: str = ""):
    """A política de dados, na língua de quem lê.

    A seção 2.11 manda escrever isto antes de existir e onde a pessoa lê antes
    de entrar. O editor de savegame promete que nada sai do computador; este
    servidor quebra essa promessa, e fingir que não seria o pior erro possível.
    """
    idioma = i18n.pick(request.headers.get("accept-language", ""), lang)
    return pages.privacy_page(idioma)


@app.get("/privacidade", response_class=HTMLResponse)
def privacy_pt():
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/privacy?lang=pt", status_code=308)

