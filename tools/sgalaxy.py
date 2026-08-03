"""
Shared Galaxy command-line client.

Runs the session cycle of section 2.4 from a terminal: create an account, join a
room, check the save out, and return it after playing. This is the skeleton of
what becomes a tab in the savegame editor (stage C of the plan) — the cycle
logic lives here, and the GUI will only call it.

Standard library only, like the rest of `tools/`: anyone who wants to check what
gets uploaded reads this file end to end in twenty minutes, installing nothing.

Usage:

    export SGALAXY_URL=https://galaxy.bygianotto.com.br

    sgalaxy register "My Name"          # or: python3 tools/sgalaxy.py …
    sgalaxy galaxies
    sgalaxy create-galaxy --seed 1654267488 --name "Frontier" --max-players 64
    sgalaxy join GALAXY                 # the whole session, one command
    sgalaxy shop GALAXY --set 608
    sgalaxy status GALAXY
    sgalaxy delete-galaxy GALAXY
    sgalaxy delete-account

The token lives in `~/.config/sgalaxy/credentials.json`, mode 600. It is the
only credential there is: losing it means losing the account, and there is no
recovery email.

THE RULE THAT IS NOT NEGOTIABLE: never write to a save while the game is open.
The game rewrites the file when it saves, and writing underneath it destroys
someone's run. `checkout`, `return` and `play` detect the process and refuse.
"""

from __future__ import annotations

import argparse
import http.client
import io
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import zipfile

# O proprio diretorio entra no path antes do import irmao. Sem isto o modulo so
# importa quando `tools/` ja esta no path — que e o caso ao rodar o script, e
# nao e o caso de quem o carrega por caminho de arquivo, como os testes e
# qualquer coisa que o embuta.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import steamfind  # noqa: E402
from _version import VERSION  # noqa: E402

CONFIG_DIR = os.path.expanduser("~/.config/sgalaxy")
CREDENTIALS = os.path.join(CONFIG_DIR, "credentials.json")

# O servidor publico. Quem hospeda o proprio poe `SGALAXY_URL` e nada mais muda
# — e a mesma promessa do compose: o caminho da sala publica e o de quem
# levanta a dele.
# Como o cliente se apresenta. `sgalaxy` e o nome do programa; a versao muda
# junto com o protocolo, nao com cada correcao.
USER_AGENT = (f"sgalaxy/{VERSION} "
              f"(+https://github.com/Gianotto/shared-galaxy)")

DEFAULT_URL = os.environ.get("SGALAXY_DEFAULT_URL",
                             "https://galaxy.bygianotto.com.br")


def prog() -> str:
    """Como chamar este programa, do jeito que a pessoa o chamou.

    Empacotado num binario nao existe `python3 tools/sgalaxy.py`, e uma
    mensagem que manda rodar isso manda a pessoa para o lugar errado.
    """
    if getattr(sys, "frozen", False):
        return os.path.basename(sys.argv[0])
    return f"python3 {os.path.join('tools', 'sgalaxy.py')}"

# Como o jogo aparece na tabela de processos. Duas formas:
#
# `spacehaven` e o launcher nativo, e o name do EXECUTAVEL — casado com `-x`,
# que compara so o name do programa. `spacehaven.jar` e a JVM que ele levanta, e
# so aparece na linha de comando, entao esse precisa de `-f`.
#
# A primeira versao usava `-f` com "SpaceHaven" solto, e casava demais: qualquer
# processo do Steam que mencionasse o path da instalacao — e ate o own
# shell que rodou o comando — virava "o jogo esta running". O erro e caro nos
# dois sentidos: falso positivo trava o jogador de brincadeira, falso negativo
# destroi a partida dele.
GAME_EXECUTABLES = ("spacehaven",)
GAME_COMMANDLINES = ("spacehaven.jar",)


class ClientError(Exception):
    """An error the user needs to read."""


# ---------------------------------------------------------------------------
# Credenciais
# ---------------------------------------------------------------------------

def parse_recovery_code(code: str) -> str:
    """Aceita o codigo com ou sem os tracos, e em qualquer caixa."""
    import re
    return re.sub(r"[\s-]", "", code).upper()


def base_url() -> str:
    return os.environ.get("SGALAXY_URL", DEFAULT_URL).rstrip("/")


def load_credentials() -> dict:
    if not os.path.isfile(CREDENTIALS):
        return {}
    with open(CREDENTIALS, "r", encoding="utf-8") as fh:
        return json.load(fh).get(base_url(), {})


def save_credentials(data: dict) -> None:
    os.makedirs(CONFIG_DIR, mode=0o700, exist_ok=True)
    todos = {}
    if os.path.isfile(CREDENTIALS):
        with open(CREDENTIALS, "r", encoding="utf-8") as fh:
            todos = json.load(fh)
    todos[base_url()] = data
    with open(CREDENTIALS, "w", encoding="utf-8") as fh:
        json.dump(todos, fh, indent=2, ensure_ascii=False)
    os.chmod(CREDENTIALS, 0o600)


def token() -> str:
    creds = load_credentials()
    if not creds.get("token"):
        raise ClientError(
            f"no account stored for {base_url()}. "
            f"Run: {prog()} register \"Your Name\"")
    return creds["token"]


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

# O que cada resposta quer dizer, em portugues de gente. O numero sozinho e
# util para quem escreveu o servidor e para mais ninguem: "error code: 1010"
# nao diz que a Cloudflare barrou o cliente, nem o que fazer a respeito.
#
# Os 1xxx sao da Cloudflare e nao do nosso servidor, o que importa: dizer "o
# servidor recusou" quando quem recusou foi o intermediario manda a pessoa
# procurar defeito no lugar errado.
CLOUDFLARE = {
    "1010": ("blocked by Cloudflare",
             "Cloudflare turned this request away because it did not "
             "recognise the client. This usually means an old build: "
             "download the latest from "
             "github.com/Gianotto/shared-galaxy/releases"),
    "1015": ("rate limited by Cloudflare",
             "too many requests from this address in a short time. Wait a "
             "minute and try again"),
    "1020": ("refused by a Cloudflare rule",
             "a firewall rule turned this request away. Whoever hosts the "
             "server can see which one in their Cloudflare dashboard"),
}

HTTP_NAMES = {
    400: "the server could not read what was sent",
    401: "not signed in",
    403: "not allowed",
    404: "not found",
    409: "conflicts with the current state",
    413: "too large",
    429: "too many requests",
    500: "the server broke",
    502: "the server is not answering",
    503: "the server is down for a moment",
    504: "the server took too long",
}


def explain(code: int, detail: str) -> str:
    """A resposta do servidor numa frase que se le sem consultar tabela."""
    achado = re.search(r"error code:\s*(\d{4})", detail or "")
    if achado:
        nome, o_que = CLOUDFLARE.get(
            achado.group(1),
            (f"Cloudflare error {achado.group(1)}",
             "the request never reached the server"))
        return f"{nome} ({achado.group(1)}). {o_que}"
    nome = HTTP_NAMES.get(code)
    limpo = " ".join((detail or "").split())
    if nome and limpo:
        return f"{nome} ({code}): {limpo}"
    if nome:
        return f"{nome} ({code})"
    return f"the server refused ({code}): {limpo}"


