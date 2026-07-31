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
from server.storage.blobs import BlobStore, StorageError

app = FastAPI(
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
    return _room_public(created, is_member=True)


def _room_public(room: dict, is_member: bool) -> dict:
    """A sala como o cliente ve.

    A seed e as opcoes so saem para quem e da sala: sao o que a pessoa digita
    para criar a partida, e a listagem publica nao deve entregar isso de uma
    sala com senha.
    """
    out = {
        "id": room["id"], "name": room["name"],
        "leaseHours": room["lease_hours"], "retentionN": room["retention_n"],
        "maxPlayers": room["max_players"],
        "hasPassword": room["password_hash"] is not None,
        "galaxyDigest": room["galaxy_digest"],
        "saveVersion": room["save_version"],
    }
    if is_member:
        out["seed"] = room["seed"]
        out["options"] = room["options"]
    return out


def _require_room(conn, room_id: str) -> dict:
    room = db.get_room(conn, room_id)
    if room is None:
        raise HTTPException(404, f"não existe sala {room_id}")
    return room


@app.get("/api/v1/rooms/{room_id}")
def room_detail(room_id: str, player: dict = Depends(current_player)):
    with db.pool().connection() as conn:
        room = _require_room(conn, room_id)
        member = db.get_membership(conn, room_id, player["id"]) is not None
        return _room_public(room, member)


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
    """Vitrine mínima. O mapa da sala entra aqui na próxima etapa."""
    return """<!doctype html><meta charset="utf-8">
<title>Galáxia Compartilhada</title>
<h1>Galáxia Compartilhada</h1>
<p>Servidor de custódia de savegames de Space Haven.</p>
<p>Projeto independente, feito por fã. <b>Space Haven</b> é um jogo da
Bugbyte Ltd.; este projeto não é oficial, não tem endosso e não tem vínculo
com ela. Nada aqui altera o jogo.</p>
<p><a href="/api/v1/rooms">salas abertas</a> ·
   <a href="/docs">a API</a></p>"""
