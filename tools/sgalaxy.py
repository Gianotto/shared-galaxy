#!/usr/bin/env python3
"""
Cliente de linha de comando da Galaxia Compartilhada.

Faz o ciclo da secao 2.4 pelo terminal: cria conta, entra numa sala, retira o
save, e devolve depois de jogar. E o esqueleto do que vira uma aba no editor de
savegame (etapa C do plano) — a logica de ciclo mora aqui, e a interface grafica
so vai chamar isto.

Biblioteca padrao pura, como todo o resto de `tools/`: quem quiser conferir o
que sobe para o servidor le este arquivo inteiro em vinte minutos, sem instalar
nada.

Uso:

    export SGALAXY_URL=https://galaxy.bygianotto.com.br    # ou o tunel local

    python3 tools/sgalaxy.py registrar "Meu Nome"
    python3 tools/sgalaxy.py salas
    python3 tools/sgalaxy.py criar-sala --seed 1654267488 --nome "Fronteira"
    python3 tools/sgalaxy.py entrar SALA --save ~/.../savegames/Minha
    python3 tools/sgalaxy.py retirar SALA --para ~/.../savegames/Sala-SALA
    python3 tools/sgalaxy.py devolver SALA --save ~/.../savegames/Sala-SALA
    python3 tools/sgalaxy.py estado SALA
    python3 tools/sgalaxy.py apagar-conta

O token fica em `~/.config/sgalaxy/credenciais.json`, com permissao 600. Ele e a
unica credencial que existe: perder e perder, e nao ha e-mail de recuperacao.

REGRA QUE NAO SE NEGOCIA: nunca escrever num save com o jogo aberto. O jogo
reescreve o arquivo ao gravar, e escrever por baixo destrói a partida de alguem.
`retirar` detecta o processo e recusa.
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
CREDENTIALS = os.path.join(CONFIG_DIR, "credenciais.json")
DEFAULT_URL = "http://127.0.0.1:8714"

# Como o jogo aparece na tabela de processos. Duas formas:
#
# `spacehaven` e o launcher nativo, e o nome do EXECUTAVEL — casado com `-x`,
# que compara so o nome do programa. `spacehaven.jar` e a JVM que ele levanta, e
# so aparece na linha de comando, entao esse precisa de `-f`.
#
# A primeira versao usava `-f` com "SpaceHaven" solto, e casava demais: qualquer
# processo do Steam que mencionasse o caminho da instalacao — e ate o proprio
# shell que rodou o comando — virava "o jogo esta aberto". O erro e caro nos
# dois sentidos: falso positivo trava o jogador de brincadeira, falso negativo
# destroi a partida dele.
GAME_EXECUTABLES = ("spacehaven",)
GAME_COMMANDLINES = ("spacehaven.jar",)


class ClientError(Exception):
    """Erro que o usuario precisa ler. Mensagem em portugues."""


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
            f"nenhuma conta guardada para {base_url()}. "
            f"Rode: python3 tools/sgalaxy.py registrar \"Seu Nome\"")
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
            detalhe = json.loads(raw).get("detail", raw.decode("utf-8", "replace"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            detalhe = raw.decode("utf-8", "replace")
        raise ClientError(f"o servidor recusou ({exc.code}): {detalhe}") from exc
    except urllib.error.URLError as exc:
        raise ClientError(f"não consegui falar com {base_url()}: {exc.reason}") from exc


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
    """O nome do processo do jogo, se ele estiver aberto.

    A regra mais importante do cliente (secao 2.9): nunca escrever num save com
    o jogo aberto. Sem `pgrep`, devolve None e o chamador avisa que nao
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


def game_day_of(folder: str) -> float:
    """O dia de jogo de uma pasta de save, ou -1 se nao der para ler."""
    import xml.etree.ElementTree as ET
    caminho = os.path.join(folder, "info")
    try:
        with open(caminho, "rb") as fh:
            valor = ET.fromstring(fh.read()).get("date")
        return int(valor) / 86400 if valor else -1.0
    except (OSError, ET.ParseError, ValueError, TypeError):
        return -1.0