def request(method: str, path: str, body: bytes | None = None,
            headers: dict | None = None, auth: bool = True) -> tuple:
    """Devolve (status, corpo, headers). Erro do servidor vira ClientError."""
    url = f"{base_url()}{path}"
    head = dict(headers or {})
    # Identificar-se nao e cortesia: a protecao de bot da Cloudflare barra o
    # `Python-urllib` padrao com um 403 "error code 1010", e o erro parece do
    # servidor sem ser dele. Um cliente que diz quem e passa, e quem hospeda
    # consegue ver nos registros o que e trafego nosso.
    head.setdefault("User-Agent", USER_AGENT)
    # Um `Authorization` explicito ganha do guardado. E o que permite conferir
    # um codigo de recuperacao ANTES de grava-lo por cima do que ja existe.
    if auth and "Authorization" not in head:
        head["Authorization"] = f"Bearer {token()}"
    req = urllib.request.Request(url, data=body, method=method, headers=head)
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            # Cabecalho HTTP nao tem caixa, e o uvicorn responde em minusculo.
            # Um `dict()` cru deixava `headers.get("X-Lease-Expires")` devolver
            # None, e o jogador nao via ate quando o save era dele.
            cabecalhos = {k.lower(): v for k, v in resp.headers.items()}
            return resp.status, resp.read(), cabecalhos
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            detail = json.loads(raw).get("detail", raw.decode("utf-8", "replace"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            detail = raw.decode("utf-8", "replace")
        raise ClientError(explain(exc.code, detail)) from exc
    except urllib.error.URLError as exc:
        raise ClientError(f"could not reach {base_url()}: {exc.reason}") from exc
    except (OSError, http.client.HTTPException) as exc:
        # A conexão caiu no meio. `RemoteDisconnected` não é `URLError` nem
        # `HTTPError`, então escapava cru — e quem estava devolvendo um save via
        # um traceback em vez da mensagem que diz onde a partida está e como
        # devolvê-la. Uma sala aberta a sessenta e quatro pessoas vai ver isto.
        raise ClientError(
            f"the connection to {base_url()} broke: {exc}") from exc


def json_request(method: str, path: str, payload: dict | None = None,
                 auth: bool = True) -> dict:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    head = {"Content-Type": "application/json"} if body else {}
    _status, raw, _h = request(method, path, body, head, auth)
    return json.loads(raw) if raw else {}


# ---------------------------------------------------------------------------
# Savegame
# ---------------------------------------------------------------------------

def game_is_running() -> str | None:
    """O name do processo do jogo, se ele estiver running.

    A regra mais importante do cliente (secao 2.9): nunca escrever num save com
    o jogo running. Sem `pgrep`, devolve None e o chamador avisa que nao
    conseguiu conferir — nunca assume que esta fechado.
    """
    if shutil.which("pgrep") is None:
        return None

    own = {str(os.getpid()), str(os.getppid())}

    def encontrou(args: list) -> bool:
        try:
            out = subprocess.run(["pgrep", *args], capture_output=True,
                                 timeout=5, text=True)
        except (subprocess.SubprocessError, OSError):
            return False
        if out.returncode != 0:
            return False
        pids = {p for p in out.stdout.split() if p and p not in own}
        return bool(pids)

    for name in GAME_EXECUTABLES:
        if encontrou(["-x", name]):
            return name
    for pattern in GAME_COMMANDLINES:
        if encontrou(["-f", pattern]):
            return pattern
    return None


def find_game() -> str | None:
    """O executavel do jogo, se der para achar sozinho.

    O launcher e um binario nativo que le `config.json` e levanta a JVM, e nao
    precisa do Steam para rodar. Achar sozinho e o que permite o fluxo unico:
    sem isso, a pessoa teria que dizer o path toda vez.

    A busca sai de `steamfind`, que le as bibliotecas do proprio Steam. A lista
    escrita a mao que estava aqui so tinha caminhos de Linux, entao no Windows
    ela nunca achava nada, e o Windows e onde a maior parte da gente joga.
    """
    return steamfind.launcher()


def age_of(folder: str) -> float:
    """O idade de uma folder de save, ou -1 se nao der para ler."""
    import xml.etree.ElementTree as ET
    path = os.path.join(folder, "info")
    try:
        with open(path, "rb") as fh:
            valor = ET.fromstring(fh.read()).get("date")
        return int(valor) / 86400 if valor else -1.0
    except (OSError, ET.ParseError, ValueError, TypeError):
        return -1.0


def most_advanced(room_folder: str) -> tuple:
    """A folder com mais progresso: o save manual ou o autosave mais adiantado.

    Quem sai do jogo sem salvar na mao deixa o avanco no autosave, e a secao
    2.4 e explicita: o cliente precisa conseguir devolver o ultimo autosave.
    Comparar por idade, e nao por data de arquivo, e o que faz isso valer
    tambem depois de uma queda — o relogio do sistema nao diz quanto se jogou.
    """
    room_folder = os.path.abspath(os.path.expanduser(room_folder))
    candidatos = []
    for name in sorted(os.listdir(room_folder)):
        path = os.path.join(room_folder, name)
        if os.path.isfile(os.path.join(path, "game")):
            candidatos.append((age_of(path), name, path))
    if not candidatos:
        raise ClientError(f"no savegame found inside {room_folder}")
    candidatos.sort(reverse=True)
    age, name, path = candidatos[0]
    return path, name, age


def resolve_save(path: str) -> str:
    """Aceita a folder do save, a folder que a contem, ou o arquivo `game`."""
    path = os.path.abspath(os.path.expanduser(path))
    if os.path.isfile(path):
        return os.path.dirname(path)
    if os.path.isdir(path):
        if os.path.isfile(os.path.join(path, "game")):
            return path
        dentro = os.path.join(path, "save")
        if os.path.isfile(os.path.join(dentro, "game")):
            return dentro
    raise ClientError(f"no savegame in {path} "
                      f"(expected a `game` file in there)")


def pack(folder: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for dirpath, _dirs, files in os.walk(folder):
            for name in sorted(files):
                # Backups do editor nao sao parte do save.
                if ".bak-" in name or name.endswith(".tmp"):
                    continue
                full = os.path.join(dirpath, name)
                zf.write(full, os.path.relpath(full, folder))
    return buf.getvalue()


def unpack(data: bytes, dest: str) -> str:
    """Abre o save recebido numa folder de savegame do jogo.

    Escreve numa folder ao lado e so entao troca, para uma queda no meio nao
    deixar o jogador com um save pela metade.
    """
    dest = os.path.abspath(os.path.expanduser(dest))
    temp = dest + ".novo"
    shutil.rmtree(temp, ignore_errors=True)
    os.makedirs(temp, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        zf.extractall(temp)

    save_dir = temp if os.path.isfile(os.path.join(temp, "game")) else None
    if save_dir is None:
        for root, _d, files in os.walk(temp):
            if "game" in files:
                save_dir = root
                break
    if save_dir is None:
        shutil.rmtree(temp, ignore_errors=True)
        raise ClientError("the server sent something that is not a savegame")

    final_dir = os.path.join(dest, "save")
    previous = dest + ".anterior"
    shutil.rmtree(previous, ignore_errors=True)
    if os.path.exists(dest):
        os.replace(dest, previous)
    os.makedirs(dest, exist_ok=True)
    shutil.move(save_dir, final_dir)
    shutil.rmtree(temp, ignore_errors=True)

    # O Steam Cloud sincroniza `savegames/<Nome>/cloudZipFile.zip`, e so isso —
    # medido no remotecache.vdf do jogo. O `save/` e local; o zip e a copia da
    # nuvem, e o jogo o refaz ao gravar.
    #
    # Um zip velho ao lado de um save recem-retirado e a combinacao perigosa: se
    # o Steam resolver restaurar, ele sobrescreve a sessao que o servidor
    # emprestou com uma partida antiga, e o jogador perde o progresso sem
    # entender por que. Entao o zip anterior sai daqui.
    for junk in ("cloudZipFile.zip", "cloud.xml"):
        path = os.path.join(dest, junk)
        if os.path.exists(path):
            os.unlink(path)
    return final_dir


# ---------------------------------------------------------------------------
# Comandos
# ---------------------------------------------------------------------------

def cmd_register(args) -> int:
    # Quem registrou pelo navegador já tem conta; aqui só guarda o código.
    if args.recover:
        code = parse_recovery_code(args.recover)
        # CONFERIR ANTES DE GRAVAR.
        #
        # A primeira versao gravava o codigo e so entao perguntava ao servidor
        # quem era. Um codigo digitado errado apagava a conta que ja estava ali
        # — e como o token e a unica credencial que existe, isso e perder a
        # conta se o papel nao estiver a mao.
        _s, raw, _h = request("GET", "/api/v1/me",
                              headers={"Authorization": f"Bearer {code}"})
        me = json.loads(raw)
        save_credentials({"token": code, "playerId": me["playerId"],
                          "name": me["name"]})
        print(f"signed in as {me['name']} on {base_url()}")
        return 0

    if not args.name:
        raise ClientError("give a name, or --recover CODE if you registered "
                          "on the website")
    data = json_request("POST", "/api/v1/players",
                         {"name": args.name, "invite": args.invite or ""},
                         auth=False)
    save_credentials({"token": data["token"], "playerId": data["playerId"],
                      "name": data["name"]})
    print(f"account created on {base_url()}")
    print(f"  name:  {data['name']}")
    print(f"  token: stored in {CREDENTIALS}")
    print()
    print("  RECOVERY CODE — write this down somewhere safe:")
    print(f"    {data['recoveryCode']}")
    print()
    print("  It is the only way back into this account. The server keeps no copy,")
    print("  there is no recovery email, and losing it means losing the account.")
    return 0


def cmd_rooms(args) -> int:
    data = json_request("GET", "/api/v1/rooms", auth=False)
    if not data["rooms"]:
        print("no open galaxies")
        return 0
    print(f"{'id':<8}{'players':<12}{'lock':<8}name")
    for room in data["rooms"]:
        print(f"{room['id']:<8}{room['players']}/{room['maxPlayers']:<10}"
              f"{'yes' if room['hasPassword'] else 'no':<8}{room['name']}")
    return 0


def cmd_create_room(args) -> int:
    data = json_request("POST", "/api/v1/rooms", {
        "seed": args.seed, "name": args.name, "password": args.password,
        "leaseHours": args.lease_hours, "maxPlayers": args.max_players,
        "options": _recipe(args)})
    print(f"galaxy {data['id']} created")
    print(f"  seed:  {data['seed']}")
    print(f"  sessions last: {data['leaseHours']}h")
    print()
    print("  Publish the recipe for whoever joins:")
    print(f"    {prog()} how-to-join {data['id']}")
    if not _recipe(args):
        print()
        print("  The recipe is empty. Once you have created the game,")
        print("  record the ship and the options you picked:")
        print(f"    {prog()} configure-galaxy {data['id']} \\")
        print('        --ship "Starting ship name" --difficulty Normal')
    return 0


def _recipe(args) -> dict:
    """O que alguem precisa reproduzir para o save ser aceito na galaxia."""
    recipe = {}
    if getattr(args, "ship", None):
        recipe["ship"] = args.ship
    if getattr(args, "difficulty", None):
        recipe["difficulty"] = args.difficulty
    for item in getattr(args, "option", None) or []:
        if "=" not in item:
            raise ClientError(f"--option expects key=value, got {item!r}")
        chave, valor = item.split("=", 1)
        recipe[chave.strip()] = valor.strip()
    return recipe


def cmd_configure_room(args) -> int:
    payload = {}
    recipe = _recipe(args)
    if recipe:
        if args.replace:
            payload["options"] = recipe
        else:
            # Mesclar e o padrao porque quase sempre se quer acrescentar uma
            # opcao, nao reescrever a receita. `--replace` existe para o outro
            # caso — inclusive apagar uma chave que nao deveria estar la.
            current = json_request("GET", f"/api/v1/rooms/{args.galaxy}")
            payload["options"] = {**(current.get("options") or {}), **recipe}
    if args.name:
        payload["name"] = args.name
    if args.lease_hours:
        payload["leaseHours"] = args.lease_hours
    if not payload:
        raise ClientError("nothing to change. Use --ship, --difficulty, "
                          "--option KEY=VALUE, --name or --lease-hours")
    json_request("PATCH", f"/api/v1/rooms/{args.galaxy}", payload)
    print(f"room {args.galaxy} updated")
    return cmd_how_to_join(args)


def cmd_how_to_join(args) -> int:
    """The recipe, laid out the way the creation screen asks for it."""
    head = {"X-Room-Password": getattr(args, "senha", None) or ""}
    _s, raw, _h = request("GET", f"/api/v1/rooms/{args.galaxy}", None, head)
    room = json.loads(raw)
    if "seed" not in room:
        raise ClientError("this room has a password; pass --password to see the recipe")

    print(f"To join room {room['id']} ({room['name']}):")
    print()
    print("  1. In Space Haven, create a new game with:")
    print(f"       seed: {room['seed']}")
    recipe = room.get("options") or {}
    if recipe.get("ship"):
        print(f"       starting ship: {recipe['ship']}")
    if recipe.get("difficulty"):
        print(f"       difficulty: {recipe['difficulty']}")
    others = {k: v for k, v in recipe.items()
              if k not in ("ship", "difficulty")}
    for key, value in sorted(others.items()):
        print(f"       {key}: {value}")
    if not recipe:
        print("       (the room owner has not published the scenario options yet)")
    print()
    print("  2. Save the game and close it.")
    print()
    print("  3. Upload the save:")
    print(f"       {prog()} join {room['id']} \\")
    print("           --save PATH/TO/YOUR/GAME")
    print()
    if room.get("galaxyDigest"):
        print(f"  This room's galaxy is {room['galaxyDigest']}. If your save does")
        print("  not match, a creation option differed — the seed alone is not")
        print("  enough.")
    else:
        print("  Nobody has joined yet: the first save uploaded defines the")
        print("  room's galaxy, and later ones must match it.")
    return 0


def cmd_join(args) -> int:
    """Entra na sala E joga. Um comando para a coisa toda.

    `join` e `play` faziam metades de uma acao so: entrar sem jogar nao serve
    para nada, e jogar exigia ter entrado antes. Quem chegava tinha que
    descobrir sozinho que eram dois passos, e errar a ordem dava um erro que
    nao explicava o que fazer.

    Sao o mesmo comando agora. `play` continua existindo porque e o nome que
    descreve o que acontece da segunda vez em diante, e porque links e
    mensagens antigas apontam para ele.
    """
    return cmd_play(args)


def _cmd_join_only(args) -> int:
    """Entra na sala sem abrir o jogo. Fica para quem automatiza."""
    if not args.save:
        # A SALA PRIMEIRO. Se ela tem um save de partida, entrar e um download:
        # a galaxia ja e a dela, a idade e do primeiro dia, e ninguem precisa
        # abrir o jogo para criar nave nenhuma.
        pronto = _start_in_room(args.galaxy, args.password or "")
        if pronto is not None:
            return pronto

        exe = args.game or find_game()
        if not exe or not os.path.isfile(exe):
            raise ClientError(
                "this room has no starting save, so your game has to be "
                "created in Space Haven, and I could not find it. Pass "
                "--game PATH, or point --save at a game you already have")
        if not first_join(args.galaxy, None, args.yes, args.password or "", exe):
            return 1
        print()
        print(f"  The server owns this save now. Play with: "
              f"{prog()} play {args.galaxy}")
        return 0

    folder = resolve_save(args.save)
    print(f"uploading {folder} …")
    _s, raw, _h = request("POST", f"/api/v1/rooms/{args.galaxy}/join",
                          pack(folder),
                          {"Content-Type": "application/zip",
                           "X-Room-Password": args.password or ""})
    data = json.loads(raw)
    galaxia = data["galaxy"]
    print(f"joined room {args.galaxy}")
    print(f"  galaxy:     {galaxia['digest']} "
          f"({galaxia['systems']} systems, {galaxia['bodies']} bodies)")
    print(f"  age:        {data['ageDays']} days")
    print(f"  your ship:  {data['presence']['shipName']}")
    print()
    nota = data.get("starter")
    if nota:
        print()
        print(f"  {nota}")
    print()
    print(f"  Play with: {prog()} join {args.galaxy}")
    return 0


def _start_in_room(room: str, senha: str):
    """Entra com o save de partida da sala. None quando ela nao tem um.

    Sala sem save de partida e a sala vazia: alguem tem que trazer a primeira
    partida, e ai o caminho antigo, pelo jogo, e o unico que existe.
    """
    try:
        _s, raw, _h = request("POST", f"/api/v1/rooms/{room}/start", b"",
                              {"X-Room-Password": senha})
    except ClientError as erro:
        texto = str(erro)
        # Sala sem partida guardada, ou servidor antigo que nao tem a rota. Nos
        # dois casos o caminho pelo jogo ainda existe. Um 404 com "no room" e
        # outra coisa: a sala nao existe, e abrir o jogo so adiaria o erro.
        if ("no starting save" in texto or "no usable starting save" in texto
                or "(404): Not Found" in texto):
            return None
        raise
    data = json.loads(raw)
    print(f"joined room {room}")
    print(f"  your ship:  {data['shipName']}")
    onde = data.get("placedAt") or {}
    if onde.get("system"):
        print(f"  placed in:  system {onde['system']}")
    print(f"  age:        {data['ageDays']} days")
    for aviso in data.get("warnings") or []:
        print(f"  note: {aviso}")
    print()
    print(f"  Play with: {prog()} play {room}")
    return 0


def cmd_delete_galaxy(args) -> int:
    """Apaga uma galaxia que voce criou. Nao ha desfazer.

    A confirmacao repete o nome, e nao um `sim`. Isto destroi o save de todo
    mundo que estava dentro, e um `sim` se digita por reflexo enquanto um nome
    exige ler o que esta prestes a sumir.
    """
    _s, raw, _h = request("GET", f"/api/v1/rooms/{args.galaxy}")
    galaxia = json.loads(raw)
    nome = galaxia.get("name") or args.galaxy
    pessoas = galaxia.get("players", "?")

    print(f"about to delete {nome} ({args.galaxy})")
    print(f"  {pessoas} player(s) are in it, and their saves go too")
    print("  there is no undo")
    if not args.yes:
        print()
        resposta = input(f'type the name to confirm ({nome}): ').strip()
        if resposta != nome:
            print("that is not the name. Nothing was deleted.")
            return 1

    _s, raw, _h = request(
        "DELETE",
        f"/api/v1/rooms/{args.galaxy}?confirm={urllib.parse.quote(nome)}")
    data = json.loads(raw)
    print()
    print(data["message"])
    livres = data.get("blobs") or {}
    if isinstance(livres, dict) and livres.get("removed"):
        print(f"  {livres['removed']} stored file(s) freed, "
              f"{_size(livres.get('freedBytes', 0))}")
    return 0


def cmd_checkout(args) -> int:
    running = game_is_running()
    if running:
        raise ClientError(
            f"Space Haven is open ({running}). Close it first: "
            f"writing to a save with the game running destroys the run")
    if shutil.which("pgrep") is None:
        print("warning: could not check whether the game is open (no `pgrep`).")
        print("         Make sure Space Haven is closed.")

    _s, data, headers = request("POST", f"/api/v1/rooms/{args.galaxy}/checkout")
    target = args.into or os.path.join(os.getcwd(), f"Sala-{args.galaxy}")
    final_dir = unpack(data, target)
    print(f"save checked out to {final_dir}")
    print(f"  due:  {_deadline(headers.get('x-lease-expires'))}")
    print(f"  {_size(len(data))}")
    print()
    print("  Play, then return it with:")
    print(f"    {prog()} return {args.galaxy} --save {target}")
    print("  Past the deadline, the session reverts to the state it was checked out in.")
    return 0


def _deadline(iso: str | None) -> str:
    """O deadline em hora local, mais quanto falta — que e o que a pessoa quer."""
    if not iso:
        return "?"
    import datetime as dt
    try:
        vence = dt.datetime.fromisoformat(iso)
    except ValueError:
        return iso
    falta = vence - dt.datetime.now(dt.timezone.utc)
    horas = falta.total_seconds() / 3600
    local = vence.astimezone().strftime("%d/%m %H:%M")
    if horas < 0:
        return f"{local} (expired {abs(horas):.1f}h ago)"
    return f"{local} ({horas:.1f}h left)"


def _size(n: int) -> str:
    """KB ate 1 MB. Um save novo tem 40 KB comprimido, e '0.0 MB' nao informa."""
    return f"{n / 1000:.0f} KB" if n < 1_000_000 else f"{n / 1_000_000:.1f} MB"


def _best_state(path: str) -> tuple:
    """A folder a devolver: o estado mais avancado, nao o mais obvio.

    Apontar para `save/` parece certo e e a armadilha: quem sai do jogo sem
    salvar na mao deixa o avanco no autosave, e `save/` fica no estado de
    quando a sessao comecou. Devolver isso manda o servidor para tras e apaga
    horas de jogo — visto acontecendo, com `save/` no age 1,29 e `autosave3` no
    2,79.

    Se o path apontar direto para uma folder de save, respeita: quem foi
    especifico sabe o que quer.
    """
    path = os.path.abspath(os.path.expanduser(path))
    if os.path.isfile(os.path.join(path, "game")):
        return path, None, -1.0
    try:
        return most_advanced(path)
    except ClientError:
        return resolve_save(path), None, -1.0


def cmd_return_save(args) -> int:
    running = game_is_running()
    if running:
        raise ClientError(
            f"Space Haven is open ({running}). Close it before returning: "
            f"the save may not be fully written yet")
    folder, which, age = _best_state(args.save)
    if which:
        print(f"returning {which} (age {age:.2f}) from {args.save} …")
    else:
        print(f"returning {folder} …")
    _s, raw, _h = request("POST", f"/api/v1/rooms/{args.galaxy}/checkin",
                          pack(folder), {"Content-Type": "application/zip"})
    data = json.loads(raw)
    print("returned")
    print(f"  age:     {data['ageDays']} days")
    print(f"  version: {data['versionId']}")
    if data.get("pruned"):
        print(f"  {data['pruned']} old version(s) fell out of the window")
    return 0


def accounts_elsewhere() -> list:
    """Servidores para os quais existe conta guardada, tirando o atual.

    A credencial é indexada por URL. Quando alguém troca de porta — um túnel
    que subiu noutro número, por exemplo — a conta continua lá, só que sob
    outra chave, e a mensagem "sem conta" sozinha parece perda de dados.
    """
    if not os.path.isfile(CREDENTIALS):
        return []
    try:
        with open(CREDENTIALS, "r", encoding="utf-8") as fh:
            todos = json.load(fh)
    except (OSError, ValueError):
        return []
    return [url for url, dados in todos.items()
            if url != base_url() and dados.get("token")]


def require_account() -> None:
    """Trava antes de qualquer coisa cara acontecer.

    Sem isto, o `play` descobria a falta de conta só na hora de subir o save —
    depois de a pessoa já ter confirmado o envio.
    """
    if load_credentials().get("token"):
        return
    linhas = [f"no account stored for {base_url()}."]
    outros = accounts_elsewhere()
    if outros:
        linhas.append("")
        linhas.append("You do have an account for:")
        for url in outros:
            linhas.append(f"    SGALAXY_URL={url}")
        linhas.append("")
        linhas.append("Set SGALAXY_URL to the right server, or register a new "
                      "account here:")
    else:
        linhas.append("Run:")
    linhas.append(f'    {prog()} register "Your Name"')
    raise ClientError("\n".join(linhas))


def is_member(room: str) -> bool:
    """Já entrei nesta sala?

    Pela lista de quem está na sala, e não por tentar e ver o erro: um 403 de
    `checkout` pode ser outra coisa, e tratar todo 403 como "ainda não entrou"
    faria o cliente subir um save por causa de um erro qualquer.

    E a mesma armadilha uma camada acima: a primeira versão disto capturava
    QUALQUER `ClientError` e devolvia False. Servidor fora do ar, conta em
    outro URL, sala inexistente — tudo virava "você ainda não entrou", e o
    cliente conduzia a pessoa até confirmar o envio do save para só então
    falhar. Aqui só existe uma resposta negativa: a lista veio e eu não estou
    nela.
    """
    require_account()
    data = json_request("GET", f"/api/v1/rooms/{room}/state")
    eu = load_credentials().get("playerId")
    return any(p["playerId"] == eu for p in data.get("players", []))


def savegame_root() -> str | None:
    exe = find_game()
    if not exe:
        return None
    raiz = os.path.join(os.path.dirname(exe), "savegames")
    return raiz if os.path.isdir(raiz) else None


def save_folders() -> set:
    """Os nomes de pasta de save que existem agora.

    Serve para descobrir por diferenca qual partida a pessoa acabou de criar. E
    mais confiavel que perguntar o nome: ela escolhe o nome no proprio jogo, e
    qualquer palpite nosso erraria acentuacao, espaco ou numero no fim.
    """
    raiz = savegame_root()
    if not raiz:
        return set()
    return {n for n in os.listdir(raiz)
            if os.path.isdir(os.path.join(raiz, n))}


def launch_and_wait(exe: str, marcador: str) -> None:
    """Abre o jogo com o bilhete armado e espera fechar."""
    game_dir = os.path.dirname(exe)
    arm_autoload(game_dir, marcador)
    try:
        subprocess.Popen([exe], cwd=game_dir).wait()
    except KeyboardInterrupt:
        print("\n      interrupted")
    except OSError as exc:
        raise ClientError(f"could not launch the game: {exc}") from exc


def create_ship(room: str, exe: str, sim: bool) -> str | None:
    """Faz a pessoa criar a nave dela, no proprio jogo, e devolve a pasta.

    POR QUE NAO APROVEITAR UM SAVE QUE JA EXISTE

    Aproveitar seria mais curto e foi o que esta funcao fazia antes. So que o
    enxerto preserva nave, tripulacao, banco e pesquisa de proposito — entao
    entrar com uma colonia de meio ano e chegar com meio ano de vantagem. Numa
    sala onde todo mundo comeca junto isso nao e um atalho, e uma injustica.

    Entao a nave nasce aqui: o jogo abre no criador de partida, a pessoa monta
    a nave dela, salva e fecha. Qual seed ela usar nao importa — o servidor
    troca a galaxia depois.

    A partida nova e achada por diferenca na pasta de savegames. Perguntar o
    nome erraria: quem escolhe e ela, dentro do jogo.
    """
    raiz = savegame_root()
    if not raiz:
        raise ClientError("could not find the game's savegames folder")

    print(f"you are not in room {room} yet — let's create your ship.")
    print()
    print("  The game will open on NEW GAME. Build your starting ship, save,")
    print("  and close the game. I take it from there.")
    print()
    print("  Any seed and any scenario option will do: the server replaces the")
    print("  galaxy with the room's. Your ship, crew and bank stay yours.")
    print()
    print("  Everyone in this room starts on a new game, so an old colony is")
    print("  not accepted here.")

    if not sim:
        print()
        try:
            resposta = input("  open the game now? [Y/n] ").strip().lower()
        except EOFError:
            resposta = ""
        if resposta in ("n", "no", "nao", "não"):
            print("  nothing happened.")
            return None

    antes = save_folders()
    print()
    print("[join 1/2] opening the game so you can create your ship …")
    if not mod_is_installed(os.path.dirname(exe)):
        print("      (no mod installed: pick NEW GAME in the menu yourself)")
    launch_and_wait(exe, AUTOLOAD_NEW_GAME)

    novas = sorted(save_folders() - antes)
    if not novas:
        print()
        print("no new game was created, so there is nothing to join with.")
        print("Run the same command again when you have created one.")
        return None
    if len(novas) > 1:
        print()
        print(f"you created more than one game ({', '.join(novas)}).")
        print("Join with the one you want:")
        for nome in novas:
            print(f"  {prog()} play {room} --join-with '{nome}'")
        return None

    pasta = os.path.join(raiz, novas[0], "save")
    if not os.path.isfile(os.path.join(pasta, "game")):
        pasta = os.path.join(raiz, novas[0])
    if not os.path.isfile(os.path.join(pasta, "game")):
        print(f"\n'{novas[0]}' has no savegame inside — did you save before "
              f"closing?")
        return None
    return pasta


def first_join(room: str, escolhido: str | None, sim: bool, senha: str,
               exe: str) -> bool:
    """A primeira entrada de alguem numa sala, dentro do `play`.

    Sobe a partida recem-criada; o servidor enxerta a galaxia da sala nela e
    devolve o resultado. Nave, tripulacao, banco e pesquisa continuam sendo da
    pessoa — so a galaxia muda.
    """
    if escolhido:
        # Escapatoria consciente: quem sabe o que esta fazendo aponta um save.
        # A sala ainda tem a ultima palavra pela idade, no servidor.
        pasta = resolve_save(escolhido)
    else:
        pasta = create_ship(room, exe, sim)
        if pasta is None:
            return False

    idade = age_of(pasta)
    print()
    print(f"[join 2/2] joining room {room} with "
          f"{os.path.basename(os.path.dirname(pasta))} (age {idade:.2f}) …")
    try:
        _s, raw, _h = request("POST", f"/api/v1/rooms/{room}/join", pack(pasta),
                              {"Content-Type": "application/zip",
                               "X-Room-Password": senha})
    except ClientError as exc:
        print(f"\nthe room did not accept it: {exc}", file=sys.stderr)
        print(f"\nYour game is safe in {pasta}; nothing there was changed.")
        return False
    data = json.loads(raw)
    if data.get("grafted"):
        print("      the room's galaxy was grafted into your save")
    print(f"      you are in. Ship {data['presence']['shipName']}, "
          f"age {data['ageDays']} days")
    return True


def _list_neighbour_ships(game_dir: str, sids: str | None) -> None:
    """Diz ao mod quais naves deste save foram montadas pelo servidor.

    Sem isto o mod não tem como separar a vitrine de um vizinho de uma nave
    NPC de verdade, porque o jogo só sabe chamar o jogador por FACÇÃO. Calar a
    facção calaria também os encontros que o próprio jogo criou.

    Escreve sempre, inclusive vazio: uma lista velha de outra sessão faria o
    mod calar naves que não são mais nossas.
    """
    alvo = os.path.join(game_dir, SHIPS_FILE)
    try:
        tmp = alvo + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write("\n".join((sids or "").split(",")) + "\n")
        os.replace(tmp, alvo)
    except OSError:
        pass


def _tell_mod_the_shop(game_dir: str, storage_id: str | None) -> None:
    """Diz ao mod qual armazém já é a loja, antes de o jogo abrir.

    É a metade que faltava. O arquivo é o canal nos DOIS sentidos: o servidor
    escreve aqui o que já vale, o botão mostra `SHOP: ON` no armazém certo, e
    se a pessoa mudar de ideia o mod reescreve e a devolução leva de volta.

    Sem isto o botão esqueceria, a cada sessão, o que foi escolhido na
    anterior — e mostraria `SET AS SHOP` num armazém que já é a loja.
    """
    alvo = os.path.join(game_dir, SHOP_FILE)
    try:
        tmp = alvo + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write((storage_id or "") + "\n")
        os.replace(tmp, alvo)
    except OSError:
        pass


def _apply_shop_choice(room: str, game_dir: str) -> None:
    """Leva ao servidor o armazém que a pessoa escolheu no painel do jogo.

    Não apaga o arquivo: quem manda nele é o próximo checkout, que o reescreve
    com o que o servidor tem. Apagar aqui era o que fazia o mod perder a
    memória entre sessões.

    Falhar não pode custar a devolução — a sessão vale mais que a escolha de
    loja, e ela se refaz com um clique.
    """
    caminho = os.path.join(game_dir, SHOP_FILE)
    if not os.path.isfile(caminho):
        return
    try:
        with open(caminho, encoding="utf-8") as fh:
            escolhido = fh.read().strip()
    except OSError:
        return
    try:
        data = json_request("PUT", f"/api/v1/rooms/{room}/shop",
                            {"storageId": escolhido or None})
        print(f"      {data['message']}")
    except ClientError as exc:
        print(f"      could not set your shop: {exc}", file=sys.stderr)


def _folder_state(pasta: str) -> tuple:
    """Assinatura barata de uma pasta de save: tamanhos e horários.

    Serve para saber se o jogo terminou de escrever. Ler um save no meio da
    gravação daria XML cortado, e o servidor recusaria — sem estragar nada, mas
    sem servir para nada.
    """
    estado = []
    for raiz, _dirs, arquivos in os.walk(pasta):
        for nome in sorted(arquivos):
            caminho = os.path.join(raiz, nome)
            try:
                st = os.stat(caminho)
            except OSError:
                continue
            estado.append((os.path.relpath(caminho, pasta), st.st_size,
                           int(st.st_mtime)))
    return tuple(estado)


def watch_autosaves(target: str, room: str, game_dir: str, parar) -> None:
    """Manda cada autosave para o servidor enquanto a pessoa joga.

    É a fase 1 do plano — o heartbeat — e o autosave já acontece, então isto só
    o aproveita. Vale por duas coisas: o mapa da sala anda durante a sessão em
    vez de só no fim, e uma queda de luz deixa de custar a sessão inteira.

    NÃO É A DEVOLUÇÃO. O servidor guarda como `checkpoint`: não mexe no
    canônico e não fecha o empréstimo. Quem decide o que fica é o `checkin`, e é
    isso que mantém a regra de uma sessão por vez.

    NUNCA ESCREVE. Só lê, e só depois que a pasta para de mudar — o jogo é dono
    daqueles arquivos enquanto estiver aberto.
    """
    vistos = {}
    while not parar.is_set():
        parar.wait(WATCH_EVERY)
        try:
            candidatos = [n for n in os.listdir(target)
                          if n.startswith("autosave")
                          and os.path.isfile(os.path.join(target, n, "game"))]
        except OSError:
            continue
        for nome in sorted(candidatos):
            pasta = os.path.join(target, nome)
            estado = _folder_state(pasta)
            if not estado or vistos.get(nome) == estado:
                continue
            # Mudou desde a última olhada: espera parar de mudar antes de ler.
            parar.wait(SETTLE_SECONDS)
            if _folder_state(pasta) != estado:
                continue        # ainda estava gravando; pega na próxima volta
            vistos[nome] = estado
            _send_checkpoint(pasta, nome, room, game_dir)


def _send_checkpoint(pasta: str, nome: str, room: str, game_dir: str) -> None:
    """Manda um autosave e conta nos dois lugares.

    No log do jogo, porque é onde a pessoa está olhando. E no terminal, porque
    é onde ela vai procurar depois se algo der errado — a primeira versão só
    escrevia no jogo, e quem estava de olho no console não via nada acontecer.
    """
    corpo = pack(pasta)
    try:
        _s, raw, _h = request("POST", f"/api/v1/rooms/{room}/checkpoint",
                              corpo, {"Content-Type": "application/zip"})
    except ClientError as exc:
        # Falhar aqui não pode atrapalhar quem está jogando: o save continua na
        # máquina e a devolução no fim da sessão é que vale.
        print(f"      {nome}: not sent ({exc})", flush=True)
        note_in_game(game_dir, [f"Shared Galaxy — {nome} NOT sent",
                                "Your progress is safe on this machine; the "
                                "return at the end is what counts."])
        return
    data = json.loads(raw)
    print(f"      {nome} sent — day {data['ageDays']}, "
          f"v{data['versionId']}, {_size(len(corpo))}", flush=True)
    # Sem o dia do jogo aqui. A janela de log já carimba cada linha com o
    # relógio dela, e o número que vem do save não bate com aquele carimbo —
    # dois dias diferentes na mesma linha só fazem duvidar da mensagem. O que
    # o jogador precisa saber é que o autosave saiu da máquina dele.
    note_in_game(game_dir, [f"Shared Galaxy — {nome} sent to the server"])


def cmd_play(args) -> int:
    """Retira, abre o jogo, espera, e devolve. Um comando para a sessao inteira.

    E o fluxo que a secao 2.4 descreve, sem o jogador precisar lembrar de
    nenhuma etapa. Como e o cliente que lanca o jogo e espera o processo
    terminar, ele sabe com certeza quando a sessao comecou e acabou — que e
    exatamente o que a secao 2.9 diz ser a razao de o cliente lancar o jogo.
    """
    running = game_is_running()
    if running:
        raise ClientError(f"Space Haven is already open ({running}). Close it "
                          f"first: I need to own the whole session")

    exe = args.game or find_game()
    if not exe or not os.path.isfile(exe):
        raise ClientError(
            "could not find the Space Haven executable. Pass --game PATH or "
            "set SPACEHAVEN_BIN")

    target = args.into or _room_folder(args.galaxy)

    # -- 0. entrar, se ainda nao entrou
    #
    # Antes do enxerto isto nao daria: a galaxia tinha que bater, e um save
    # qualquer nao batia. Agora o servidor conserta, entao a primeira sessao de
    # alguem cabe no mesmo comando que todas as outras.
    if not is_member(args.galaxy):
        # A SALA PRIMEIRO. Se ela tem um save de partida, entrar e um download,
        # e ninguem abre o jogo para criar nave nenhuma. So a primeira pessoa
        # de uma sala precisa do caminho longo, porque nao ha o que copiar.
        if _start_in_room(args.galaxy, args.password or "") is None:
            if not first_join(args.galaxy, args.join_with, args.yes,
                              args.password or "", exe):
                return 1

    # -- 1. retirar
    print(f"[1/4] checking out the save from room {args.galaxy} …")
    _s, data, headers = request("POST", f"/api/v1/rooms/{args.galaxy}/checkout")
    final_dir = unpack(data, target)
    deadline = headers.get("x-lease-expires")
    print(f"      {final_dir}  ({_size(len(data))})")
    print(f"      due: {_deadline(deadline)}")

    # -- 2. jogar
    folder_name = os.path.basename(target.rstrip("/"))
    game_dir = os.path.dirname(exe)
    armed = arm_autoload(game_dir, folder_name) and mod_is_installed(game_dir)

    _list_neighbour_ships(game_dir, headers.get("x-neighbour-sids"))
    _tell_mod_the_shop(game_dir, headers.get("x-shop-storage"))

    vendas = _sales_line(headers)
    if vendas:
        print(f"      {vendas}")

    versao = headers.get("x-version-id")
    servidor = base_url().split("//", 1)[-1]
    # Sobrescreve, nunca acrescenta: uma linha da sessão passada que o mod não
    # chegou a consumir apareceria no log da sessão nova, dizendo que um
    # autosave de ontem acabou de subir.
    note_in_game(game_dir, [
        f"Shared Galaxy — room {args.galaxy}, save v{versao or '?'}",
        f"{servidor} — due {_deadline(deadline)}",
    ] + ([vendas] if vendas else []) + [
        "Close the game when you are done and it goes back to the room.",
    ])

    if armed:
        print(f"[2/4] launching the game straight into '{folder_name}'.")
    else:
        print(f"[2/4] launching the game. Load the save named '{folder_name}'.")
        print("      (install mod/ to skip this step: "
              "python3 tools/install_mod.py)")
    print("      Each autosave is sent to the server while you play.")
    print("      When you close the game, I return it for you.")

    parar = threading.Event()
    vigia = threading.Thread(target=watch_autosaves,
                             args=(target, args.galaxy, game_dir, parar),
                             daemon=True)
    vigia.start()
    try:
        proc = subprocess.Popen([exe], cwd=game_dir)
        proc.wait()
    except KeyboardInterrupt:
        print("\n      interrupted; returning whatever is there")
    except OSError as exc:
        raise ClientError(f"could not launch the game: {exc}") from exc
    finally:
        parar.set()
        vigia.join(timeout=5)

    # -- 2b. a loja escolhida dentro do jogo
    _apply_shop_choice(args.galaxy, game_dir)

    # -- 3. escolher o estado mais avancado
    print("[3/4] finding the most advanced state …")
    folder, which, age = most_advanced(target)
    print(f"      {which} (age {age:.2f})")

    # -- 4. devolver
    print("[4/4] returning …")
    try:
        _s, raw, _h = request("POST", f"/api/v1/rooms/{args.galaxy}/checkin",
                              pack(folder), {"Content-Type": "application/zip"})
    except ClientError as exc:
        print(f"\nfailed to return: {exc}", file=sys.stderr)
        print(f"\nYour progress is NOT lost: it is in {folder}.")
        print("Once fixed, return it with:")
        print(f"  {prog()} return {args.galaxy} --save {folder}")
        return 1
    data = json.loads(raw)
    print(f"      age {data['ageDays']} days, version {data['versionId']}")
    print()
    print("session closed. The save is on the server.")
    return 0


AUTOLOAD_MARKER = "sharedgalaxy.autoload"

# Bilhete especial: em vez de um save, pede ao mod que abra o criador de
# partida. E o primeiro acesso de alguem a uma sala — a nave dela nasce ali.
AUTOLOAD_NEW_GAME = "__new__"

# Linhas que o mod põe na janela de log do jogo — a mesma que diz "Day 3.10
# Autosaved". Quem escreve o texto é o cliente: o mod não sabe o que é uma sala
# nem um servidor, e não tem por que saber.
NOTES_FILE = "sharedgalaxy.log"

# O botão do mod escreve aqui o armazém que virou a loja. Fica num arquivo
# nosso porque não pode ficar no save: o jogo regrava a partir do modelo dele e
# um atributo inventado por nós some no próximo salvamento.
SHOP_FILE = "sharedgalaxy.shop"

# As naves que o servidor montou neste save. O mod as usa para calar o chamado
# automatico das vitrines — o jogo so sabe chamar por facção, nunca por nave,
# então sem esta lista calar a nossa calaria também os NPCs de verdade.
SHIPS_FILE = "sharedgalaxy.ships"

# De quanto em quanto tempo olhar se apareceu autosave novo, e quanto esperar
# para ter certeza de que o jogo terminou de gravar.
WATCH_EVERY = 20
SETTLE_SECONDS = 3


def _sales_line(headers) -> str | None:
    """O que venderam por você enquanto esteve fora, se houve algo.

    A venda aconteceu na partida de outra pessoa, contra uma nave que o servidor
    montou. Este save já vem com os créditos dentro e com a carga fora do
    depósito — mas nada disso aparece na tela do jogo, e uma pessoa que não é
    avisada só percebe que vendeu quando dá falta do estoque.
    """
    try:
        quantos = int(headers.get("x-sales-paid") or 0)
        creditos = int(headers.get("x-sales-credits") or 0)
    except (TypeError, ValueError):
        return None
    if quantos <= 0:
        return None
    return (f"sold while you were away: {quantos} "
            f"transaction{'s' if quantos != 1 else ''}, "
            f"{creditos} credits already in your bank")


def mod_is_installed(game_dir: str) -> bool:
    """O mod está armado nesta instalação?

    Lê o `config.json` que o lançador do jogo consome. Não é adivinhação: o mod
    só roda se houver um `-javaagent` do aspectjweaver e o jar no `classPath`,
    que é exatamente o que `tools/install_mod.py` escreve.
    """
    caminho = os.path.join(game_dir, "config.json")
    try:
        with open(caminho, encoding="utf-8") as fh:
            config = json.load(fh)
    except (OSError, ValueError):
        return False
    tem_agente = any(str(a).startswith("-javaagent:./aspectjweaver")
                     for a in (config.get("vmArgs") or []))
    tem_mod = any(os.path.basename(str(c)) == "SharedGalaxy.jar"
                  for c in (config.get("classPath") or []))
    return tem_agente and tem_mod


def note_in_game(game_dir: str, linhas: list) -> bool:
    """Deixa para o mod as linhas que vão aparecer no log do jogo.

    Serve para a pessoa não se perguntar, no meio da sessão, se está jogando o
    save da sala ou uma partida local — é a confusão que faz alguém devolver a
    partida errada.
    """
    alvo = os.path.join(game_dir, NOTES_FILE)
    try:
        # Grava num temporário e renomeia: o mod olha esse arquivo a cada meio
        # segundo, e ler um arquivo pela metade mostraria linha cortada.
        tmp = alvo + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write("\n".join(linhas) + "\n")
        os.replace(tmp, alvo)
        return True
    except OSError:
        return False


def arm_autoload(game_dir: str, folder_name: str) -> bool:
    """Deixa o bilhete que diz ao mod qual save abrir.

    O mod lê e apaga. Se ele não estiver instalado o arquivo fica lá sem efeito,
    então isto é escrito sempre — não custa nada e evita um estado a mais.
    """
    try:
        with open(os.path.join(game_dir, AUTOLOAD_MARKER), "w",
                  encoding="utf-8") as fh:
            fh.write(folder_name + "\n")
        return True
    except OSError:
        return False


def _room_folder(room: str) -> str:
    """Onde a pasta da galaxia mora, ao lado das outras partidas do jogo."""
    exe = find_game()
    if exe:
        saves = os.path.join(os.path.dirname(exe), "savegames")
        if os.path.isdir(saves):
            return os.path.join(saves, f"Sala-{room}")
    return os.path.join(os.getcwd(), f"Sala-{room}")


def cmd_install_mod(args) -> int:
    """Instala (ou remove) o mod que abre o jogo direto no save da sala.

    Vive aqui para o jogador ter um programa só. A lógica continua em
    `tools/install_mod.py`, que roda sozinho para quem preferir.
    """
    import install_mod

    try:
        jogo = args.game or install_mod.find_game()
        if args.status:
            return install_mod.status(jogo)
        if args.uninstall:
            return install_mod.uninstall(jogo, args.dry_run)
        return install_mod.install(jogo, args.dry_run)
    except install_mod.ModError as erro:
        raise ClientError(str(erro)) from erro


def cmd_shop(args) -> int:
    """Escolhe de qual armazém da tua nave os vizinhos podem comprar.

    Sem argumento, lista os armazéns. Com `--set`, escolhe. Com `--close`,
    fecha a loja.

    Depois de escolhido, a loja se administra dentro do jogo: o que você mover
    para aquele armazém está à venda, o que tirar sai. Não há catálogo aqui de
    propósito — arrastar carga é uma mecânica que você já conhece, e o que está
    fisicamente lá é a única promessa que dá para cumprir.
    """
    if args.close:
        data = json_request("PUT", f"/api/v1/rooms/{args.galaxy}/shop",
                            {"storageId": None})
        print(data["message"])
        return 0
    if args.set:
        data = json_request("PUT", f"/api/v1/rooms/{args.galaxy}/shop",
                            {"storageId": args.set})
        print(data["message"])
        return 0

    data = json_request("GET", f"/api/v1/rooms/{args.galaxy}/shop")
    if not data["storages"]:
        print("no storage found on your ship in the save the server has.")
        return 1
    print(f"{'':2}{'storage':<10}{'where':<12}{'stacks':>7}{'units':>7}")
    for a in data["storages"]:
        marca = "->" if a["isShop"] else "  "
        onde = f"({a['at'][0]},{a['at'][1]})"
        print(f"{marca}{a['id']:<10}{onde:<12}{a['stacks']:>7}{a['units']:>7}")
    print()
    # O jogo nunca mostra estes ids, então a coluna que casa é `units`: o
    # painel do armazém, no jogo, diz "Capacity: 153 / 250" — e 153 é o mesmo
    # número. Sem esta linha, os ids são três números sem sentido.
    print("  In the game, click a storage: the panel shows "
          "\"Capacity: N / total\".")
    print("  That N is the `units` column above — that is how you tell "
          "them apart.")
    print()
    print(f"  {data['message']}")
    if not data["shopStorageId"]:
        print(f"  {prog()} shop {args.galaxy} --set STORAGE")
    return 0


def cmd_status(args) -> int:
    """What is open, before you launch the wrong save by accident."""
    data = json_request("GET", f"/api/v1/rooms/{args.galaxy}/state")
    eu = load_credentials().get("playerId")
    mine = next((p for p in data["players"] if p["playerId"] == eu), None)
    if mine is None:
        print(f"you are not in room {args.galaxy}")
        return 1
    print(f"room {args.galaxy}")
    print(f"  your ship:   {mine['shipName'] or '—'}")
    print(f"  age on server: {mine['ageDays'] or '—'} days")
    print(f"  lease:       {'OPEN' if mine['playing'] else 'closed'}")

    folder = _room_folder(args.galaxy)
    if not os.path.isdir(folder):
        print(f"  local folder: none ({folder})")
        return 0
    try:
        _p, which, age = most_advanced(folder)
    except ClientError:
        print(f"  local folder: {folder} (no savegame inside)")
        return 0
    print(f"  local folder: {folder}")
    print(f"                most advanced: {which}, age {age:.2f} days")
    if not mine["playing"]:
        on_server = mine["ageDays"] or 0
        if age > on_server + 0.01:
            print()
            print("  WARNING: the local folder is AHEAD of the server and no lease")
            print("  is open. That means you played without checking out. A new")
            print("  checkout will overwrite that progress.")
            print("  It cannot be handed in: the room only accepts what came out")
            print("  of a lease. Copy the folder aside first if you want to keep")
            print("  it outside the room.")
    return 0


def cmd_state(args) -> int:
    data = json_request("GET", f"/api/v1/rooms/{args.galaxy}/state")
    if not data["players"]:
        print("empty room")
        return 0
    print(f"{'player':<18}{'ship':<24}{'system':<10}{'body':<18}{'age':<8}where")
    for p in data["players"]:
        print(f"{(p['name'] or '?'):<18}{(p['shipName'] or '—'):<24}"
              f"{(p['system'] or '—'):<10}{(p['body'] or '—'):<18}"
              f"{str(p['ageDays'] or '—'):<8}"
              f"{'playing' if p['playing'] else 'away'}")
    return 0


def cmd_delete_account(args) -> int:
    print("This deletes your account and ALL your saves on this server.")
    print("There is no undo.")
    if input("Type 'delete everything' to confirm: ").strip() != "delete everything":
        print("cancelled")
        return 1
    data = json_request("DELETE", "/api/v1/me?confirm=delete%20everything")
    print(data["message"])
    if os.path.isfile(CREDENTIALS):
        todos = json.load(open(CREDENTIALS, encoding="utf-8"))
        todos.pop(base_url(), None)
        with open(CREDENTIALS, "w", encoding="utf-8") as fh:
            json.dump(todos, fh, indent=2, ensure_ascii=False)
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    """Os comandos, separados de `main` para poderem ser conferidos.

    Um `required=True` num argumento e uma decisao de produto escondida numa
    linha de configuracao: foi assim que `join --save` passou a exigir um save
    de quem ainda nao tinha nenhum, e ninguem notou porque nao havia como
    testar o parser sem rodar o programa.
    """
    ap = argparse.ArgumentParser(
        description="Shared Galaxy client",
        epilog=f"sgalaxy {VERSION} · server: {base_url()} "
               f"(change with SGALAXY_URL)")
    ap.add_argument("--version", action="version",
                    version=f"sgalaxy {VERSION}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("register", help="create an account on this server")
    p.add_argument("name", nargs="?")
    p.add_argument("--recover", metavar="CODE",
                   help="use the recovery code from the website instead of "
                        "creating a new account")
    p.add_argument("--invite", help="if the server requires one")
    p.set_defaults(func=cmd_register)

    p = sub.add_parser("galaxies", help="list open galaxies")
    p.set_defaults(func=cmd_rooms)

    p = sub.add_parser("create-galaxy", help="create a galaxy")
    # Os tres sao obrigatorios de proposito. A seed e a galaxia; sem nome
    # ninguem reconhece a sua na listagem; e o teto de gente decide se o
    # convite cabe, e descobrir que nao cabe quando a 33a pessoa chega e tarde
    # demais para mudar.
    p.add_argument("--seed", required=True, help="the galaxy seed")
    p.add_argument("--name", required=True,
                   help="how people will recognise it in the listing")
    p.add_argument("--max-players", type=int, required=True,
                   help="how many people it opens to")
    p.add_argument("--password")
    p.add_argument("--lease-hours", type=int, default=12,
                   help="how long a session may stay checked out")
    p.add_argument("--ship", help="starting ship everyone must pick")
    p.add_argument("--difficulty")
    p.add_argument("--option", action="append", metavar="KEY=VALUE",
                   help="scenario option; repeatable")
    p.set_defaults(func=cmd_create_room)

    p = sub.add_parser("configure-galaxy",
                       help="publish or fix the galaxy recipe")
    p.add_argument("galaxy", metavar="GALAXY")
    p.add_argument("--ship", help="starting ship everyone must pick")
    p.add_argument("--difficulty")
    p.add_argument("--option", action="append", metavar="KEY=VALUE",
                   help="scenario option; repeatable")
    p.add_argument("--name")
    p.add_argument("--lease-hours", type=int)
    p.add_argument("--password", help="if the room has one")
    p.add_argument("--replace", action="store_true",
                   help="replace the whole recipe instead of merging into it")
    p.set_defaults(func=cmd_configure_room)

    p = sub.add_parser("how-to-join",
                       help="the recipe for reproducing this galaxy")
    p.add_argument("galaxy", metavar="GALAXY")
    p.add_argument("--password")
    p.set_defaults(func=cmd_how_to_join)

    # `join` e `play` sao o mesmo comando. Entrar sem jogar nao serve para
    # nada, e jogar exige ter entrado: eram duas metades de uma acao so, e a
    # ordem entre elas era uma coisa a mais para alguem descobrir sozinho.
    for nome, ajuda in (("join", "join the galaxy and play"),
                        ("play", "same as join: check out, play, return")):
        p = sub.add_parser(nome, help=ajuda)
        p.add_argument("galaxy", metavar="GALAXY")
        p.add_argument("--into", help="folder for the galaxy (default: next to the game)")
        p.add_argument("--game", help="path to the Space Haven executable")
        p.add_argument("--join-with", "--save", dest="join_with",
                       help="a game you already have to join with, the first "
                            "time (default: the room's starting save)")
        p.add_argument("--password", help="galaxy password, if it has one")
        p.add_argument("-y", "--yes", action="store_true",
                       help="do not ask before uploading the save to join")
        p.set_defaults(func=cmd_join)

    p = sub.add_parser("checkout", help="check the save out to play")
    p.add_argument("galaxy", metavar="GALAXY")
    p.add_argument("--into", help="destination folder")
    p.set_defaults(func=cmd_checkout)

    p = sub.add_parser("return", help="return the save after playing")
    p.add_argument("galaxy", metavar="GALAXY")
    p.add_argument("--save", required=True)
    p.set_defaults(func=cmd_return_save)


    p = sub.add_parser("install-mod",
                       help="install the mod into your copy of the game")
    p.add_argument("--game", help="the game folder (found on its own by default)")
    p.add_argument("--dry-run", action="store_true",
                   help="show what it would change, without writing")
    p.add_argument("--uninstall", action="store_true", help="undo it")
    p.add_argument("--status", action="store_true", help="just report")
    p.set_defaults(func=cmd_install_mod)

    p = sub.add_parser("shop",
                       help="pick which storage your neighbours can buy from")
    p.add_argument("galaxy", metavar="GALAXY")
    p.add_argument("--set", metavar="STORAGE", help="make this storage the shop")
    p.add_argument("--close", action="store_true", help="stop selling")
    p.set_defaults(func=cmd_shop)

    p = sub.add_parser("status",
                       help="what is open, before you launch the game")
    p.add_argument("galaxy", metavar="GALAXY")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("state", help="who is where in the galaxy")
    p.add_argument("galaxy", metavar="GALAXY")
    p.set_defaults(func=cmd_state)

    p = sub.add_parser("delete-galaxy",
                       help="delete a galaxy you created, no undo")
    p.add_argument("galaxy", metavar="GALAXY")
    p.add_argument("-y", "--yes", action="store_true",
                   help="do not ask before deleting")
    p.set_defaults(func=cmd_delete_galaxy)

    p = sub.add_parser("delete-account", help="delete account and saves, no undo")
    p.set_defaults(func=cmd_delete_account)

    return ap


def main() -> int:
    args = build_parser().parse_args()
    try:
        return args.func(args)
    except ClientError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
