"""
Page strings, in English and Portuguese.

The pages are the front door — step 2 of section 2.11, where someone sees a
living room and decides whether to join — so serving a single language shuts the
door on half of whoever arrives.

No translation library: a few dozen phrases fit in a dict. gettext would add a
dependency, binary catalogue files and a build step for the same result.

The language comes from `?lang=` when present, otherwise from the browser's
`Accept-Language`. English is the default: the project is Brazilian, the game's
community is not.
"""

from __future__ import annotations

LANGS = ("en", "pt")
DEFAULT = "en"

STRINGS: dict = {
    # -- shared
    "site": {"pt": "Galáxia Compartilhada", "en": "Shared Galaxy"},
    "tagline": {
        "pt": "Várias pessoas jogando Space Haven na mesma galáxia, cada uma "
              "no seu próprio jogo.",
        "en": "Several people playing Space Haven in one galaxy, each running "
              "their own game.",
    },
    "rooms": {"pt": "salas", "en": "rooms"},
    "privacy_link": {"pt": "o que acontece com o seu save",
                     "en": "what happens to your save"},
    "code": {"pt": "o código", "en": "the code"},
    "disclaimer": {
        "pt": "<b>Space Haven</b> é um jogo da "
              "<a href=\"https://bugbyte.fi/\">Bugbyte Ltd.</a> Este é um "
              "projeto independente, feito por fã: não é oficial, não tem "
              "endosso e não tem vínculo com ela. Nada aqui altera o jogo.",
        "en": "<b>Space Haven</b> is a game by "
              "<a href=\"https://bugbyte.fi/\">Bugbyte Ltd.</a> This is an "
              "independent, fan-made project: not official, not endorsed, and "
              "with no affiliation. Nothing here modifies the game.",
    },

    # -- room list
    "no_rooms": {
        "pt": "Nenhuma sala aberta ainda. Quem criar a primeira define a "
              "galáxia que todos vão dividir.",
        "en": "No open rooms yet. Whoever creates the first one defines the "
              "galaxy everyone will share.",
    },
    "players": {"pt": "jogadores", "en": "players"},
    "has_password": {"pt": "com senha", "en": "password"},

    # -- room
    "room": {"pt": "sala", "en": "room"},
    "lease_of": {"pt": "empréstimo de", "en": "lease of"},
    "who_is_where": {"pt": "Quem está onde", "en": "Who is where"},
    "nobody_yet": {
        "pt": "Ninguém entrou ainda. O primeiro save a subir define a galáxia "
              "desta sala.",
        "en": "Nobody has joined yet. The first save uploaded defines this "
              "room's galaxy.",
    },
    "map_later": {
        "pt": "O mapa aparece quando o primeiro jogador entrar: é o save dele "
              "que define a galáxia da sala.",
        "en": "The map appears once the first player joins — their save is "
              "what defines the room's galaxy.",
    },
    "th_player": {"pt": "jogador", "en": "player"},
    "th_ship": {"pt": "nave", "en": "ship"},
    "th_system": {"pt": "sistema", "en": "system"},
    "th_age": {"pt": "idade", "en": "age"},
    "days": {"pt": "dias", "en": "days"},
    "playing": {"pt": "jogando", "en": "playing"},
    "and_more": {"pt": "+{n} naves neste sistema",
                 "en": "+{n} ships on this system"},
    "first_here": {"pt": "primeiro aqui", "en": "first here"},
    "never_reached": {"pt": "ninguém chegou aqui ainda",
                      "en": "nobody has reached this yet"},
    "map_legend": {
        "pt": "Cada ponto é um sistema, na posição da estrela dele. Os claros "
              "são por onde a sala já passou. Passe o mouse para ver o nome e "
              "quem está lá.",
        "en": "Each dot is a system, at its star's position. Bright ones are "
              "where the room has been. Hover for the name and who is there.",
    },

    # -- how to join
    "how_to_join": {"pt": "Como entrar", "en": "How to join"},
    "how_intro": {
        "pt": "Crie uma partida no Space Haven com esta seed e estas opções. A "
              "seed reproduz a galáxia inteira, mas não a sua tripulação nem a "
              "sua nave — mesmo universo, gente diferente.",
        "en": "Create a game in Space Haven with this seed and these options. "
              "The seed reproduces the whole galaxy, but not your crew or your "
              "ship — same universe, different people.",
    },
    "seed": {"pt": "seed", "en": "seed"},
    "no_options_yet": {
        "pt": "o dono da sala ainda não publicou as opções",
        "en": "the room owner hasn't published the options yet",
    },
    "then_upload": {"pt": "Depois, suba o save:",
                    "en": "Then upload your save:"},
    "wrong_options": {
        "pt": "Opção de criação diferente dá outra galáxia, e o servidor "
              "recusa o save — com o motivo.",
        "en": "A different creation option yields a different galaxy, and the "
              "server refuses the save — telling you why.",
    },
    "locked_room": {
        "pt": "Esta sala tem senha. Peça ao dono a seed e as opções de criação.",
        "en": "This room is password-protected. Ask the owner for the seed and "
              "creation options.",
    },

    # -- onboarding pela web
    "join_us": {"pt": "Entrar", "en": "Join"},
    "create_account": {"pt": "Criar uma conta", "en": "Create an account"},
    "your_name": {"pt": "Como você quer ser chamado",
                  "en": "What you want to be called"},
    "no_email": {
        "pt": "Sem e-mail, sem senha, sem login de Steam. O servidor gera um "
              "código aleatório e guarda só o resumo dele.",
        "en": "No email, no password, no Steam login. The server generates a "
              "random code and keeps only a digest of it.",
    },
    "account_made": {"pt": "Conta criada", "en": "Account created"},
    "your_code": {"pt": "O seu código de recuperação",
                  "en": "Your recovery code"},
    "code_warning": {
        "pt": "Guarde agora, num lugar que você vá reencontrar. É a única "
              "forma de voltar a esta conta: o servidor não tem cópia, não há "
              "e-mail de recuperação, e perder é perder.",
        "en": "Save it now, somewhere you will find again. It is the only way "
              "back into this account: the server keeps no copy, there is no "
              "recovery email, and losing it means losing the account.",
    },
    "use_in_client": {
        "pt": "Para usar no cliente:",
        "en": "To use it in the client:",
    },
    "new_room": {"pt": "Criar uma sala", "en": "Create a room"},
    "room_name": {"pt": "Nome da sala", "en": "Room name"},
    "room_seed_help": {
        "pt": "A seed que você usou ao criar a sua partida. O servidor não "
              "consegue gerar uma galáxia — quem cria é o jogo, na sua "
              "máquina. Você cria a partida uma vez, sobe o save, e a partir "
              "daí o servidor entrega essa galáxia a quem entrar.",
        "en": "The seed you used when creating your game. The server cannot "
              "generate a galaxy — the game does, on your machine. You create "
              "the game once, upload the save, and from then on the server "
              "hands that galaxy to whoever joins.",
    },
    "create": {"pt": "Criar", "en": "Create"},
    "owner_next": {
        "pt": "Sala criada. Agora suba o save da sua partida: é ele que "
              "define a galáxia que todos vão dividir.",
        "en": "Room created. Now upload your game's save: it is what defines "
              "the galaxy everyone will share.",
    },
    "need_account": {
        "pt": "Você precisa de uma conta para criar uma sala.",
        "en": "You need an account to create a room.",
    },
    "signed_as": {"pt": "conectado como", "en": "signed in as"},

    # -- data policy
    "privacy_title": {"pt": "O que acontece com o seu save",
                      "en": "What happens to your save"},
    "back": {"pt": "voltar", "en": "back"},
}


def pick(accept_language: str = "", query: str = "") -> str:
    """Response language. `?lang=` wins, then the browser, then English."""
    if query and query.lower()[:2] in LANGS:
        return query.lower()[:2]
    for part in (accept_language or "").split(","):
        code = part.split(";")[0].strip().lower()[:2]
        if code in LANGS:
            return code
    return DEFAULT


def t(key: str, lang: str) -> str:
    """One string. An unknown key returns itself, so the mistake shows up."""
    return STRINGS.get(key, {}).get(lang, key)
