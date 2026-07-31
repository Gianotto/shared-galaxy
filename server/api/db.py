"""
Acesso ao banco. SQL na mao, sem ORM.

O esquema tem seis tabelas e as consultas sao pequenas. Um ORM aqui esconderia
justamente o que precisa ficar visivel — qual transacao segura o que, e onde o
indice unico do emprestimo entra em acao.

Toda funcao recebe uma conexao em vez de abrir uma: quem chama decide o escopo
da transacao. Isso importa porque `checkout` e `checkin` precisam ser atomicos e
nao podem virar duas transacoes acidentalmente.
"""

from __future__ import annotations

import datetime as dt
import os

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

_pool: ConnectionPool | None = None


def dsn() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL não está definida")
    return url


def pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(dsn(), min_size=1, max_size=10,
                               kwargs={"row_factory": dict_row}, open=True)
    return _pool


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


# ---------------------------------------------------------------------------
# Jogador
# ---------------------------------------------------------------------------

def create_player(conn: psycopg.Connection, token_hash: str, name: str) -> dict:
    return conn.execute(
        """INSERT INTO player (token_hash, display_name)
           VALUES (%s, %s) RETURNING id, display_name, created_at""",
        (token_hash, name)).fetchone()


def player_by_token(conn: psycopg.Connection, token_hash: str) -> dict | None:
    return conn.execute(
        """SELECT id, display_name, rooms_created, blocked
             FROM player WHERE token_hash = %s""", (token_hash,)).fetchone()


def touch_player(conn: psycopg.Connection, player_id: int) -> None:
    conn.execute("UPDATE player SET last_seen_at = now() WHERE id = %s",
                 (player_id,))


# ---------------------------------------------------------------------------
# Sala
# ---------------------------------------------------------------------------

def create_room(conn: psycopg.Connection, room: dict) -> dict:
    row = conn.execute(
        """INSERT INTO room (id, name, seed, options, password_hash, owner_id,
                             lease_hours, retention_n, max_players)
           VALUES (%(id)s, %(name)s, %(seed)s, %(options)s, %(password_hash)s,
                   %(owner_id)s, %(lease_hours)s, %(retention_n)s,
                   %(max_players)s)
           RETURNING *""", room).fetchone()
    conn.execute(
        "UPDATE player SET rooms_created = rooms_created + 1 WHERE id = %s",
        (room["owner_id"],))
    return row


def get_room(conn: psycopg.Connection, room_id: str) -> dict | None:
    return conn.execute("SELECT * FROM room WHERE id = %s",
                        (room_id,)).fetchone()


def list_rooms(conn: psycopg.Connection, limit: int = 50) -> list:
    """A listagem publica. Nao expoe seed nem digest — quem entra recebe.

    A seed fica de fora de proposito: ela e o convite para reproduzir a galaxia,
    e uma sala com senha nao deveria entrega-la a quem so leu a lista.
    """
    return conn.execute(
        """SELECT r.id, r.name, r.created_at, r.max_players,
                  (r.password_hash IS NOT NULL) AS has_password,
                  count(m.player_id)            AS players
             FROM room r
             LEFT JOIN membership m ON m.room_id = r.id
            WHERE r.listed
            GROUP BY r.id
            ORDER BY r.created_at DESC
            LIMIT %s""", (limit,)).fetchall()


def adopt_galaxy(conn: psycopg.Connection, room_id: str, digest: str,
                 save_version: str | None) -> None:
    """A primeira entrada define a galaxia da sala."""
    conn.execute(
        """UPDATE room SET galaxy_digest = %s, save_version = %s
            WHERE id = %s AND galaxy_digest IS NULL""",
        (digest, save_version, room_id))


# ---------------------------------------------------------------------------
# Participacao
# ---------------------------------------------------------------------------

def get_membership(conn: psycopg.Connection, room_id: str,
                   player_id: int) -> dict | None:
    return conn.execute(
        "SELECT * FROM membership WHERE room_id = %s AND player_id = %s",
        (room_id, player_id)).fetchone()


