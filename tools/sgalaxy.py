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

    python3 tools/sgalaxy.py register "My Name"
    python3 tools/sgalaxy.py rooms
    python3 tools/sgalaxy.py create-room --seed 1654267488 --name "Frontier"
    python3 tools/sgalaxy.py how-to-join ROOM
    python3 tools/sgalaxy.py join ROOM --save ~/.../savegames/MyGame
    python3 tools/sgalaxy.py play ROOM          # the whole session, one command
    python3 tools/sgalaxy.py status ROOM
    python3 tools/sgalaxy.py delete-account

The token lives in `~/.config/sgalaxy/credentials.json`, mode 600. It is the
only credential there is: losing it means losing the account, and there is no
recovery email.

THE RULE THAT IS NOT NEGOTIABLE: never write to a save while the game is open.
The game rewrites the file when it saves, and writing underneath it destroys
someone's run. `checkout`, `return` and `play` detect the process and refuse.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile

CONFIG_DIR = os.path.expanduser("~/.config/sgalaxy")
CREDENTIALS = os.path.join(CONFIG_DIR, "credentials.json")
DEFAULT_URL = "http://127.0.0.1:8714"

# Como o jogo aparece na tabela de processos. Duas formas:
#
# `spacehaven` e o launcher nativo, e o nome do EXECUTAVEL — casado com `-x`,
# que compara so o nome do programa. `spacehaven.jar` e a JVM que ele levanta, e
# so aparece na linha de comando, entao esse precisa de `-f`.
#
# A primeira versao usava `-f` com "SpaceHaven" solto, e casava demais: qualquer
# processo do Steam que mencionasse o caminho da instalacao — e ate o proprio
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
            f"Run: python3 tools/sgalaxy.py register \"Your Name\"")
    return creds["token"]


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def request(method: str, path: str, body: bytes | None = None,
            headers: dict | None = None, auth: bool = True) -> tuple:
    """Devolve (status, corpo, headers). Erro do servidor vira ClientError."""
    url = f"{base_url()}{path}"
    head = dict(headers or {})
    if auth:
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
        raise ClientError(f"the server refused ({exc.code}): {detail}") from exc
    except urllib.error.URLError as exc:
        raise ClientError(f"could not reach {base_url()}: {exc.reason}") from exc


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
    """O nome do processo do jogo, se ele estiver running.

    A regra mais importante do cliente (secao 2.9): nunca escrever num save com
    o jogo running. Sem `pgrep`, devolve None e o chamador avisa que nao
    conseguiu conferir — nunca assume que esta fechado.
    """
    if shutil.which("pgrep") is None:
        return None

    proprio = {str(os.getpid()), str(os.getppid())}

    def encontrou(args: list) -> bool:
        try:
            out = subprocess.run(["pgrep", *args], capture_output=True,
                                 timeout=5, text=True)
        except (subprocess.SubprocessError, OSError):
            return False
        if out.returncode != 0:
            return False
        pids = {p for p in out.stdout.split() if p and p not in proprio}
        return bool(pids)

    for nome in GAME_EXECUTABLES:
        if encontrou(["-x", nome]):
            return nome
    for padrao in GAME_COMMANDLINES:
        if encontrou(["-f", padrao]):
            return padrao
    return None


def find_game() -> str | None:
    """O executavel do jogo, se der para achar sozinho.

    O launcher e um binario nativo que le `config.json` e levanta a JVM — nao
    precisa do Steam para rodar. Achar sozinho e o que permite o fluxo unico:
    sem isso, o jogador teria que dizer o caminho toda vez.
    """
    if os.environ.get("SPACEHAVEN_BIN"):
        return os.environ["SPACEHAVEN_BIN"]
    candidatos = [
        "~/snap/steam/common/.local/share/Steam/steamapps/common/SpaceHaven",
        "~/.steam/steam/steamapps/common/SpaceHaven",
        "~/.local/share/Steam/steamapps/common/SpaceHaven",
        "/usr/share/spacehaven",
    ]
    for base in candidatos:
        exe = os.path.join(os.path.expanduser(base), "spacehaven")
        if os.path.isfile(exe) and os.access(exe, os.X_OK):
            return exe
    return None