def most_advanced(room_folder: str) -> tuple:
    """A pasta com mais progresso: o save manual ou o autosave mais adiantado.

    Quem sai do jogo sem salvar na mao deixa o avanco no autosave, e a secao
    2.4 e explicita: o cliente precisa conseguir devolver o ultimo autosave.
    Comparar por dia de jogo, e nao por data de arquivo, e o que faz isso valer
    tambem depois de uma queda — o relogio do sistema nao diz quanto se jogou.
    """
    room_folder = os.path.abspath(os.path.expanduser(room_folder))
    candidatos = []
    for nome in sorted(os.listdir(room_folder)):
        caminho = os.path.join(room_folder, nome)
        if os.path.isfile(os.path.join(caminho, "game")):
            candidatos.append((game_day_of(caminho), nome, caminho))
    if not candidatos:
        raise ClientError(f"não achei nenhum savegame dentro de {room_folder}")
    candidatos.sort(reverse=True)
    dia, nome, caminho = candidatos[0]
    return caminho, nome, dia


def resolve_save(path: str) -> str:
    """Aceita a pasta do save, a pasta que a contem, ou o arquivo `game`."""
    path = os.path.abspath(os.path.expanduser(path))
    if os.path.isfile(path):
        return os.path.dirname(path)
    if os.path.isdir(path):
        if os.path.isfile(os.path.join(path, "game")):
            return path
        dentro = os.path.join(path, "save")
        if os.path.isfile(os.path.join(dentro, "game")):
            return dentro
    raise ClientError(f"não achei um savegame em {path} "
                      f"(esperava um arquivo `game` ali dentro)")


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
    """Abre o save recebido numa pasta de savegame do jogo.

    Escreve numa pasta ao lado e so entao troca, para uma queda no meio nao
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
        raise ClientError("o servidor mandou algo que não é um savegame")

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

def cmd_registrar(args) -> int:
    dados = json_request("POST", "/api/v1/players",
                         {"name": args.nome, "invite": args.convite or ""},
                         auth=False)
    save_credentials({"token": dados["token"], "playerId": dados["playerId"],
                      "name": dados["name"]})
    print(f"conta criada em {base_url()}")
    print(f"  nome:  {dados['name']}")
    print(f"  token: guardado em {CREDENTIALS}")
    print()
    print("  CÓDIGO DE RECUPERAÇÃO — anote em algum lugar seguro:")
    print(f"    {dados['recoveryCode']}")
    print()
    print("  É a única forma de voltar a esta conta. O servidor não tem cópia,")
    print("  não há e-mail de recuperação, e perder é perder.")
    return 0


def cmd_salas(args) -> int:
    dados = json_request("GET", "/api/v1/rooms", auth=False)
    if not dados["rooms"]:
        print("nenhuma sala aberta")
        return 0
    print(f"{'id':<8}{'jogadores':<12}{'senha':<8}nome")
    for sala in dados["rooms"]:
        print(f"{sala['id']:<8}{sala['players']}/{sala['maxPlayers']:<10}"
              f"{'sim' if sala['hasPassword'] else 'não':<8}{sala['name']}")
    return 0


def cmd_criar_sala(args) -> int:
    dados = json_request("POST", "/api/v1/rooms", {
        "seed": args.seed, "name": args.nome, "password": args.senha,
        "leaseHours": args.prazo, "maxPlayers": args.max_jogadores,
        "options": _receita(args)})
    print(f"sala {dados['id']} criada")
    print(f"  seed:  {dados['seed']}")
    print(f"  prazo: {dados['leaseHours']}h")
    print()
    print(f"  Publique a receita para quem for entrar:")
    print(f"    python3 tools/sgalaxy.py como-entrar {dados['id']}")
    if not _receita(args):
        print()
        print("  A receita está vazia. Depois de criar a partida no jogo,")
        print("  registre a nave e as opções que você marcou:")
        print(f"    python3 tools/sgalaxy.py configurar-sala {dados['id']} \\")
        print(f"        --nave \"Nome da nave inicial\" --dificuldade Normal")
    return 0


def _receita(args) -> dict:
    """O que alguem precisa reproduzir para o save ser aceito na sala."""
    receita = {}
    if getattr(args, "nave", None):
        receita["nave"] = args.nave
    if getattr(args, "dificuldade", None):
        receita["dificuldade"] = args.dificuldade
    for item in getattr(args, "opcao", None) or []:
        if "=" not in item:
            raise ClientError(f"--opcao espera chave=valor, veio {item!r}")
        chave, valor = item.split("=", 1)
        receita[chave.strip()] = valor.strip()
    return receita


def cmd_configurar_sala(args) -> int:
    payload = {}
    receita = _receita(args)
    if receita:
        atual = json_request("GET", f"/api/v1/rooms/{args.sala}")
        payload["options"] = {**(atual.get("options") or {}), **receita}
    if args.nome:
        payload["name"] = args.nome
    if args.prazo:
        payload["leaseHours"] = args.prazo
    if not payload:
        raise ClientError("nada para mudar. Use --nave, --dificuldade, "
                          "--opcao chave=valor, --nome ou --prazo")
    json_request("PATCH", f"/api/v1/rooms/{args.sala}", payload)
    print(f"sala {args.sala} atualizada")
    return cmd_como_entrar(args)


def cmd_como_entrar(args) -> int:
    """A receita, do jeito que a pessoa vai seguir na tela de criação."""
    head = {"X-Room-Password": getattr(args, "senha", None) or ""}
    _s, raw, _h = request("GET", f"/api/v1/rooms/{args.sala}", None, head)
    sala = json.loads(raw)
    if "seed" not in sala:
        raise ClientError("esta sala tem senha; passe --senha para ver a receita")

    print(f"Para entrar na sala {sala['id']} ({sala['name']}):")
    print()
    print("  1. No Space Haven, crie uma partida nova com:")
    print(f"       seed: {sala['seed']}")
    receita = sala.get("options") or {}
    if receita.get("nave"):
        print(f"       nave inicial: {receita['nave']}")
    if receita.get("dificuldade"):
        print(f"       dificuldade: {receita['dificuldade']}")
    outras = {k: v for k, v in receita.items()
              if k not in ("nave", "dificuldade")}
    for chave, valor in sorted(outras.items()):
        print(f"       {chave}: {valor}")
    if not receita:
        print("       (o dono da sala ainda não publicou as opções de cenário)")
    print()
    print("  2. Salve a partida e feche o jogo.")
    print()
    print("  3. Suba o save:")
    print(f"       python3 tools/sgalaxy.py entrar {sala['id']} \\")
    print(f"           --save CAMINHO/DA/PARTIDA")
    print()
    if sala.get("galaxyDigest"):
        print(f"  A galáxia desta sala é {sala['galaxyDigest']}. Se o seu save")
        print("  não bater, foi opção de criação diferente — a seed sozinha não")
        print("  basta.")
    else:
        print("  Ninguém entrou ainda: o primeiro save que subir define a")
        print("  galáxia da sala, e os seguintes têm que bater com ele.")
    return 0


def cmd_entrar(args) -> int:
    pasta = resolve_save(args.save)
    print(f"subindo {pasta} …")
    _s, raw, _h = request("POST", f"/api/v1/rooms/{args.sala}/join",
                          pack(pasta),
                          {"Content-Type": "application/zip",
                           "X-Room-Password": args.senha or ""})
    dados = json.loads(raw)
    galaxia = dados["galaxy"]
    print(f"entrou na sala {args.sala}")
    print(f"  galáxia:    {galaxia['digest']} "
          f"({galaxia['systems']} sistemas, {galaxia['bodies']} corpos)")
    print(f"  dia de jogo: {dados['gameDay']}")
    print(f"  sua nave:    {dados['presence']['shipName']}")
    print()
    print("  O servidor é dono deste save agora. Use `retirar` para jogar.")
    return 0


def cmd_retirar(args) -> int:
    aberto = game_is_running()
    if aberto:
        raise ClientError(
            f"o Space Haven está aberto ({aberto}). Feche o jogo antes: "
            f"escrever num save com o jogo aberto destrói a partida")
    if shutil.which("pgrep") is None:
        print("aviso: não consegui conferir se o jogo está aberto (sem `pgrep`).")
        print("       Certifique-se de que o Space Haven está fechado.")

    _s, data, headers = request("POST", f"/api/v1/rooms/{args.sala}/checkout")
    destino = args.para or os.path.join(os.getcwd(), f"Sala-{args.sala}")
    final = unpack(data, destino)
    print(f"save retirado para {final}")
    print(f"  prazo até: {_prazo(headers.get('x-lease-expires'))}")
    print(f"  {_tamanho(len(data))}")
    print()
    print("  Jogue, e depois devolva com:")
    print(f"    python3 tools/sgalaxy.py devolver {args.sala} --save {destino}")
    print("  Passado o prazo, a sessão volta ao estado de quando foi retirada.")
    return 0


def _prazo(iso: str | None) -> str:
    """O prazo em hora local, mais quanto falta — que e o que a pessoa quer."""
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


def _tamanho(n: int) -> str:
    """KB ate 1 MB. Um save novo tem 40 KB comprimido, e '0.0 MB' nao informa."""
    return f"{n / 1000:.0f} KB" if n < 1_000_000 else f"{n / 1_000_000:.1f} MB"


def cmd_devolver(args) -> int:
    aberto = game_is_running()
    if aberto:
        raise ClientError(
            f"o Space Haven está aberto ({aberto}). Feche o jogo antes de "
            f"devolver: o save pode não estar gravado por completo")
    pasta = resolve_save(args.save)
    print(f"devolvendo {pasta} …")
    _s, raw, _h = request("POST", f"/api/v1/rooms/{args.sala}/checkin",
                          pack(pasta), {"Content-Type": "application/zip"})
    dados = json.loads(raw)
    print("devolvido")
    print(f"  dia de jogo: {dados['gameDay']}")
    print(f"  versão:      {dados['versionId']}")
    if dados.get("pruned"):
        print(f"  {dados['pruned']} versão(ões) antiga(s) saíram da janela")
    return 0


def cmd_jogar(args) -> int:
    """Retira, abre o jogo, espera, e devolve. Um comando para a sessao inteira.

    E o fluxo que a secao 2.4 descreve, sem o jogador precisar lembrar de
    nenhuma etapa. Como e o cliente que lanca o jogo e espera o processo
    terminar, ele sabe com certeza quando a sessao comecou e acabou — que e
    exatamente o que a secao 2.9 diz ser a razao de o cliente lancar o jogo.
    """
    aberto = game_is_running()
    if aberto:
        raise ClientError(f"o Space Haven já está aberto ({aberto}). Feche "
                          f"antes: preciso controlar a sessão inteira")

    exe = args.jogo or find_game()
    if not exe or not os.path.isfile(exe):
        raise ClientError(
            "não achei o executável do Space Haven. Passe --jogo CAMINHO ou "
            "defina SPACEHAVEN_BIN")

    destino = args.para or _room_folder(args.sala)

    # -- 1. retirar
    print(f"[1/4] retirando o save da sala {args.sala} …")
    _s, data, headers = request("POST", f"/api/v1/rooms/{args.sala}/checkout")
    final = unpack(data, destino)
    prazo = headers.get("x-lease-expires")
    print(f"      {final}  ({_tamanho(len(data))})")
    print(f"      prazo: {_prazo(prazo)}")

    # -- 2. jogar
    nome_pasta = os.path.basename(destino.rstrip("/"))
    print(f"[2/4] abrindo o jogo. Carregue a partida '{nome_pasta}'.")
    print("      Quando você fechar o jogo, eu devolvo sozinho.")
    try:
        proc = subprocess.Popen([exe], cwd=os.path.dirname(exe))
        proc.wait()
    except KeyboardInterrupt:
        print("\n      interrompido; vou devolver o que houver")
    except OSError as exc:
        raise ClientError(f"não consegui abrir o jogo: {exc}") from exc

    # -- 3. escolher o estado mais avancado
    print("[3/4] procurando o estado mais avançado …")
    pasta, qual, dia = most_advanced(destino)
    print(f"      {qual} (dia {dia:.2f})")

    # -- 4. devolver
    print("[4/4] devolvendo …")
    try:
        _s, raw, _h = request("POST", f"/api/v1/rooms/{args.sala}/checkin",
                              pack(pasta), {"Content-Type": "application/zip"})
    except ClientError as exc:
        print(f"\nerro ao devolver: {exc}", file=sys.stderr)
        print(f"\nO seu progresso NÃO foi perdido: está em {pasta}.")
        print("Quando resolver, devolva com:")
        print(f"  python3 tools/sgalaxy.py devolver {args.sala} --save {pasta}")
        return 1
    dados = json.loads(raw)
    print(f"      dia {dados['gameDay']}, versão {dados['versionId']}")
    print()
    print("sessão fechada. O save está no servidor.")
    return 0


def _room_folder(sala: str) -> str:
    """Onde a pasta da sala mora, ao lado das outras partidas do jogo."""
    exe = find_game()
    if exe:
        saves = os.path.join(os.path.dirname(exe), "savegames")
        if os.path.isdir(saves):
            return os.path.join(saves, f"Sala-{sala}")
    return os.path.join(os.getcwd(), f"Sala-{sala}")


def cmd_situacao(args) -> int:
    """O que está em aberto, antes de você abrir o jogo por engano."""
    dados = json_request("GET", f"/api/v1/rooms/{args.sala}/state")
    eu = load_credentials().get("playerId")
    meu = next((p for p in dados["players"] if p["playerId"] == eu), None)
    if meu is None:
        print(f"você não está na sala {args.sala}")
        return 1
    print(f"sala {args.sala}")
    print(f"  sua nave:    {meu['shipName'] or '—'}")
    print(f"  dia no servidor: {meu['gameDay'] or '—'}")
    print(f"  empréstimo:  {'ABERTO' if meu['playing'] else 'fechado'}")

    pasta = _room_folder(args.sala)
    if not os.path.isdir(pasta):
        print(f"  pasta local: não existe ({pasta})")
        return 0
    try:
        _p, qual, dia = most_advanced(pasta)
    except ClientError:
        print(f"  pasta local: {pasta} (sem savegame dentro)")
        return 0
    print(f"  pasta local: {pasta}")
    print(f"               mais avançado: {qual}, dia {dia:.2f}")
    if not meu["playing"]:
        servidor = meu["gameDay"] or 0
        if dia > servidor + 0.01:
            print()
            print("  AVISO: a pasta local está À FRENTE do servidor e não há")
            print("  empréstimo aberto. Isso quer dizer que você jogou sem")
            print("  retirar. Uma nova retirada vai sobrescrever esse avanço.")
            print("  Esse avanço não tem como ser entregue: a sala só aceita")
            print("  o que saiu de um empréstimo. Guarde uma cópia da pasta")
            print("  antes de retirar, se quiser conservá-lo fora da sala.")
    return 0


def cmd_estado(args) -> int:
    dados = json_request("GET", f"/api/v1/rooms/{args.sala}/state")
    if not dados["players"]:
        print("sala vazia")
        return 0
    print(f"{'jogador':<18}{'nave':<24}{'sistema':<10}{'corpo':<8}{'dia':<8}onde")
    for p in dados["players"]:
        print(f"{(p['name'] or '?'):<18}{(p['shipName'] or '—'):<24}"
              f"{(p['system'] or '—'):<10}{(p['celeid'] or '—'):<8}"
              f"{str(p['gameDay'] or '—'):<8}"
              f"{'jogando' if p['playing'] else 'fora'}")
    return 0


def cmd_apagar_conta(args) -> int:
    print("Isto apaga a sua conta e TODOS os seus saves neste servidor.")
    print("Não há como desfazer.")
    if input("Digite 'apagar tudo' para confirmar: ").strip() != "apagar tudo":
        print("cancelado")
        return 1
    dados = json_request("DELETE", "/api/v1/me?confirm=apagar%20tudo")
    print(dados["message"])
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
        description="cliente da Galáxia Compartilhada",
        epilog=f"servidor: {base_url()} (mude com SGALAXY_URL)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("registrar", help="cria uma conta neste servidor")
    p.add_argument("nome")
    p.add_argument("--convite", help="se o servidor exigir")
    p.set_defaults(func=cmd_registrar)

    p = sub.add_parser("salas", help="lista as salas abertas")
    p.set_defaults(func=cmd_salas)

    p = sub.add_parser("criar-sala", help="cria uma sala")
    p.add_argument("--seed", required=True, help="a seed da galáxia")
    p.add_argument("--nome", default="")
    p.add_argument("--senha")
    p.add_argument("--prazo", type=int, default=12, help="horas de empréstimo")
    p.add_argument("--max-jogadores", type=int, default=8)
    p.add_argument("--nave", help="nave inicial que todos devem escolher")
    p.add_argument("--dificuldade")
    p.add_argument("--opcao", action="append", metavar="CHAVE=VALOR",
                   help="opção de cenário; pode repetir")
    p.set_defaults(func=cmd_criar_sala)

    p = sub.add_parser("configurar-sala",
                       help="publica ou corrige a receita da sala")
    p.add_argument("sala")
    p.add_argument("--nave", help="nave inicial que todos devem escolher")
    p.add_argument("--dificuldade")
    p.add_argument("--opcao", action="append", metavar="CHAVE=VALOR",
                   help="opção de cenário; pode repetir")
    p.add_argument("--nome")
    p.add_argument("--prazo", type=int)
    p.add_argument("--senha", help="se a sala tiver")
    p.set_defaults(func=cmd_configurar_sala)

    p = sub.add_parser("como-entrar",
                       help="a receita para reproduzir a galáxia da sala")
    p.add_argument("sala")
    p.add_argument("--senha")
    p.set_defaults(func=cmd_como_entrar)

    p = sub.add_parser("entrar", help="sobe o save inicial e entra numa sala")
    p.add_argument("sala")
    p.add_argument("--save", required=True, help="pasta do savegame")
    p.add_argument("--senha")
    p.set_defaults(func=cmd_entrar)

    p = sub.add_parser("retirar", help="retira o save para jogar")
    p.add_argument("sala")
    p.add_argument("--para", help="pasta de destino")
    p.set_defaults(func=cmd_retirar)

    p = sub.add_parser("devolver", help="devolve o save depois de jogar")
    p.add_argument("sala")
    p.add_argument("--save", required=True)
    p.set_defaults(func=cmd_devolver)

    p = sub.add_parser("jogar",
                       help="retira, abre o jogo, e devolve ao fechar")
    p.add_argument("sala")
    p.add_argument("--para", help="pasta da sala (padrão: ao lado do jogo)")
    p.add_argument("--jogo", help="caminho do executável do Space Haven")
    p.set_defaults(func=cmd_jogar)

    p = sub.add_parser("situacao",
                       help="o que está em aberto, antes de abrir o jogo")
    p.add_argument("sala")
    p.set_defaults(func=cmd_situacao)

    p = sub.add_parser("estado", help="quem está onde na sala")
    p.add_argument("sala")
    p.set_defaults(func=cmd_estado)

    p = sub.add_parser("apagar-conta", help="apaga conta e saves, sem volta")
    p.set_defaults(func=cmd_apagar_conta)

    args = ap.parse_args()
    try:
        return args.func(args)
    except ClientError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
