"""
As regras da custodia, sem banco e sem rede.

Tudo aqui e funcao pura: recebe estado, devolve decisao. O motivo e teste — as
regras que decidem o que acontece com o save de um jogador sao as que mais
merecem ser exercitadas, e sao justamente as que ficariam presas dentro de um
handler HTTP com Postgres atras se ninguem separasse.

O que mora aqui:

- identidade: gerar token, guardar so o hash, montar codigo de recuperacao
- emprestimo: quando vence, o que fazer quando venceu
- retencao: quais versoes podem ser apagadas e quais nunca
- entrada: se um save serve para a sala

O que NAO mora aqui: nada que fale SQL ou HTTP.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
import secrets

# --------------------------------------------------------------------------
# Identidade
# --------------------------------------------------------------------------

# 32 bytes em base32 sem padding: 52 caracteres, alfabeto sem ambiguidade
# visual, e o suficiente para o token ser inadivinhavel. E a unica credencial
# que existe no sistema — nao ha e-mail para recuperar, nao ha senha para
# trocar. Por isso e longo e por isso o cliente e obrigado a guardar.
TOKEN_BYTES = 32

# O codigo de recuperacao e o proprio token, so que formatado em grupos para a
# pessoa conseguir copiar de um papel sem errar.
GROUP = 4


def new_token() -> str:
    """Um token novo, em claro. Existe uma vez so, na resposta do cadastro."""
    import base64
    raw = base64.b32encode(secrets.token_bytes(TOKEN_BYTES)).decode("ascii")
    return raw.rstrip("=")


def hash_token(token: str) -> str:
    """O que o banco guarda.

    sha256 puro, sem sal e sem KDF, de proposito: o token tem 256 bits de
    entropia gerados por nos, entao nao ha dicionario que ataque e esticar custo
    so atrasaria toda requisicao. A regra seria outra se fosse senha escolhida
    por gente.
    """
    return hashlib.sha256(token.strip().encode("utf-8")).hexdigest()


def recovery_code(token: str) -> str:
    """O token em grupos, para ser copiado a mao sem erro."""
    clean = token.strip()
    return "-".join(clean[i:i + GROUP] for i in range(0, len(clean), GROUP))


def parse_recovery_code(code: str) -> str:
    """Aceita o codigo de volta com ou sem os tracos, e em qualquer caixa."""
    return re.sub(r"[\s-]", "", code).upper()


# --------------------------------------------------------------------------
# Sala
# --------------------------------------------------------------------------

# Sem vogais: um id gerado ao acaso nunca vira palavra infeliz, e ninguem
# precisa revisar lista de palavra proibida. Sem `0/O` e `1/I/L` porque o id vai
# ser ditado em voz alta e digitado errado.
ROOM_ALPHABET = "BCDFGHJKMNPQRSTVWXZ23456789"
ROOM_ID_LEN = 6

MAX_ROOMS_PER_PLAYER = 1


def new_room_id() -> str:
    return "".join(secrets.choice(ROOM_ALPHABET) for _ in range(ROOM_ID_LEN))


def can_create_room(rooms_owned: int, blocked: bool) -> tuple[bool, str]:
    """Cota de galaxia. Criar conta e gratis; criar galaxia nao e ilimitado.

    CONTA GALAXIAS VIVAS, e nao quantas a pessoa ja criou algum dia. Com um
    contador que so sobe, apagar a propria galaxia trancava a conta para
    sempre: o limite e um teto de quantas existem ao mesmo tempo, e nao uma
    cota vitalicia.
    """
    if blocked:
        return False, "this account is blocked"
    if rooms_owned >= MAX_ROOMS_PER_PLAYER:
        return False, (f"limit of {MAX_ROOMS_PER_PLAYER} galaxy per account. "
                       f"Delete yours before creating another")
    return True, ""


# --------------------------------------------------------------------------
# Entrada numa sala
# --------------------------------------------------------------------------

def check_join(save: dict, room: dict, age_days: float | None = None
               ) -> tuple[bool, str]:
    """O save que chegou serve para esta sala?

    `save` vem de `server.galaxy.fingerprint.describe`. A recusa sempre explica
    o motivo, porque quase sempre e opcao de criacao diferente e a pessoa
    consegue corrigir — recusar sem dizer o que houve manda ela embora.

    `age_days` e a idade da colonia que chegou. Desde que o servidor enxerta a
    galaxia, uma colonia velha entra tao facil quanto uma nova — e chega com a
    nave, a tripulacao e o banco dela. Quem jogou meio ano nao comeca ao lado de
    quem acabou de abrir o jogo, entao a sala pode exigir partida nova.
    """
    if room.get("save_version") and save.get("saveVersion"):
        if str(room["save_version"]) != str(save["saveVersion"]):
            return False, (
                f"this save is format version {save['saveVersion']} and the "
                f"room is on {room['save_version']}. The game was probably "
                f"updated; the room needs to be recreated")

    # A primeira entrada define a galáxia da sala: não há com o que comparar.
    if not room.get("galaxy_digest"):
        return True, ""

    if save.get("digest") != room["galaxy_digest"]:
        return False, (
            "this save's galaxy is not the room's. Almost always a different "
            "creation option: check the seed and every scenario option the "
            "room publishes, and create the game again")
    return True, ""


def check_join_age(age_days: float | None, room: dict) -> tuple[bool, str]:
    """A colonia que chegou e nova o bastante para esta sala?

    Fica separado de `check_join` de proposito: aquele decide se o save CABE na
    sala e pode ser consertado por enxerto; este decide se a pessoa pode entrar
    com ele, e enxerto nenhum conserta idade. Juntar os dois faria o servidor
    tentar enxertar uma colonia de 178 dias antes de recusa-la.
    """
    limite = room.get("max_join_age_days")
    if limite is None or age_days is None:
        return True, ""
    if float(age_days) <= float(limite):
        return True, ""
    return False, (
        f"this colony is {float(age_days):.1f} days old and the room accepts "
        f"up to {float(limite):.1f} at join. Everyone here starts together, so "
        f"create a new game in Space Haven and join with that one — any seed "
        f"and any scenario option will do, the server puts you in the room's "
        f"galaxy")


# --------------------------------------------------------------------------
# Emprestimo
# --------------------------------------------------------------------------

def lease_expiry(issued_at: dt.datetime, lease_hours: int) -> dt.datetime:
    return issued_at + dt.timedelta(hours=lease_hours)


def lease_is_expired(lease: dict, now: dt.datetime) -> bool:
    return lease["state"] == "open" and lease["expires_at"] <= now


def can_checkout(open_lease: dict | None, now: dt.datetime) -> tuple[bool, str]:
    """Pode retirar o save?

    Um emprestimo aberto por vez, e e isso que impede duplicacao por sessao
    paralela. Um emprestimo vencido nao bloqueia: quem passou do prazo perde a
    sessao, mas nao perde o direito de jogar de novo.
    """
    if open_lease is None:
        return True, ""
    if lease_is_expired(open_lease, now):
        return True, ""
    remaining = open_lease["expires_at"] - now
    hours = remaining.total_seconds() / 3600
    return False, (
        f"you already have this save checked out. Return it before checking "
        f"out again, or wait {hours:.1f}h for the lease to expire")


def can_checkin(lease: dict | None, now: dt.datetime) -> tuple[bool, str]:
    """Pode devolver?

    Devolver fora do prazo e recusado com explicacao, e o estado ja voltou ao de
    quando foi retirado. E duro, e e o preco de nao existir "so devolvo a sessao
    que foi boa" — mas a mensagem diz exatamente o que aconteceu.
    """
    if lease is None:
        return False, ("no open lease for this save. Check it out before "
                       "returning it")
    if lease["state"] == "returned":
        return False, "this lease has already been returned"
    if lease_is_expired(lease, now):
        late = (now - lease["expires_at"]).total_seconds() / 3600
        return False, (
            f"the lease expired {late:.1f}h ago and the save reverted to the "
            f"state it was checked out in. This session cannot be returned")
    return True, ""


# --------------------------------------------------------------------------
# Retencao
# --------------------------------------------------------------------------

def versions_to_prune(versions: list, retention_n: int,
                      protected_ids: set) -> list:
    """Quais versoes podem sair, mais antigas primeiro.

    `versions` vem ordenado do mais novo para o mais velho. Nunca sai a canonica
    atual nem a que esta emprestada — apagar qualquer uma das duas deixaria um
    jogador sem save, que e o unico erro verdadeiramente imperdoavel aqui.

    A janela e a decisao registrada no plano: histórico de N versoes por
    jogador. Limita o alcance da conferencia da secao 2.7, e isso foi aceito em
    troca de armazenamento previsivel numa sala aberta.
    """
    keep = 0
    out = []
    for version in versions:
        if version["id"] in protected_ids:
            continue
        if keep < retention_n:
            keep += 1
            continue
        out.append(version)
    return out


def live_hashes(versions: list) -> set:
    """Os blobs que ainda tem dono. O resto o volume pode apagar."""
    return {v["sha256"] for v in versions}