def age_of(folder: str) -> float:
    """O idade de uma folder de save, ou -1 se nao der para ler."""
    import xml.etree.ElementTree as ET
    caminho = os.path.join(folder, "info")
    try:
        with open(caminho, "rb") as fh:
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
    for nome in sorted(os.listdir(room_folder)):
        caminho = os.path.join(room_folder, nome)
        if os.path.isfile(os.path.join(caminho, "game")):
            candidatos.append((age_of(caminho), nome, caminho))
    if not candidatos:
        raise ClientError(f"no savegame found inside {room_folder}")
    candidatos.sort(reverse=True)
    dia, nome, caminho = candidatos[0]
    return caminho, nome, dia


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
        for raiz, _d, arquivos in os.walk(temp):
            if "game" in arquivos:
                save_dir = raiz
                break
    if save_dir is None:
        shutil.rmtree(temp, ignore_errors=True)
        raise ClientError("the server sent something that is not a savegame")

    final = os.path.join(dest, "save")
    antigo = dest + ".anterior"
    shutil.rmtree(antigo, ignore_errors=True)
    if os.path.exists(dest):
        os.replace(dest, antigo)
    os.makedirs(dest, exist_ok=True)
    shutil.move(save_dir, final)
    shutil.rmtree(temp, ignore_errors=True)

    # O Steam Cloud sincroniza `savegames/<Nome>/cloudZipFile.zip`, e so isso —
    # medido no remotecache.vdf do jogo. O `save/` e local; o zip e a copia da
    # nuvem, e o jogo o refaz ao gravar.
    #
    # Um zip velho ao lado de um save recem-retirado e a combinacao perigosa: se
    # o Steam resolver restaurar, ele sobrescreve a sessao que o servidor
    # emprestou com uma partida antiga, e o jogador perde o progresso sem
    # entender por que. Entao o zip anterior sai daqui.
    for lixo in ("cloudZipFile.zip", "cloud.xml"):
        caminho = os.path.join(dest, lixo)
        if os.path.exists(caminho):
            os.unlink(caminho)
    return final


# ---------------------------------------------------------------------------
# Comandos
# ---------------------------------------------------------------------------

def cmd_register(args) -> int:
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
        print("no open rooms")
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
    print(f"room {data['id']} criada")
    print(f"  seed:  {data['seed']}")
    print(f"  deadline: {data['leaseHours']}h")
    print()
    print(f"  Publique a recipe para quem for entrar:")
    print(f"    python3 tools/sgalaxy.py como-entrar {data['id']}")
    if not _recipe(args):
        print()
        print("  A recipe está vazia. Depois de criar a partida no jogo,")
        print("  and the options you picked:")
        print(f"    python3 tools/sgalaxy.py configurar-room {data['id']} \\")
        print(f"        --nave \"Nome da nave inicial\" --dificuldade Normal")
    return 0


def _recipe(args) -> dict:
    """O que alguem precisa reproduzir para o save ser aceito na room."""
    recipe = {}
    if getattr(args, "ship", None):
        recipe["ship"] = args.ship
    if getattr(args, "difficulty", None):
        recipe["difficulty"] = args.difficulty
    for item in getattr(args, "option", None) or []:
        if "=" not in item:
            raise ClientError(f"--opcao espera chave=valor, veio {item!r}")
        chave, valor = item.split("=", 1)
        recipe[chave.strip()] = valor.strip()
    return recipe


def cmd_configure_room(args) -> int:
    payload = {}
    recipe = _recipe(args)
    if recipe:
        atual = json_request("GET", f"/api/v1/rooms/{args.room}")
        payload["options"] = {**(atual.get("options") or {}), **recipe}
    if args.name:
        payload["name"] = args.name
    if args.lease_hours:
        payload["leaseHours"] = args.lease_hours
    if not payload:
        raise ClientError("nada para mudar. Use --nave, --dificuldade, "
                          "--opcao chave=valor, --nome ou --deadline")
    json_request("PATCH", f"/api/v1/rooms/{args.room}", payload)
    print(f"room {args.room} updated")
    return cmd_how_to_join(args)