def upsert_membership(conn: psycopg.Connection, room_id: str, player_id: int,
                      ship_name: str | None, canonical_id: int | None) -> dict:
    return conn.execute(
        """INSERT INTO membership (room_id, player_id, ship_name, canonical_id)
           VALUES (%s, %s, %s, %s)
           ON CONFLICT (room_id, player_id) DO UPDATE
               SET ship_name    = COALESCE(EXCLUDED.ship_name, membership.ship_name),
                   canonical_id = COALESCE(EXCLUDED.canonical_id, membership.canonical_id),
                   last_seen_at = now()
           RETURNING *""",
        (room_id, player_id, ship_name, canonical_id)).fetchone()


def set_position(conn: psycopg.Connection, room_id: str, player_id: int,
                 system: str | None, celeid: str | None) -> None:
    """Onde a frota esta, na lingua da sala.

    `celeid` e nao o `id` local: so ele significa a mesma coisa no save de todo
    mundo (docs/findings.md, item 1).
    """
    conn.execute(
        """UPDATE membership SET at_system = %s, at_celeid = %s,
                                 last_seen_at = now()
            WHERE room_id = %s AND player_id = %s""",
        (system, celeid, room_id, player_id))


def room_roster(conn: psycopg.Connection, room_id: str) -> list:
    return conn.execute(
        """SELECT m.player_id, p.display_name, m.ship_name, m.at_system,
                  m.at_celeid, m.joined_at, m.last_seen_at,
                  v.game_day, v.created_at AS canonical_at,
                  (l.id IS NOT NULL) AS playing
             FROM membership m
             JOIN player p        ON p.id = m.player_id
             LEFT JOIN save_version v ON v.id = m.canonical_id
             LEFT JOIN lease l    ON l.room_id = m.room_id
                                 AND l.player_id = m.player_id
                                 AND l.state = 'open'
            WHERE m.room_id = %s
            ORDER BY m.joined_at""", (room_id,)).fetchall()


def count_players(conn: psycopg.Connection, room_id: str) -> int:
    return conn.execute(
        "SELECT count(*) AS n FROM membership WHERE room_id = %s",
        (room_id,)).fetchone()["n"]


# ---------------------------------------------------------------------------
# Versao de save
# ---------------------------------------------------------------------------

def add_version(conn: psycopg.Connection, version: dict) -> dict:
    return conn.execute(
        """INSERT INTO save_version (room_id, player_id, sha256, bytes, kind,
                                     game_day, galaxy_digest)
           VALUES (%(room_id)s, %(player_id)s, %(sha256)s, %(bytes)s,
                   %(kind)s, %(game_day)s, %(galaxy_digest)s)
           RETURNING *""", version).fetchone()


def get_version(conn: psycopg.Connection, version_id: int) -> dict | None:
    return conn.execute("SELECT * FROM save_version WHERE id = %s",
                        (version_id,)).fetchone()


def player_versions(conn: psycopg.Connection, room_id: str,
                    player_id: int) -> list:
    """Do mais novo para o mais velho, que e a ordem que a poda espera."""
    return conn.execute(
        """SELECT id, sha256, bytes, kind, game_day, created_at
             FROM save_version
            WHERE room_id = %s AND player_id = %s
            ORDER BY created_at DESC, id DESC""",
        (room_id, player_id)).fetchall()


def delete_versions(conn: psycopg.Connection, ids: list) -> int:
    if not ids:
        return 0
    return conn.execute("DELETE FROM save_version WHERE id = ANY(%s)",
                        (list(ids),)).rowcount


def all_live_hashes(conn: psycopg.Connection) -> set:
    """Todo sha256 que ainda tem versao apontando. Alimenta a poda de blobs."""
    return {r["sha256"] for r in
            conn.execute("SELECT DISTINCT sha256 FROM save_version").fetchall()}


