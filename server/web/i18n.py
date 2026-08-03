"""
Page strings, in English and Portuguese.

The pages are the front door, step 2 of section 2.11, where someone sees a
living room and decides whether to join. Serving a single language shuts that
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
    "rooms": {"pt": "galáxias", "en": "galaxies"},
    "home": {"pt": "Início", "en": "Home"},
    "nav_rooms": {"pt": "Galáxias", "en": "Galaxies"},
    "nav_client": {"pt": "Cliente", "en": "Client"},
    "nav_recovery": {"pt": "Código de acesso", "en": "Recovery code"},
    "nav_privacy": {"pt": "Privacidade", "en": "Privacy"},

    # -- o cliente, por sistema
    "client_title": {"pt": "Instalar e usar o cliente",
                     "en": "Install and use the client"},
    "client_intro": {
        "pt": "Um arquivo só. Sem instalador, sem Python, sem dependência. "
              "Ele fala com o servidor e abre o jogo; o Space Haven continua "
              "sendo o seu, instalado onde sempre esteve.",
        "en": "One file. No installer, no Python, no dependencies. It talks to "
              "the server and opens the game; Space Haven stays yours, "
              "installed where it always was.",
    },
    "on_windows": {"pt": "No Windows", "en": "On Windows"},
    "on_unix": {"pt": "No macOS e no Linux", "en": "On macOS and Linux"},
    "unix_chmod": {
        "pt": "Depois de baixar, dê permissão de execução e rode a partir da "
              "pasta onde ele está:",
        "en": "After downloading, make it executable and run it from the "
              "folder it is in:",
    },
    "windows_note": {
        "pt": "Abra o PowerShell na pasta onde baixou. O Windows pode avisar "
              "que o arquivo veio da internet. É um binário sem assinatura "
              "paga, e o código está aberto para conferência.",
        "en": "Open PowerShell in the folder you downloaded to. Windows may "
              "warn that the file came from the internet. It is an unsigned "
              "binary, and the source is open to inspection.",
    },
    "what_it_writes": {"pt": "O que ele cria no seu computador",
                       "en": "What it writes on your machine"},
    "mod_h": {"pt": "O mod, que é opcional",
              "en": "The mod, which is optional"},
    "mod_why": {
        "pt": "Tudo funciona sem ele. O que ele tira são as partes chatas: "
              "abre o save da galáxia direto, escreve a galáxia e as suas vendas no "
              "log do jogo, põe um botão SHOP no painel do depósito, e cala os "
              "chamados automáticos das vitrines dos vizinhos.",
        "en": "Everything works without it. What it removes are the fiddly "
              "parts: it opens the galaxy's save straight away, writes the galaxy "
              "and your sales into the game log, puts a SHOP toggle on a "
              "storage panel, and silences the automatic hails from your "
              "neighbours' storefronts.",
    },
    "mod_needs_loader": {
        "pt": "Ele precisa do <b>SpaceHaven Mod Loader</b>, que é um item do "
              "Workshop. Assine-o e deixe o Steam baixar. É de onde vem o "
              "AspectJ, que é o que permite um mod de código existir neste "
              "jogo.",
        "en": "It needs the <b>SpaceHaven Mod Loader</b>, a Workshop item. "
              "Subscribe and let Steam download it. That is where AspectJ "
              "comes from, and AspectJ is what makes a code mod possible in "
              "this game at all.",
    },
    "mod_install_h": {"pt": "Instalar", "en": "Installing"},
    "mod_install_help": {
        "pt": "O cliente já leva o mod dentro dele. Com o <b>jogo fechado</b>:",
        "en": "The client already carries the mod inside it. With the "
              "<b>game closed</b>:",
    },
    "mod_closed_why": {
        "pt": "Com o jogo aberto ele recusa, de propósito: a JVM lê o jar uma "
              "vez, ao iniciar, então trocar o arquivo durante a partida não "
              "muda nada, e faria você testar a versão antiga achando que "
              "testa a nova.",
        "en": "With the game open it refuses, on purpose: the JVM reads the "
              "jar once, at startup, so swapping the file mid-session changes "
              "nothing, and would have you testing the old version believing "
              "it is the new one.",
    },
    "mod_uninstall": {"pt": "Para desfazer:", "en": "To undo it:"},
    "mod_touches": {
        "pt": "Ele não altera os arquivos do jogo. O <code>spacehaven.jar</code> "
              "fica intacto; o que muda são três linhas no "
              "<code>config.json</code> ao lado dele, e há backup.",
        "en": "It does not patch the game's files. "
              "<code>spacehaven.jar</code> is untouched; what changes is three "
              "lines in the <code>config.json</code> beside it, and a backup "
              "is kept.",
    },
    "writes_intro": {
        "pt": "Um arquivo, e só um. É onde o seu código de acesso fica "
              "guardado, para você não ter que digitá-lo a cada sessão:",
        "en": "One file, and only one. It is where your access code is kept so "
              "you do not have to type it every session:",
    },
    "writes_detail": {
        "pt": "No Windows o caminho equivalente é "
              "<code>%USERPROFILE%\\.config\\sgalaxy\\credentials.json</code>. "
              "O arquivo é criado com permissão 600 (só o seu usuário lê) e "
              "guarda o código em claro, porque ele <b>é</b> a sua conta: quem "
              "ler o arquivo entra como você. Apagar o arquivo desconecta "
              "este computador da conta, e a conta segue viva no servidor.",
        "en": "On Windows the equivalent path is "
              "<code>%USERPROFILE%\\.config\\sgalaxy\\credentials.json</code>. "
              "The file is created mode 600 (only your user can read it) and "
              "holds the code in the clear, because it <b>is</b> your account: "
              "anybody who reads the file signs in as you. Deleting the file "
              "disconnects this machine, and the account stays alive on the "
              "server.",
    },

    # -- codigo de recuperacao
    "recovery_title": {"pt": "Usar um código de recuperação",
                       "en": "Using a recovery code"},
    "recovery_what": {
        "pt": "O código de recuperação <b>é</b> a sua conta. Não há e-mail, "
              "senha nem \"esqueci minha senha\": o servidor guarda apenas um "
              "resumo criptográfico dele, e por isso não consegue te devolver "
              "o código se você perder.",
        "en": "The recovery code <b>is</b> your account. There is no email, no "
              "password and no \"forgot my password\": the server keeps only a "
              "cryptographic digest of it, which is exactly why it cannot give "
              "the code back to you if you lose it.",
    },
    "recovery_when": {
        "pt": "Você usa o código quando troca de computador, reinstala o "
              "sistema, ou quando o servidor diz que já existe uma conta "
              "criada da sua conexão.",
        "en": "You use the code when you change machines, reinstall your "
              "system, or when the server says an account already exists from "
              "your connection.",
    },
    "recovery_how": {"pt": "Como usar", "en": "How to use it"},
    "recovery_check": {
        "pt": "O cliente confere com o servidor <b>antes</b> de gravar. Um "
              "código digitado errado não apaga a conta que já estava ali.",
        "en": "The client checks with the server <b>before</b> writing. A "
              "mistyped code will not overwrite an account already there.",
    },
    "recovery_dashes": {
        "pt": "Os traços são só para copiar sem errar: com ou sem eles, e em "
              "qualquer caixa, funciona igual.",
        "en": "The dashes only make it easier to copy: with or without them, "
              "in any case, it works the same.",
    },

    # -- apagar a conta
    "delete_title": {"pt": "Apagar a conta e sair",
                     "en": "Delete your account and leave"},
    "delete_intro": {
        "pt": "Apaga a sua conta e todos os seus saves. Não há etapa de "
              "arrependimento e não há como desfazer.",
        "en": "This deletes your account and every save you have. There is no "
              "second-guessing step and there is no undo.",
    },
    "delete_rooms_note": {
        "pt": "Salas que você criou e que ainda têm outras pessoas dentro "
              "continuam de pé: apagá-las destruiria o save de quem não pediu "
              "nada. Elas saem da listagem pública e o seu código deixa de "
              "valer.",
        "en": "Rooms you created that still have other people in them stay up: "
              "deleting them would destroy the saves of people who asked for "
              "nothing. They leave the public listing and your code stops "
              "working.",
    },
    "your_code_label": {"pt": "O seu código de recuperação",
                        "en": "Your recovery code"},
    "delete_confirm_label": {
        "pt": "Digite <code>delete everything</code> para confirmar",
        "en": "Type <code>delete everything</code> to confirm",
    },
    "delete_button": {"pt": "Apagar tudo", "en": "Delete everything"},
    "delete_done": {"pt": "Apagado.", "en": "Deleted."},
    "delete_bad_code": {
        "pt": "Esse código não corresponde a nenhuma conta.",
        "en": "That code does not match any account.",
    },
    "delete_bad_confirm": {
        "pt": "A confirmação não confere.",
        "en": "The confirmation does not match.",
    },
    "invite_code": {"pt": "Código de convite", "en": "Invite code"},
    "invite_help": {
        "pt": "Este servidor pede convite. Quem te chamou tem o código.",
        "en": "This server asks for an invite. Whoever invited you has the code.",
    },
    "invite_wrong": {"pt": "Convite inválido.", "en": "That invite is not valid."},
    "one_per_ip": {
        "pt": "Já existe uma conta criada desta conexão. Se a conta é sua, "
              "use o seu código de acesso em vez de criar outra. Se você "
              "divide a internet com quem já "
              "entrou, fale com quem administra a galáxia.",
        "en": "An account has already been created from this connection. If it "
              "is yours, use your recovery code instead of making another. If "
              "you share the connection with somebody who already joined, ask "
              "whoever runs the galaxy.",
    },
    "nav_how": {"pt": "Como funciona", "en": "How it works"},
    "how_title": {"pt": "Como funciona", "en": "How it works"},

    # -- entrar numa sala
    "join_this": {"pt": "Entrar nesta galáxia", "en": "Join this galaxy"},
    "join_title": {"pt": "Entrar em %s", "en": "Join %s"},
    "join_intro": {
        "pt": "O jogo continua sendo o seu, no seu computador. O que este "
              "servidor faz é guardar o save entre as sessões e emprestá-lo "
              "de volta com a galáxia atualizada pelas outras pessoas.",
        "en": "The game stays yours, on your machine. What this server does is "
              "keep the save between sessions and hand it back with the galaxy "
              "as the others left it.",
    },
    "step_download": {"pt": "1. Baixe o cliente",
                      "en": "1. Download the client"},
    "step_download_help": {
        "pt": "Um arquivo só, sem instalador e sem Python. Você precisa ter o "
              "Space Haven instalado; o cliente acha sozinho onde ele está.",
        "en": "One file, no installer and no Python. You need Space Haven "
              "installed; the client finds it on its own.",
    },
    "rename_it": {
        "pt": "Renomeie o arquivo baixado para <code>sgalaxy</code>. Os "
              "comandos abaixo usam esse nome, e o arquivo chega com o do "
              "sistema no fim.",
        "en": "Rename the file you downloaded to <code>sgalaxy</code>. The "
              "commands below use that name, and the file arrives with the "
              "system stamped on the end.",
    },
    "mod_optional_here": {
        "pt": "O mod é opcional e melhora a vida: ele abre o save da galáxia "
              "direto e põe o botão da loja dentro do jogo.",
        "en": "The mod is optional and makes life easier: it opens the galaxy's "
              "save for you and puts the shop toggle inside the game.",
    },
    "step_account": {"pt": "2. Entre na sua conta",
                     "en": "2. Sign in to your account"},
    "step_account_help": {
        "pt": "Se ainda não tem conta, crie uma. Ela leva um nome e devolve "
              "um código de recuperação, que é o que o cliente usa.",
        "en": "If you do not have an account yet, make one. It takes a name "
              "and gives back a recovery code, which is what the client uses.",
    },
    "step_mod": {"pt": "3. Instale o mod (opcional)",
                 "en": "3. Install the mod (optional)"},
    "step_join": {"pt": "4. Entre na galáxia e jogue",
                  "en": "4. Join the galaxy and play"},
    "step_join_help": {
        "pt": "Um comando faz tudo: a galáxia te entrega uma cópia da partida de "
              "quem a fundou, com a sua nave batizada com o seu nome e "
              "estacionada num campo de asteroides livre, e o jogo abre nela. "
              "Ao fechar o jogo, o save volta para a galáxia sozinho.",
        "en": "One command does all of it: the galaxy hands you a copy of the "
              "game its founder started, with your ship named after you and "
              "parked on a free asteroid field, and the game opens on it. When "
              "you close the game the save goes back on its own.",
    },
    "step_join_empty": {
        "pt": "Se você for a primeira pessoa da galáxia, não há partida para "
              "copiar: o jogo abre para você criar a sua em NEW GAME, e é ela "
              "que vira o ponto de partida de quem chegar depois.",
        "en": "If you are the first person in the galaxy there is nothing to "
              "copy: the game opens for you to create yours in NEW GAME, and "
              "that one becomes the starting point for everybody after you.",
    },
    "mod_first": {
        "pt": "Instale o mod antes deste passo, se for instalar: com ele o "
              "jogo já abre no lugar certo.",
        "en": "Install the mod before this step if you are going to: with it "
              "the game opens where it should on its own.",
    },
    "step_play": {"pt": "5. Depois disso", "en": "5. After that"},
    "step_play_help": {
        "pt": "O mesmo comando serve para todas as próximas sessões: ele "
              "retira o save, abre o jogo e devolve quando você fecha. "
              "<code>play</code> é o mesmo comando com outro nome.",
        "en": "The same command runs every session from here on: it checks the "
              "save out, opens the game, and gives it back when you close it. "
              "<code>play</code> is the same command under another name.",
    },
    "room_full": {"pt": "Esta galáxia está cheia.", "en": "This galaxy is full."},
    "room_locked": {
        "pt": "Esta galáxia pede senha. Peça a quem te convidou e informe com "
              "<code>--password</code>.",
        "en": "This galaxy asks for a password. Ask whoever invited you and pass "
              "it with <code>--password</code>.",
    },
    "join_age_rule": {
        "pt": "Partidas com mais de %s dias de jogo não entram: a galáxia começa "
              "junta, e uma colônia madura chegaria pronta numa galáxia que "
              "ninguém desbravou ainda.",
        "en": "Games older than %s in-game days cannot join: the galaxy starts "
              "together, and a mature colony would arrive finished in a galaxy "
              "nobody has opened yet.",
    },
    "download_linux": {"pt": "Linux", "en": "Linux"},
    "download_windows": {"pt": "Windows", "en": "Windows"},
    "download_macos": {"pt": "macOS (Apple Silicon)", "en": "macOS (Apple Silicon)"},
    "have_account": {"pt": "Já tenho conta", "en": "I already have an account"},
    "no_account_yet": {"pt": "Criar uma conta", "en": "Create an account"},
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
        "pt": "Nenhuma galáxia aberta ainda. Quem criar a primeira define a "
              "galáxia que todos vão dividir.",
        "en": "No open galaxies yet. Whoever creates the first one defines the "
              "galaxy everyone will share.",
    },
    "players": {"pt": "jogadores", "en": "players"},
    "has_password": {"pt": "com senha", "en": "password"},

    # -- room
    "room": {"pt": "galáxia", "en": "galaxy"},
    "lease_of": {"pt": "empréstimo de", "en": "lease of"},
    "who_is_where": {"pt": "Quem está onde", "en": "Who is where"},
    "nobody_yet": {
        "pt": "Ninguém entrou ainda. O primeiro save a subir é o que esta "
              "galáxia vai ser.",
        "en": "Nobody has joined yet. The first save uploaded is what this "
              "galaxy will be.",
    },
    "map_later": {
        "pt": "O mapa aparece quando o primeiro jogador entrar: é o save dele "
              "que define a galáxia da galáxia.",
        "en": "The map appears once the first player joins, because their save is "
              "what defines the galaxy's galaxy.",
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
              "são por onde a galáxia já passou. Passe o mouse para ver o nome e "
              "quem está lá.",
        "en": "Each dot is a system, at its star's position. Bright ones are "
              "where the galaxy has been. Hover for the name and who is there.",
    },

    # -- how to join
    "how_to_join": {"pt": "Como entrar", "en": "How to join"},
    "how_intro": {
        "pt": "Crie uma partida no Space Haven com esta seed e estas opções. A "
              "seed reproduz a galáxia inteira, mas não a sua tripulação nem a "
              "sua nave. Mesmo universo, gente diferente.",
        "en": "Create a game in Space Haven with this seed and these options. "
              "The seed reproduces the whole galaxy, but not your crew or your "
              "ship. Same universe, different people.",
    },
    "seed": {"pt": "seed", "en": "seed"},
    "no_options_yet": {
        "pt": "o dono da galáxia ainda não publicou as opções",
        "en": "the galaxy owner hasn't published the options yet",
    },
    "then_upload": {"pt": "Depois, suba o save:",
                    "en": "Then upload your save:"},
    "wrong_options": {
        "pt": "Opção de criação diferente dá outra galáxia, e o servidor "
              "recusa o save, dizendo o motivo.",
        "en": "A different creation option yields a different galaxy, and the "
              "server refuses the save and tells you why.",
    },
    "locked_room": {
        "pt": "Esta galáxia tem senha. Peça o código a quem administra.",
        "en": "This galaxy is password-protected. Ask whoever runs it for the code.",
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
    "new_room": {"pt": "Criar uma galáxia", "en": "Create a galaxy"},
    "room_name": {"pt": "Nome da galáxia", "en": "Galaxy name"},
    "room_seed_help": {
        "pt": "A seed que você usou ao criar a sua partida. O servidor não "
              "consegue gerar uma galáxia. Quem cria é o jogo, na sua "
              "máquina. Você cria a partida uma vez, sobe o save, e a partir "
              "daí o servidor entrega essa galáxia a quem entrar.",
        "en": "The seed you used when creating your game. The server cannot "
              "generate a galaxy. The game does, on your machine. You create "
              "the game once, upload the save, and from then on the server "
              "hands that galaxy to whoever joins.",
    },
    "create": {"pt": "Criar", "en": "Create"},
    "owner_next": {
        "pt": "Galáxia criada. Agora suba o save da sua partida: é ele que "
              "todo mundo aqui vai dividir, e o começo de quem chegar depois.",
        "en": "Galaxy created. Now upload your game's save: it is what "
              "everybody here will share, and where newcomers will begin.",
    },
    "need_account": {
        "pt": "Você precisa de uma conta para criar uma galáxia.",
        "en": "You need an account to create a galaxy.",
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
