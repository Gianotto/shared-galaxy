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
import logging
import os

import psycopg
from fastapi import Depends, FastAPI, Form, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from server.api import db
from server.domain import rules
from server.galaxy import fingerprint, presence
from sgalaxy import discovery as discovering
from sgalaxy import graft as grafting
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
def create_player(payload: dict | None = None):
    """Emite um token novo. E o unico cadastro que existe.

    Sem e-mail, sem senha, sem confirmacao. O token volta uma vez so — o cliente
    e responsavel por guardar, e por deixar claro que perder e perder.
    """
    payload = payload or {}
    if INVITE_ONLY and payload.get("invite", "").strip() != INVITE_ONLY:
        raise HTTPException(403, "este servidor exige convite para criar conta")

    name = str(payload.get("name") or "").strip() or "Anonymous"
    if len(name) > 40:
        raise HTTPException(400, "the name is at most 40 characters")

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
        raise HTTPException(400, "give the galaxy seed. It is not stored in the save, "
                                 "so the server is the one that has to keep it")
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
    return {"roomId": room_id, "players": [
        {"playerId": r["player_id"], "name": r["display_name"],
         "shipName": r["ship_name"], "system": r["at_system"],
         "x": r["at_x"], "y": r["at_y"], "body": r["at_body"], "ageDays": float(r["age_days"]) if r["age_days"] else None,
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
            "message": ("the room's galaxy was grafted into your save, and the "
                        "result is now canonical — check out to get it back. "
                        "Your ship, crew, bank and research are untouched."
                        if grafted else
                        "save adopted as canonical. The server owns it from "
                        "now on.")}


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

    Devolve `(zip, sids, relatorio)`. Os `sids` sao o que o `checkin` vai tirar
    de volta — sem isso a vitrine vira parte permanente da partida da pessoa.

    Falhar aqui nunca custa a sessao: sem vitrine a sala continua jogavel, e
    entregar um save quebrado seria muito pior que entregar um save sozinho.
    """
    vizinhos = _neighbours_of(conn, room_id, player_id)
    relatorio = {"placed": 0, "skipped": [], "neighbours": []}
    if not vizinhos:
        return data, [], relatorio

    sids = []
    try:
        with blobs.with_unpacked(data) as folder:
            sf = SaveFile(folder)
            for outro in vizinhos:
                nome = f"{outro['ship_name'] or 'ship'} ({outro['display_name']})"
                try:
                    # Nave NPC VIVA, nao casco de destroco: sucata aparece
                    # como "Derelict" e, pior, se reclama e se desmonta. A
                    # diferenca entre viva e sucata e a tripulacao, e ela vem
                    # junto no molde.
                    cascos = storefront.live_npc_ships(sf)
                    if not cascos:
                        relatorio["skipped"].append(
                            f"{outro['display_name']}: no live NPC ship to "
                            f"build the storefront on")
                        continue
                    # Sem <asi> a nave entra sem IA de bordo, sem radio e sem
                    # postura de combate. Vitrine quebrada e pior que ausente.
                    rel = storefront.inject_ship(
                        sf, cascos[0], faction=NEIGHBOUR_FACTION,
                        credits=NEIGHBOUR_CREDITS, name=nome, hull_mode=True,
                        crew_side=NEIGHBOUR_FACTION,
                        at=(outro["at_x"], outro["at_y"]),
                        system_id=outro["at_system"])
                    sids.append(rel["fleet"]["createdShipId"])
                    relatorio["placed"] += 1
                    relatorio["neighbours"].append(nome)
                except Exception as exc:      # noqa: BLE001
                    relatorio["skipped"].append(
                        f"{outro['display_name']}: {exc}")
            if not sids:
                return data, [], relatorio
            sf.save(backup=False)
            return blobs.pack_save(folder), sids, relatorio
    except Exception as exc:      # noqa: BLE001
        log.warning("could not place neighbours: %s", exc)
        return data, [], {"placed": 0, "skipped": [str(exc)], "neighbours": []}


def _strip_neighbours(lease: dict, data: bytes) -> bytes:
    """Tira as vitrines antes de guardar o que voltou.

    E o par obrigatorio de `_place_neighbours`. Sem ele a nave de um vizinho
    ficaria guardada como parte da partida de quem devolveu, e voltaria
    empilhada a cada sessao.
    """
    sids = (lease or {}).get("injected_sids") or []
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
        data, sids, vizinhanca = _place_neighbours(conn, room_id, player["id"],
                                                   data)
        if sids:
            db.set_injected_sids(conn, lease["id"], sids)

    return Response(
        content=data, media_type="application/zip",
        headers={
            "X-Discovery-Flagged": str(partilha["flagged"]),
            "X-Discovery-Inserted": str(partilha["inserted"]),
            "X-Neighbours": str(vizinhanca["placed"]),
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

        data = _strip_neighbours(lease, data)

        try:
            with blobs.with_unpacked(data) as folder:
                described = fingerprint.describe(folder)
                here = presence.read(folder)
                day = here["ageDays"]
        except StorageError as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(400, f"could not read this save: {exc}") from exc

        if described["digest"] != room["galaxy_digest"]:
            raise HTTPException(409, "this save's galaxy is not the room's")

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

        # As vitrines saem ANTES de qualquer leitura: o que for guardado, o
        # que entrar no mapa e o que a proxima retirada entregar tem de ser a
        # partida da pessoa, sem as naves que o servidor emprestou.
        data = _strip_neighbours(lease, data)

        try:
            with blobs.with_unpacked(data) as folder:
                described = fingerprint.describe(folder)
                here = presence.read(folder)
                day = here["ageDays"]
        except StorageError as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(400, f"could not read this save: {exc}") from exc

        # A galaxia nao pode ter mudado no meio de uma sessao. Se mudou, o save
        # nao e o que foi emprestado — outra partida, outro universo.
        if described["digest"] != room["galaxy_digest"]:
            raise HTTPException(409,
                                "this save's galaxy is not the room's. This is not "
                                "the save that was lent out")

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
        raise HTTPException(503, f"database unavailable: {exc}") from exc


@app.get("/", response_class=HTMLResponse)
def index(request: Request, lang: str = ""):
    """As salas abertas. É a vitrine: ver antes de decidir se quer entrar."""
    idioma = i18n.pick(request.headers.get("accept-language", ""), lang)
    with db.pool().connection() as conn:
        rooms = db.list_rooms(conn)
    return pages.room_list([dict(r) for r in rooms], idioma)


@app.get("/room/{room_id}", response_class=HTMLResponse)
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


# O caminho antigo, para links já compartilhados não morrerem.
@app.get("/sala/{room_id}", response_class=HTMLResponse)
def room_web_pt(room_id: str, request: Request):
    from fastapi.responses import RedirectResponse
    return RedirectResponse(f"/room/{room_id}?lang=pt", status_code=308)


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
    return pages.register_form(idioma)


@app.post("/register", response_class=HTMLResponse)
def register_submit(request: Request, name: str = Form(""), lang: str = ""):
    idioma = i18n.pick(request.headers.get("accept-language", ""), lang)
    limpo = name.strip()[:40]
    if not limpo:
        return HTMLResponse(pages.register_form(idioma, "?"), status_code=400)
    if INVITE_ONLY:
        return HTMLResponse(
            pages.register_form(idioma,
                                "this server requires an invite"),
            status_code=403)

    token = rules.new_token()
    with db.pool().connection() as conn:
        player = db.create_player(conn, rules.hash_token(token), limpo)
    resposta = HTMLResponse(pages.registered_page(
        player["display_name"], rules.recovery_code(token), idioma))
    _set_session(resposta, token)
    return resposta


@app.get("/new-room", response_class=HTMLResponse)
def new_room_page(request: Request, lang: str = ""):
    idioma = i18n.pick(request.headers.get("accept-language", ""), lang)
    player = _web_player(request)
    return pages.new_room_form(idioma, player["display_name"] if player else None)


@app.post("/new-room")
def new_room_submit(request: Request, name: str = Form(""),
                    seed: str = Form(""), lang: str = ""):
    idioma = i18n.pick(request.headers.get("accept-language", ""), lang)
    player = _web_player(request)
    if player is None:
        return HTMLResponse(pages.new_room_form(idioma, None), status_code=403)

    ok, motivo = rules.can_create_room(player["rooms_created"],
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
        "lease_hours": 12, "retention_n": 20, "max_players": 32,
        "max_join_age_days": 5,
    }
    with db.pool().connection() as conn:
        created = db.create_room(conn, room)
    return RedirectResponse(f"/room/{created['id']}?lang={idioma}&new=1",
                            status_code=303)


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