# ---------------------------------------------------------------------------
# Emprestimo
# ---------------------------------------------------------------------------

def open_lease(conn: psycopg.Connection, room_id: str,
               player_id: int) -> dict | None:
    return conn.execute(
        """SELECT * FROM lease
            WHERE room_id = %s AND player_id = %s AND state = 'open'""",
        (room_id, player_id)).fetchone()


def create_lease(conn: psycopg.Connection, room_id: str, player_id: int,
                 delivered_id: int, expires_at: dt.datetime) -> dict:
    """Abre um emprestimo.

    O indice unico parcial do esquema garante um aberto por jogador e sala. Se
    duas requisicoes chegarem juntas, uma leva `UniqueViolation` — e isso e o
    desenho, nao um acidente: e onde a duplicacao por sessao paralela morre.
    """
    return conn.execute(
        """INSERT INTO lease (room_id, player_id, delivered_id, expires_at)
           VALUES (%s, %s, %s, %s) RETURNING *""",
        (room_id, player_id, delivered_id, expires_at)).fetchone()


def close_lease(conn: psycopg.Connection, lease_id: int,
                returned_id: int) -> None:
    conn.execute(
        """UPDATE lease SET state = 'returned', returned_id = %s,
                            closed_at = now()
            WHERE id = %s""", (returned_id, lease_id))


def expire_leases(conn: psycopg.Connection) -> int:
    """Vence o que passou do prazo.

    Quem nao devolveu volta ao estado de quando pegou — e isso ja e verdade sem
    fazer nada, porque a canonica nunca foi trocada. Vencer e so fechar o
    registro para o jogador poder retirar de novo.
    """
    return conn.execute(
        """UPDATE lease SET state = 'expired', closed_at = now()
            WHERE state = 'open' AND expires_at <= now()""").rowcount


# ---------------------------------------------------------------------------
# O esqueleto da galaxia, para o mapa
# ---------------------------------------------------------------------------

def save_galaxy_map(conn: psycopg.Connection, room_id: str, mapa: dict) -> int:
    """Grava o esqueleto uma vez, quando a sala adota a galaxia.

    E constante da sala, nao estado de jogador: a seed reproduz o mundo gerado,
    entao os sistemas e as posicoes nao mudam mais.
    """
    if not mapa.get("systems"):
        return 0
    conn.execute("UPDATE room SET galaxy_w = %s, galaxy_h = %s WHERE id = %s",
                 (mapa["w"], mapa["h"], room_id))
    with conn.cursor() as cur:
        cur.executemany(
            # A posicao nunca muda, mas o NOME chega depois: o jogo so batiza
            # um sistema quando o jogador chega perto, e num save recem-criado
            # todos vem vazios — e por isso a impressao digital os ignora. Entao
            # o nome e preenchido quando aparece, e nunca sobrescrito por vazio.
            """INSERT INTO galaxy_system (room_id, system_id, name, x, y, bodies)
               VALUES (%s, %s, %s, %s, %s, %s)
               ON CONFLICT (room_id, system_id) DO UPDATE
                   SET name = COALESCE(galaxy_system.name, EXCLUDED.name)""",
            [(room_id, s["systemId"], s["name"], s["x"], s["y"], s["bodies"])
             for s in mapa["systems"]])
    return len(mapa["systems"])


def galaxy_map(conn: psycopg.Connection, room_id: str) -> dict:
    room = conn.execute(
        "SELECT galaxy_w, galaxy_h FROM room WHERE id = %s",
        (room_id,)).fetchone()
    sistemas = conn.execute(
        """SELECT system_id AS "systemId", name, x, y, bodies
             FROM galaxy_system WHERE room_id = %s ORDER BY system_id""",
        (room_id,)).fetchall()
    return {"w": (room or {}).get("galaxy_w") or 0,
            "h": (room or {}).get("galaxy_h") or 0,
            "systems": [dict(s) for s in sistemas]}
