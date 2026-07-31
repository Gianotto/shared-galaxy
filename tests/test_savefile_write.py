"""
Escrita byte-idêntica do `savefile.py` vendorado.

É a promessa que faz a cópia existir (`sgalaxy/VENDOR.md`): um serializador
próprio que reproduz o estilo do jogo — sem espaço antes de `/>`, ordem de
atributos preservada, escapes mínimos, sem declaração XML — mais um trailer de
bytes crus recuperado por diferença.

Enquanto este repositório só lia saves, divergir do upstream era inofensivo. O
enxerto **escreve**, e o construtor de retratos da fase 2 vai escrever mais. Uma
divergência aqui não dá erro: dá o save de um jogador corrompido, descoberto
quando ele for carregar. O `VENDOR.md` chama este teste de obrigatório antes da
fase 2.

Três garantias, em ordem de força:

1. **round-trip** — abrir um save real e gravá-lo sem mexer em nada devolve
   exatamente os mesmos bytes. É a mais forte: se ela vale, o serializador
   reproduz tudo que o jogo escreveu, inclusive o que ninguém documentou
2. **cirurgia** — depois de mudar um atributo, só o intervalo dele muda
3. **paridade** — as duas cópias produzem os mesmos bytes para o mesmo save

As três precisam de save real e se declaram puladas sem ele. O que roda sempre,
inclusive no CI que não tem save nenhum, é o estilo do serializador.

    python3 -m unittest tests.test_savefile_write -v
"""

from __future__ import annotations

import filecmp
import os
import shutil
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sgalaxy.savefile import SaveFile, serialize  # noqa: E402
from tests import synthetic  # noqa: E402
from tests.test_fingerprint_parity import _find_editor, _find_saves  # noqa: E402


def _bytes(caminho: str) -> bytes:
    with open(caminho, "rb") as fh:
        return fh.read()


class SerializerStyleTestCase(unittest.TestCase):
    """O estilo do jogo, sem precisar do jogo. Roda em qualquer lugar."""

    def test_no_xml_declaration(self):
        """O jogo não escreve `<?xml …?>`, e um save com ela não é o mesmo."""
        out = serialize(ET.fromstring('<game a="1"/>'))
        self.assertFalse(out.startswith(b"<?xml"))

    def test_empty_elements_close_without_a_space(self):
        """`<l a="1"/>`, nunca `<l a="1" />`."""
        self.assertEqual(serialize(ET.fromstring('<l a="1"/>')), b'<l a="1"/>')

    def test_attribute_order_is_preserved(self):
        """Reordenar atributos muda o arquivo inteiro num diff, e o jogo não faz isso."""
        original = '<l z="1" a="2" m="3"/>'
        self.assertEqual(serialize(ET.fromstring(original)), original.encode())

    def test_escapes_are_minimal(self):
        """Escapar o que não precisa também muda bytes."""
        out = serialize(ET.fromstring('<l s="a&amp;b" t="c&lt;d"/>')).decode()
        self.assertIn("a&amp;b", out)
        self.assertIn("c&lt;d", out)
        self.assertNotIn("&quot;", out)
        self.assertNotIn("&apos;", out)

    def test_a_synthetic_save_round_trips(self):
        """Sem save real, ao menos o molde tem que voltar igual."""
        tmp = tempfile.mkdtemp(prefix="sfw-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        pasta = synthetic.write_save(os.path.join(tmp, "s"),
                                     synthetic.build_game())
        alvo = os.path.join(pasta, "game")
        antes = _bytes(alvo)
        SaveFile(pasta).save(backup=False)
        self.assertEqual(_bytes(alvo), antes)


