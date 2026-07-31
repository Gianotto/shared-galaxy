"""
Testes da guarda de savegames.

Cobrem o que quebraria save de jogador: conteudo que volta diferente do que
entrou, blob apagado enquanto uma versao ainda aponta para ele, zip malicioso, e
o limite de upload que uma sala aberta precisa ter.

    python3 -m unittest tests.test_blobs -v
"""

from __future__ import annotations

import io
import os
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.storage.blobs import (  # noqa: E402
    MAX_UPLOAD_BYTES, BlobStore, StorageError, pack_save, unpack_save,
    with_unpacked,
)


def _zip(members: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in members.items():
            zf.writestr(name, content)
    return buf.getvalue()


class BlobStoreTestCase(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = BlobStore(os.path.join(self.tmp.name, "blobs"))

    def test_round_trip_is_exact(self):
        data = b"<game seed=\"0\"><masterData idCounter=\"55\"/></game>\n"
        meta = self.store.put(data)
        self.assertTrue(meta["stored"])
        self.assertEqual(self.store.get(meta["sha256"]), data)

    def test_same_content_is_stored_once(self):
        data = b"x" * 5000
        first = self.store.put(data)
        second = self.store.put(data)
        self.assertTrue(first["stored"])
        self.assertFalse(second["stored"], "o mesmo conteúdo foi guardado duas vezes")
        self.assertEqual(first["sha256"], second["sha256"])
        self.assertEqual(self.store.usage()["blobs"], 1)

    def test_xml_compresses_well(self):
        """A economia é a premissa do plano: histórico de N versões cabe."""
        data = (b'<e id="-1" m="927" rot="R90" x="76" y="12" fg="0"/>' * 2000)
        meta = self.store.put(data)
        ratio = meta["storedBytes"] / meta["bytes"]
        self.assertLess(ratio, 0.2,
                        f"comprimiu só para {ratio:.0%}; a premissa de "
                        f"armazenamento do plano assume perto de 10%")

    def test_rejects_oversized_upload(self):
        with self.assertRaises(StorageError) as ctx:
            self.store.put(b"a" * (MAX_UPLOAD_BYTES + 1))
        self.assertIn("limite", str(ctx.exception))

    def test_rejects_empty(self):
        with self.assertRaises(StorageError):
            self.store.put(b"")

    def test_corrupted_blob_is_caught_on_read(self):
        """Bit podre vira erro claro, não save que o jogo recusa."""
        meta = self.store.put(b"conteudo original")
        path = self.store._path(meta["sha256"])
        import gzip
        with gzip.open(path, "wb") as fh:
            fh.write(b"conteudo adulterado")
        with self.assertRaises(StorageError) as ctx:
            self.store.get(meta["sha256"])
        self.assertIn("corrompido", str(ctx.exception))

    def test_missing_blob_is_a_clear_error(self):
        with self.assertRaises(StorageError):
            self.store.get("0" * 64)

    def test_rejects_non_hex_digest(self):
        with self.assertRaises(StorageError):
            self.store.get("não é um hash")

    # -- poda --------------------------------------------------------------

    def test_prune_keeps_referenced(self):
        vivo = self.store.put(b"versao canonica")["sha256"]
        morto = self.store.put(b"versao antiga")["sha256"]
        result = self.store.delete_unreferenced({vivo})
        self.assertEqual(result["removed"], 1)
        self.assertTrue(self.store.exists(vivo))
        self.assertFalse(self.store.exists(morto))

    def test_prune_with_everything_live_removes_nothing(self):
        a = self.store.put(b"um")["sha256"]
        b = self.store.put(b"dois")["sha256"]
        self.assertEqual(self.store.delete_unreferenced({a, b})["removed"], 0)


class SavePackagingTestCase(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_unpacks_flat_save(self):
        data = _zip({"game": "<game/>", "info": '<info version="21"/>'})
        folder = unpack_save(data, os.path.join(self.tmp.name, "a"))
        self.assertTrue(os.path.isfile(os.path.join(folder, "game")))

    def test_unpacks_save_inside_a_folder(self):
        """Quem compacta na mão costuma incluir a pasta que contém o save."""
        data = _zip({"save/game": "<game/>", "save/ships/ship55": "<ship/>"})
        folder = unpack_save(data, os.path.join(self.tmp.name, "b"))
        self.assertTrue(os.path.isfile(os.path.join(folder, "game")))
        self.assertTrue(os.path.isfile(os.path.join(folder, "ships", "ship55")))

    def test_rejects_zip_without_a_game_file(self):
        data = _zip({"leiame.txt": "oi"})
        with self.assertRaises(StorageError) as ctx:
            unpack_save(data, os.path.join(self.tmp.name, "c"))
        self.assertIn("savegame", str(ctx.exception))

    def test_rejects_path_traversal(self):
        """Sala aberta, zip vindo pela rede: é a primeira coisa que tentam."""
        data = _zip({"game": "<game/>", "../fora.txt": "escapou"})
        with self.assertRaises(StorageError) as ctx:
            unpack_save(data, os.path.join(self.tmp.name, "d"))
        self.assertIn("escapa", str(ctx.exception))

    def test_rejects_garbage(self):
        with self.assertRaises(StorageError):
            unpack_save(b"isto nao e um zip", os.path.join(self.tmp.name, "e"))

    def test_pack_and_unpack_preserve_the_tree(self):
        src = os.path.join(self.tmp.name, "save")
        os.makedirs(os.path.join(src, "ships"))
        os.makedirs(os.path.join(src, "sector104"))
        with open(os.path.join(src, "game"), "w") as fh:
            fh.write("<game/>")
        with open(os.path.join(src, "ships", "ship55"), "w") as fh:
            fh.write("<ship/>")
        with open(os.path.join(src, "sector104", "s"), "w") as fh:
            fh.write("x")

        data = pack_save(src)
        back = unpack_save(data, os.path.join(self.tmp.name, "volta"))
        for rel in ("game", "ships/ship55", "sector104/s"):
            self.assertTrue(os.path.isfile(os.path.join(back, rel)),
                            f"{rel} não sobreviveu ao ciclo")

    def test_with_unpacked_cleans_up(self):
        data = _zip({"game": "<game/>"})
        with with_unpacked(data) as folder:
            self.assertTrue(os.path.isfile(os.path.join(folder, "game")))
            guardado = folder
        self.assertFalse(os.path.exists(guardado),
                         "o save ficou descompactado no disco depois do uso")


if __name__ == "__main__":
    unittest.main()
