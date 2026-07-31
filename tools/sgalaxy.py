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
            return resp.status, resp.read(), dict(resp.headers)
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
    print(f"  prazo até: {headers.get('X-Lease-Expires', '?')}")
    print(f"  {len(data) / 1_000_000:.1f} MB")
    print()
    print("  Jogue, e depois devolva com:")
    print(f"    python3 tools/sgalaxy.py devolver {args.sala} --save {destino}")
    print("  Passado o prazo, a sessão volta ao estado de quando foi retirada.")
    return 0


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
