"""
Guarda de savegames, enderecada por conteudo.

O Postgres guarda metadado; o save em si mora aqui, num volume. A decisao esta
no plano (etapa B): backup e `tar` da pasta, auto-hospedar nao exige nada, e
`large object` de Postgres e uma dor que nao precisamos.

Tres propriedades que valem a pena entender antes de mexer:

**Enderecado por conteudo.** O nome do arquivo e o sha256 do que tem dentro.
Duas versoes identicas ocupam um blob so — e isso nao e otimizacao prematura: um
jogador que retira o save e devolve sem jogar produz exatamente o mesmo
conteudo, e a fase 1 vai mandar batimento com frequencia.

**Comprimido.** O save e XML numa linha so e comprime para perto de 10%. Uma
partida de 124 dias tem 4,5 MB, entao uma sala de seis pessoas com vinte versoes
cada cabe em poucas centenas de MB.

**Contado por referencia.** A poda de retencao apaga *versoes*, nao blobs; um
blob so vai embora quando nenhuma versao aponta para ele. Quem faz essa conta e
o banco, e por isso `delete_unreferenced` recebe de fora o conjunto de hashes
vivos em vez de tentar adivinhar.

O save chega como um `.zip` montado pelo cliente, porque um save e uma pasta com
`game`, `ships/`, `sector*/` e binarios soltos. O servidor nao descompacta para
guardar: guarda o zip inteiro e so abre quando precisa olhar dentro (a impressao
digital do `join`, a conciliacao da fase 3).
"""

from __future__ import annotations

import gzip
import hashlib
import os
import shutil
import tempfile
import zipfile

# Um save de 124 dias tem 4,5 MB de `game` mais naves e setores; o zip inteiro
# de uma partida grande medida foi de 11 MB. 64 MB deixa folga de ordem de
# grandeza e ainda barra upload de lixo, que e o ponto numa sala aberta.
MAX_UPLOAD_BYTES = 64 * 1024 * 1024

# Prefixo de dois caracteres no caminho para nao criar um diretorio com dezenas
# de milhares de entradas.
FANOUT = 2


class StorageError(Exception):
    """Erro de guarda. Mensagem em portugues, como no resto do projeto."""