def cmd_how_to_join(args) -> int:
    """The recipe, laid out the way the creation screen asks for it."""
    head = {"X-Room-Password": getattr(args, "senha", None) or ""}
    _s, raw, _h = request("GET", f"/api/v1/rooms/{args.room}", None, head)
    room = json.loads(raw)
    if "seed" not in room:
        raise ClientError("esta room tem senha; passe --senha para ver a recipe")

    print(f"To join room {room['id']} ({room['name']}):")
    print()
    print("  1. In Space Haven, create a new game with:")
    print(f"       seed: {room['seed']}")
    recipe = room.get("options") or {}
    if recipe.get("ship"):
        print(f"       nave inicial: {recipe['nave']}")
    if recipe.get("difficulty"):
        print(f"       dificuldade: {recipe['dificuldade']}")
    outras = {k: v for k, v in recipe.items()
              if k not in ("ship", "difficulty")}
    for chave, valor in sorted(outras.items()):
        print(f"       {chave}: {valor}")
    if not recipe:
        print("       (the room owner has not published the scenario options yet)")
    print()
    print("  2. Save the game and close it.")
    print()
    print("  3. Upload the save:")
    print(f"       python3 tools/sgalaxy.py entrar {room['id']} \\")
    print(f"           --save CAMINHO/DA/PARTIDA")
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
    folder = resolve_save(args.save)
    print(f"subindo {folder} …")
    _s, raw, _h = request("POST", f"/api/v1/rooms/{args.room}/join",
                          pack(folder),
                          {"Content-Type": "application/zip",
                           "X-Room-Password": args.password or ""})
    data = json.loads(raw)
    galaxia = data["galaxy"]
    print(f"joined room {args.room}")
    print(f"  galáxia:    {galaxia['digest']} "
          f"({galaxia['systems']} sistemas, {galaxia['bodies']} corpos)")
    print(f"  age:     {data['ageDays']} days")
    print(f"  sua nave:    {data['presence']['shipName']}")
    print()
    print("  The server owns this save now. Use `play` to start a session.")
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

    _s, data, headers = request("POST", f"/api/v1/rooms/{args.room}/checkout")
    destino = args.into or os.path.join(os.getcwd(), f"Sala-{args.room}")
    final = unpack(data, destino)
    print(f"save checked out to {final}")
    print(f"  due:  {_deadline(headers.get('x-lease-expires'))}")
    print(f"  {_size(len(data))}")
    print()
    print("  Play, then return it with:")
    print(f"    python3 tools/sgalaxy.py devolver {args.room} --save {destino}")
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
    return f"{local} (faltam {horas:.1f}h)"


def _size(n: int) -> str:
    """KB ate 1 MB. Um save novo tem 40 KB comprimido, e '0.0 MB' nao informa."""
    return f"{n / 1000:.0f} KB" if n < 1_000_000 else f"{n / 1_000_000:.1f} MB"


def _best_state(caminho: str) -> tuple:
    """A folder a devolver: o estado mais avancado, nao o mais obvio.

    Apontar para `save/` parece certo e e a armadilha: quem sai do jogo sem
    salvar na mao deixa o avanco no autosave, e `save/` fica no estado de
    quando a sessao comecou. Devolver isso manda o servidor para tras e apaga
    horas de jogo — visto acontecendo, com `save/` no dia 1,29 e `autosave3` no
    2,79.

    Se o caminho apontar direto para uma folder de save, respeita: quem foi
    especifico sabe o que quer.
    """
    caminho = os.path.abspath(os.path.expanduser(caminho))
    if os.path.isfile(os.path.join(caminho, "game")):
        return caminho, None, -1.0
    try:
        return most_advanced(caminho)
    except ClientError:
        return resolve_save(caminho), None, -1.0