class RealSaveWriteTestCase(unittest.TestCase):

    def setUp(self):
        self.saves = _find_saves(limit=3)
        if not self.saves:
            self.skipTest("nenhum savegame encontrado; defina SPACEHAVEN_SAVES "
                          "para rodar o teste de escrita")
        self.tmp = tempfile.mkdtemp(prefix="sfw-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _copia(self, origem: str) -> str:
        destino = os.path.join(self.tmp, f"save{abs(hash(origem))}")
        shutil.copytree(origem, destino)
        return destino

    def test_writing_an_untouched_save_changes_nothing(self):
        """A garantia forte: abrir e gravar devolve os mesmos bytes.

        Vale para todo arquivo do save, não só o `game` — inclusive os `.bin`
        que ninguém documentou e que o serializador nem toca.
        """
        for origem in self.saves:
            with self.subTest(os.path.basename(os.path.dirname(origem))):
                destino = self._copia(origem)
                SaveFile(destino).save(backup=False)
                arquivos = [f for f in os.listdir(origem)
                            if os.path.isfile(os.path.join(origem, f))]
                _iguais, difs, erros = filecmp.cmpfiles(
                    origem, destino, arquivos, shallow=False)
                self.assertEqual(difs, [],
                                 "gravar sem mexer em nada mudou bytes; "
                                 "qualquer escrita corrompe save de jogador")
                self.assertEqual(erros, [])

    def test_an_edit_touches_only_its_own_bytes(self):
        """Mudar um atributo não pode reescrever o arquivo em volta."""
        destino = self._copia(self.saves[0])
        caminho = os.path.join(destino, "game")
        antes = _bytes(caminho)

        sf = SaveFile(destino)
        banco = sf.main.find("playerBank")
        self.assertIsNotNone(banco, "save real sem <playerBank>")
        antigo = banco.get("ca")
        novo = "123456"
        self.assertNotEqual(antigo, novo)
        banco.set("ca", novo)
        sf.docs["game"].dirty = True
        sf.save(backup=False)

        depois = _bytes(caminho)
        self.assertEqual(len(depois) - len(antes), len(novo) - len(antigo))

        # O prefixo e o sufixo em volta da mudança têm que estar intactos.
        primeira = next(i for i in range(min(len(antes), len(depois)))
                        if antes[i] != depois[i])
        ultima = next(j for j in range(1, min(len(antes), len(depois)))
                      if antes[-j] != depois[-j])
        self.assertEqual(antes[:primeira], depois[:primeira])
        self.assertEqual(antes[len(antes) - ultima + 1:],
                         depois[len(depois) - ultima + 1:])
        self.assertIn(f'ca="{novo}"'.encode(),
                      depois[primeira - 60:primeira + 60])

    def test_the_trailer_survives(self):
        """O `game` tem bytes crus depois do XML, e eles não são nossos.

        Recuperados por diferença na leitura. Perdê-los é a falha silenciosa
        clássica: o XML fica perfeito e o arquivo fica errado.
        """
        destino = self._copia(self.saves[0])
        sf = SaveFile(destino)
        trailer = sf.docs["game"].trailer
        sf.save(backup=False)
        bruto = _bytes(os.path.join(destino, "game"))
        if trailer:
            self.assertTrue(bruto.endswith(trailer),
                            "o trailer sumiu ao gravar")


class WriteParityTestCase(unittest.TestCase):
    """A cópia e o upstream têm que escrever os mesmos bytes.

    O `test_fingerprint_parity` cobre a LEITURA. Este cobre a escrita, que é a
    razão declarada de a cópia existir.
    """

    def setUp(self):
        self.editor = _find_editor()
        if not self.editor:
            self.skipTest("repositório do editor não encontrado; defina "
                          "SPACEHAVEN_EDITOR para rodar a paridade de escrita")
        self.saves = _find_saves(limit=2)
        if not self.saves:
            self.skipTest("nenhum savegame encontrado; defina SPACEHAVEN_SAVES")
        self.tmp = tempfile.mkdtemp(prefix="sfw-par-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _upstream_serialize(self):
        """Importa o `serialize` do editor isolado, sem misturar as cópias."""
        import importlib.util

        salvo_path, salvos = list(sys.path), dict(sys.modules)
        try:
            sys.path.insert(0, self.editor)
            spec = importlib.util.spec_from_file_location(
                "_upstream_savefile",
                os.path.join(self.editor, "shedit", "savefile.py"))
            modulo = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(modulo)
            return modulo.serialize
        finally:
            sys.path[:] = salvo_path
            for nome in list(sys.modules):
                if nome not in salvos:
                    del sys.modules[nome]
            sys.modules.update(salvos)

    def test_both_copies_serialize_a_real_save_identically(self):
        upstream = self._upstream_serialize()
        for origem in self.saves:
            with self.subTest(os.path.basename(os.path.dirname(origem))):
                destino = os.path.join(self.tmp, f"s{abs(hash(origem))}")
                shutil.copytree(origem, destino)
                sf = SaveFile(destino)
                self.assertEqual(serialize(sf.main), upstream(sf.main),
                                 "as cópias divergiram na escrita; a partir da "
                                 "fase 2 isso corrompe partida de jogador")


if __name__ == "__main__":
    unittest.main()
