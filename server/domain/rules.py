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

MAX_ROOMS_PER_PLAYER = 5


def new_room_id() -> str:
    return "".join(secrets.choice(ROOM_ALPHABET) for _ in range(ROOM_ID_LEN))


def can_create_room(rooms_created: int, blocked: bool) -> tuple[bool, str]:
    """Cota de sala aberta. Criar token e gratis; criar sala nao e ilimitado."""
    if blocked:
        return False, "esta conta está bloqueada"
    if rooms_created >= MAX_ROOMS_PER_PLAYER:
        return False, (f"limite de {MAX_ROOMS_PER_PLAYER} salas por conta. "
                       f"Apague uma sala antes de criar outra")
    return True, ""


# --------------------------------------------------------------------------
# Entrada numa sala
# --------------------------------------------------------------------------

def check_join(save: dict, room: dict) -> tuple[bool, str]:
    """O save que chegou serve para esta sala?

    `save` vem de `server.galaxy.fingerprint.describe`. A recusa sempre explica
    o motivo, porque quase sempre e opcao de criacao diferente e a pessoa
    consegue corrigir — recusar sem dizer o que houve manda ela embora.
    """
    if room.get("save_version") and save.get("saveVersion"):
        if str(room["save_version"]) != str(save["saveVersion"]):
            return False, (
                f"este save é da versão de formato {save['saveVersion']} e a "
                f"sala está na {room['save_version']}. Provavelmente o jogo foi "
                f"atualizado; a sala precisa ser recriada")

    # A primeira entrada define a galáxia da sala: não há com o que comparar.
    if not room.get("galaxy_digest"):
        return True, ""

    if save.get("digest") != room["galaxy_digest"]:
        return False, (
            "a galáxia deste save não é a da sala. Quase sempre é opção de "
            "criação diferente: confira a seed e cada uma das opções de cenário "
            "publicadas pela sala, e crie a partida de novo")
    return True, ""


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
    faltam = open_lease["expires_at"] - now
    horas = faltam.total_seconds() / 3600
    return False, (
        f"você já está com este save retirado. Devolva antes de retirar de "
        f"novo, ou espere o prazo vencer em {horas:.1f}h")


def can_checkin(lease: dict | None, now: dt.datetime) -> tuple[bool, str]:
    """Pode devolver?

    Devolver fora do prazo e recusado com explicacao, e o estado ja voltou ao de
    quando foi retirado. E duro, e e o preco de nao existir "so devolvo a sessao
    que foi boa" — mas a mensagem diz exatamente o que aconteceu.
    """
    if lease is None:
        return False, ("não há empréstimo aberto para este save. Retire antes "
                       "de devolver")
    if lease["state"] == "returned":
        return False, "este empréstimo já foi devolvido"
    if lease_is_expired(lease, now):
        atraso = (now - lease["expires_at"]).total_seconds() / 3600
        return False, (
            f"o prazo venceu há {atraso:.1f}h e o save voltou ao estado de "
            f"quando foi retirado. Esta sessão não pode ser devolvida")
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