def cmd_return_save(args) -> int:
    running = game_is_running()
    if running:
        raise ClientError(
            f"Space Haven is open ({running}). Close it before returning: "
            f"the save may not be fully written yet")
    folder, which, dia = _best_state(args.save)
    if which:
        print(f"devolvendo {which} (dia {dia:.2f}) de {args.save} …")
    else:
        print(f"returning {folder} …")
    _s, raw, _h = request("POST", f"/api/v1/rooms/{args.room}/checkin",
                          pack(folder), {"Content-Type": "application/zip"})
    data = json.loads(raw)
    print("returned")
    print(f"  age:     {data['ageDays']} days")
    print(f"  version: {data['versionId']}")
    if data.get("pruned"):
        print(f"  {data['pruned']} old version(s) fell out of the window")
    return 0


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

    destino = args.into or _room_folder(args.room)

    # -- 1. retirar
    print(f"[1/4] checking out the save from room {args.room} …")
    _s, data, headers = request("POST", f"/api/v1/rooms/{args.room}/checkout")
    final = unpack(data, destino)
    deadline = headers.get("x-lease-expires")
    print(f"      {final}  ({_size(len(data))})")
    print(f"      due: {_deadline(deadline)}")

    # -- 2. jogar
    folder_name = os.path.basename(destino.rstrip("/"))
    print(f"[2/4] launching the game. Load the save named '{folder_name}'.")
    print("      When you close the game, I return it for you.")
    try:
        proc = subprocess.Popen([exe], cwd=os.path.dirname(exe))
        proc.wait()
    except KeyboardInterrupt:
        print("\n      interrupted; returning whatever is there")
    except OSError as exc:
        raise ClientError(f"could not launch the game: {exc}") from exc

    # -- 3. escolher o estado mais avancado
    print("[3/4] finding the most advanced state …")
    folder, which, dia = most_advanced(destino)
    print(f"      {which} (dia {dia:.2f})")

    # -- 4. devolver
    print("[4/4] returning …")
    try:
        _s, raw, _h = request("POST", f"/api/v1/rooms/{args.room}/checkin",
                              pack(folder), {"Content-Type": "application/zip"})
    except ClientError as exc:
        print(f"\nfailed to return: {exc}", file=sys.stderr)
        print(f"\nYour progress is NOT lost: it is in {folder}.")
        print("Once fixed, return it with:")
        print(f"  python3 tools/sgalaxy.py devolver {args.room} --save {folder}")
        return 1
    data = json.loads(raw)
    print(f"      age {data['ageDays']} days, version {data['versionId']}")
    print()
    print("session closed. The save is on the server.")
    return 0


def _room_folder(room: str) -> str:
    """Onde a folder da room mora, ao lado das outras partidas do jogo."""
    exe = find_game()
    if exe:
        saves = os.path.join(os.path.dirname(exe), "savegames")
        if os.path.isdir(saves):
            return os.path.join(saves, f"Sala-{room}")
    return os.path.join(os.getcwd(), f"Sala-{room}")


def cmd_status(args) -> int:
    """What is open, before you launch the wrong save by accident."""
    data = json_request("GET", f"/api/v1/rooms/{args.room}/state")
    eu = load_credentials().get("playerId")
    mine = next((p for p in data["players"] if p["playerId"] == eu), None)
    if mine is None:
        print(f"you are not in room {args.room}")
        return 1
    print(f"room {args.room}")
    print(f"  your ship:   {mine['shipName'] or '—'}")
    print(f"  age on server: {mine['ageDays'] or '—'} days")
    print(f"  lease:       {'OPEN' if mine['playing'] else 'closed'}")

    folder = _room_folder(args.room)
    if not os.path.isdir(folder):
        print(f"  local folder: none ({folder})")
        return 0
    try:
        _p, which, dia = most_advanced(folder)
    except ClientError:
        print(f"  local folder: {folder} (no savegame inside)")
        return 0
    print(f"  local folder: {folder}")
    print(f"                most advanced: {which}, age {age:.2f} days")
    if not mine["playing"]:
        servidor = mine["ageDays"] or 0
        if dia > servidor + 0.01:
            print()
            print("  WARNING: the local folder is AHEAD of the server and no lease")
            print("  is open. That means you played without checking out. A new")
            print("  checkout will overwrite that progress.")
            print("  It cannot be handed in: the room only accepts what came out")
            print("  of a lease. Copy the folder aside first if you want to keep")
            print("  it outside the room.")
    return 0