class BlobStore:
    """Arquivos enderecados por sha256, comprimidos, num volume."""

    def __init__(self, root: str):
        self.root = os.path.abspath(root)
        os.makedirs(self.root, exist_ok=True)

    # -- caminhos ----------------------------------------------------------

    def _path(self, digest: str) -> str:
        if len(digest) != 64 or not all(c in "0123456789abcdef" for c in digest):
            raise StorageError(f"{digest!r} is not a hex sha256")
        return os.path.join(self.root, digest[:FANOUT], f"{digest}.gz")

    def exists(self, digest: str) -> bool:
        return os.path.isfile(self._path(digest))

    # -- escrita -----------------------------------------------------------

    def put(self, data: bytes) -> dict:
        """Guarda `data` e devolve o que o banco precisa registrar.

        Idempotente: guardar duas vezes o mesmo conteudo nao duplica nada e nao
        e erro. `stored` diz se o blob e novo, o que serve para metrica e para
        entender custo de armazenamento sem contar arquivo na mao.
        """
        if not data:
            raise StorageError("empty save")
        if len(data) > MAX_UPLOAD_BYTES:
            raise StorageError(
                f"save de {len(data)} bytes passa do limite de "
                f"{MAX_UPLOAD_BYTES} ({MAX_UPLOAD_BYTES // (1024*1024)} MB)")

        digest = hashlib.sha256(data).hexdigest()
        path = self._path(digest)
        if os.path.isfile(path):
            return {"sha256": digest, "bytes": len(data), "stored": False,
                    "storedBytes": os.path.getsize(path)}

        os.makedirs(os.path.dirname(path), exist_ok=True)
        # Escreve ao lado e move: um processo morto no meio nao deixa blob
        # truncado com nome de conteudo valido, que seria corrupcao silenciosa.
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as raw:
                with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz:
                    gz.write(data)
            os.replace(tmp, path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
        return {"sha256": digest, "bytes": len(data), "stored": True,
                "storedBytes": os.path.getsize(path)}

    # -- leitura -----------------------------------------------------------

    def get(self, digest: str) -> bytes:
        path = self._path(digest)
        if not os.path.isfile(path):
            raise StorageError(f"blob {digest[:12]}… is not stored")
        with gzip.open(path, "rb") as fh:
            data = fh.read()
        # Conferir na leitura e barato e transforma bit podre em erro claro, em
        # vez de num save que o jogo recusa na maquina do jogador.
        actual = hashlib.sha256(data).hexdigest()
        if actual != digest:
            raise StorageError(
                f"blob {digest[:12]}… está corrompido: o conteúdo tem hash "
                f"{actual[:12]}…")
        return data

    # -- poda --------------------------------------------------------------

    def delete_unreferenced(self, live: set[str]) -> dict:
        """Apaga blobs que nenhuma versao referencia.

        `live` vem do banco. Nao ha inferencia aqui de proposito: um erro de
        contagem apagaria save de jogador, e o unico lugar que sabe quais
        versoes existem e a tabela.
        """
        removed, freed = 0, 0
        for prefix in os.listdir(self.root):
            folder = os.path.join(self.root, prefix)
            if not os.path.isdir(folder):
                continue
            for name in os.listdir(folder):
                if not name.endswith(".gz"):
                    continue
                digest = name[:-3]
                if digest in live:
                    continue
                path = os.path.join(folder, name)
                freed += os.path.getsize(path)
                os.unlink(path)
                removed += 1
            if not os.listdir(folder):
                os.rmdir(folder)
        return {"removed": removed, "freedBytes": freed}

    def usage(self) -> dict:
        blobs, total = 0, 0
        for prefix in os.listdir(self.root):
            folder = os.path.join(self.root, prefix)
            if not os.path.isdir(folder):
                continue
            for name in os.listdir(folder):
                if name.endswith(".gz"):
                    blobs += 1
                    total += os.path.getsize(os.path.join(folder, name))
        return {"blobs": blobs, "bytes": total}


# ---------------------------------------------------------------------------
# O zip que o cliente manda
# ---------------------------------------------------------------------------

# Um save valido tem `game` na raiz. `info` costuma vir junto e e de onde sai a
# versao do formato, mas nao e obrigatorio para o jogo abrir.
REQUIRED_MEMBERS = ("game",)


def unpack_save(data: bytes, dest: str) -> str:
    """Abre o zip de um save numa pasta e devolve o caminho dela.

    Recusa caminho que escape do destino. E um zip que veio pela rede, de uma
    sala aberta: `../../etc` dentro de um nome de membro e a primeira coisa que
    alguem tenta, e `extractall` sozinho ja protege nas versoes atuais do
    Python, mas conferir aqui deixa o motivo explicito e a recusa legivel.
    """
    os.makedirs(dest, exist_ok=True)
    try:
        with zipfile.ZipFile(io_bytes(data)) as zf:
            names = zf.namelist()
            for name in names:
                if name.startswith("/") or ".." in name.replace("\\", "/").split("/"):
                    raise StorageError(
                        f"o zip tem um caminho que escapa da pasta: {name!r}")
            root = _save_root(names)
            if root is None:
                raise StorageError(
                    "este zip não parece um savegame: não achei um arquivo "
                    "`game` dentro dele")
            zf.extractall(dest)
    except zipfile.BadZipFile as exc:
        raise StorageError(f"the upload is not a valid zip: {exc}") from exc
    return os.path.join(dest, root) if root else dest


def _save_root(names: list[str]) -> str | None:
    """Onde o `game` esta dentro do zip, como prefixo relativo.

    Aceita tanto o zip feito de dentro da pasta do save quanto o feito da pasta
    que a contem — os dois acontecem quando a pessoa compacta na mao.
    """
    candidates = [n for n in names if os.path.basename(n) == "game"
                  and not n.endswith("/")]
    if not candidates:
        return None
    shallowest = min(candidates, key=lambda n: n.count("/"))
    return os.path.dirname(shallowest)


def pack_save(folder: str) -> bytes:
    """Compacta uma pasta de save, para devolver ao cliente na retirada."""
    if not os.path.isfile(os.path.join(folder, "game")):
        raise StorageError(f"{folder} has no `game` file")
    buf = io_buffer()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for dirpath, _dirs, files in os.walk(folder):
            for name in sorted(files):
                full = os.path.join(dirpath, name)
                zf.write(full, os.path.relpath(full, folder))
    return buf.getvalue()


def io_bytes(data: bytes):
    import io
    return io.BytesIO(data)


def io_buffer():
    import io
    return io.BytesIO()


def with_unpacked(data: bytes):
    """Contexto que abre o save numa pasta temporaria e limpa depois.

    Usado pelo `join` (impressao digital) e pela conciliacao. O save de um
    jogador nao fica descompactado no disco do servidor mais do que o necessario.
    """
    import contextlib

    @contextlib.contextmanager
    def _ctx():
        tmp = tempfile.mkdtemp(prefix="sgalaxy-save-")
        try:
            yield unpack_save(data, tmp)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    return _ctx()