def cmd_state(args) -> int:
    data = json_request("GET", f"/api/v1/rooms/{args.room}/state")
    if not data["players"]:
        print("empty room")
        return 0
    print(f"{'player':<18}{'ship':<24}{'system':<10}{'body':<8}{'age':<8}where")
    for p in data["players"]:
        print(f"{(p['name'] or '?'):<18}{(p['shipName'] or '—'):<24}"
              f"{(p['system'] or '—'):<10}{(p['celeid'] or '—'):<8}"
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

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Shared Galaxy client",
        epilog=f"server: {base_url()} (change with SGALAXY_URL)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("register", help="create an account on this server")
    p.add_argument("nome")
    p.add_argument("--invite", help="if the server requires one")
    p.set_defaults(func=cmd_register)

    p = sub.add_parser("rooms", help="list open rooms")
    p.set_defaults(func=cmd_rooms)

    p = sub.add_parser("create-room", help="create a room")
    p.add_argument("--seed", required=True, help="the galaxy seed")
    p.add_argument("--name", default="")
    p.add_argument("--password")
    p.add_argument("--lease-hours", type=int, default=12, help="lease hours")
    p.add_argument("--max-players", type=int, default=8)
    p.add_argument("--ship", help="starting ship everyone must pick")
    p.add_argument("--difficulty")
    p.add_argument("--option", action="append", metavar="CHAVE=VALOR",
                   help="scenario option; repeatable")
    p.set_defaults(func=cmd_create_room)

    p = sub.add_parser("configure-room",
                       help="publish or fix the room recipe")
    p.add_argument("room")
    p.add_argument("--ship", help="starting ship everyone must pick")
    p.add_argument("--difficulty")
    p.add_argument("--option", action="append", metavar="CHAVE=VALOR",
                   help="scenario option; repeatable")
    p.add_argument("--name")
    p.add_argument("--lease-hours", type=int)
    p.add_argument("--password", help="if the room has one")
    p.set_defaults(func=cmd_configure_room)

    p = sub.add_parser("how-to-join",
                       help="the recipe for reproducing the room's galaxy")
    p.add_argument("room")
    p.add_argument("--password")
    p.set_defaults(func=cmd_how_to_join)

    p = sub.add_parser("join", help="upload your first save and join a room")
    p.add_argument("room")
    p.add_argument("--save", required=True, help="savegame folder")
    p.add_argument("--password")
    p.set_defaults(func=cmd_join)

    p = sub.add_parser("checkout", help="check the save out to play")
    p.add_argument("room")
    p.add_argument("--into", help="destination folder")
    p.set_defaults(func=cmd_checkout)

    p = sub.add_parser("return", help="return the save after playing")
    p.add_argument("room")
    p.add_argument("--save", required=True)
    p.set_defaults(func=cmd_return_save)

    p = sub.add_parser("play",
                       help="checkout, launch the game, return when it closes")
    p.add_argument("room")
    p.add_argument("--into", help="room folder (default: next to the game)")
    p.add_argument("--game", help="path to the Space Haven executable")
    p.set_defaults(func=cmd_play)

    p = sub.add_parser("status",
                       help="what is open, before you launch the game")
    p.add_argument("room")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("state", help="who is where in the room")
    p.add_argument("room")
    p.set_defaults(func=cmd_state)

    p = sub.add_parser("delete-account", help="delete account and saves, no undo")
    p.set_defaults(func=cmd_delete_account)

    args = ap.parse_args()
    try:
        return args.func(args)
    except ClientError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
