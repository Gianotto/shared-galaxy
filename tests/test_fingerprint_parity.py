"""
Teste cruzado da impressao digital vendorada.

`server/galaxy/fingerprint.py` e copia de `tools/compare_galaxy.py` do editor de
savegame. Duas copias da mesma logica derivam em silencio, e a consequencia aqui
nao e cosmetica: se o servidor calcular um digest diferente do que o editor
calcula, ele recusa saves legitimos na entrada de uma sala (secao 2.3) sem
ninguem entender por que.

Este teste e a defesa. Ele roda as duas funcoes sobre o mesmo save e exige o
mesmo digest.

O `VENDOR.md` chama isso de obrigatorio antes da fase 2. Ele fica aqui desde a
fase 0 porque custa pouco e porque a divergencia so aparece quando alguem mexe
numa das duas copias — que e exatamente quando ninguem esta olhando.

Precisa do repositorio do editor ao lado para rodar. Sem ele, o teste se declara
pulado em vez de passar caladamente: um teste que nao rodou nao e um teste que
passou, e o CI nao tem save nenhum.

    python3 -m unittest tests.test_fingerprint_parity -v
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.galaxy import fingerprint as vendored  # noqa: E402

# Onde procurar o editor. Nao ha descoberta esperta: ou esta ao lado, ou o
# caminho vem por variavel de ambiente.
EDITOR_PATHS = [
    os.environ.get("SPACEHAVEN_EDITOR", ""),
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), "space_haven_editor"),
]

# Saves reais para comparar. Sao arquivos pessoais e nao entram no repositorio,
# entao o teste procura e se declara pulado quando nao acha.
SAVE_ROOTS = [
    os.environ.get("SPACEHAVEN_SAVES", ""),
    os.path.expanduser("~/snap/steam/common/.local/share/Steam/steamapps/"
                       "common/SpaceHaven/savegames"),
    os.path.expanduser("~/.config/unity3d/Bugbyte/Space Haven/savegames"),
]


def _find_editor() -> str | None:
    for path in EDITOR_PATHS:
        if path and os.path.isfile(os.path.join(path, "tools", "compare_galaxy.py")):
            return path
    return None


def _find_saves(limit: int = 3) -> list[str]:
    out: list[str] = []
    for root in SAVE_ROOTS:
        if not root or not os.path.isdir(root):
            continue
        for name in sorted(os.listdir(root)):
            candidate = os.path.join(root, name, "save")
            if os.path.isfile(os.path.join(candidate, "game")):
                out.append(candidate)
            if len(out) >= limit:
                return out
    return out


class FingerprintParityTestCase(unittest.TestCase):

    def setUp(self):
        self.editor = _find_editor()
        if not self.editor:
            self.skipTest("repositório do editor não encontrado; defina "
                          "SPACEHAVEN_EDITOR para rodar o teste cruzado")
        self.saves = _find_saves()
        if not self.saves:
            self.skipTest("nenhum savegame encontrado; defina SPACEHAVEN_SAVES "
                          "para rodar o teste cruzado")

    def _upstream(self):
        """Importa o `fingerprint` do editor sem poluir o sys.path do processo.

        O modulo de la faz `sys.path.insert` para achar o `shedit`, e importar
        os dois pacotes no mesmo processo e justamente o que confundiria as
        copias. Por isso o import acontece isolado e e desfeito depois.
        """
        import importlib.util

        saved_path = list(sys.path)
        saved_modules = dict(sys.modules)
        try:
            sys.path.insert(0, self.editor)
            spec = importlib.util.spec_from_file_location(
                "_upstream_compare_galaxy",
                os.path.join(self.editor, "tools", "compare_galaxy.py"))
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module.fingerprint
        finally:
            sys.path[:] = saved_path
            for name in list(sys.modules):
                if name not in saved_modules:
                    del sys.modules[name]
            sys.modules.update(saved_modules)

    def test_digests_deliberately_differ(self):
        """A divergência é intencional, e está registrada.

        O editor monta o digest a partir de corpos, setores e nuvens. Medido:
        a galáxia é materializada preguiçosamente, e um salto de hiperespaço
        acrescentou 14 corpos a um sistema — então aquele digest identifica o
        quanto foi explorado, não qual galáxia é. O servidor passou a usar só
        as estrelas, que existem desde o primeiro save e não se movem.

        Este teste trava a divergência para ninguém "consertar" de volta.
        """
        upstream = self._upstream()
        save = self.saves[0]
        self.assertNotEqual(
            vendored.fingerprint(save)["digest"], upstream(save)["digest"],
            "os digests voltaram a coincidir: ou o editor adotou as estrelas "
            "(atualize sgalaxy/VENDOR.md), ou o servidor voltou a contar "
            "corpos e vai recusar quem viajar")

    def test_the_reading_still_matches(self):
        """O digest diverge de propósito, a LEITURA não pode divergir.

        As duas cópias têm que enxergar os mesmos sistemas, corpos e setores.
        Se isso deriva, é bug de vendoração e não decisão de desenho.
        """
        upstream = self._upstream()
        save = self.saves[0]
        mine, theirs = vendored.fingerprint(save), upstream(save)
        self.assertEqual(len(mine["systems"]), len(theirs["systems"]))
        for a, b in zip(mine["systems"], theirs["systems"]):
            self.assertEqual(a["bodies"], b["bodies"])
            self.assertEqual(a["sectors"], b["sectors"])
            self.assertEqual(a["clouds"], b["clouds"])


if __name__ == "__main__":
    unittest.main()


class GalaxyGrowsTestCase(unittest.TestCase):
    """A galáxia cresce enquanto se joga, e o portão precisa saber disso.

    Medido numa sessão recusada de verdade: 64 sistemas na entrega, 65 na
    devolução, e as 64 estrelas em comum idênticas byte a byte. O save estava
    certo — o portão é que estava errado, e custou a sessão de alguém.
    """

    ESTRELAS = {str(i): {"celeid": str(i), "seed": str(1000 + i),
                         "x": str(i * 10), "y": str(i * 7),
                         "starType": "M", "starClass": "V"}
                for i in range(1, 65)}

    def test_a_save_that_discovered_a_new_system_still_belongs(self):
        maior = dict(self.ESTRELAS)
        maior["65"] = {"celeid": "65", "seed": "9999", "x": "1", "y": "2",
                       "starType": "G", "starClass": "V"}
        ok, motivo = vendored.agree(self.ESTRELAS, maior)
        self.assertTrue(ok, motivo)

    def test_a_fresher_save_with_fewer_systems_still_belongs(self):
        menor = {k: v for k, v in self.ESTRELAS.items() if int(k) <= 40}
        self.assertTrue(vendored.agree(self.ESTRELAS, menor)[0])

    def test_a_save_that_disagrees_about_one_system_is_refused(self):
        """Uma seed gera o mesmo sistema todas as vezes: discordar é ser
        outra galáxia."""
        outra = dict(self.ESTRELAS)
        outra["6"] = dict(outra["6"], seed="0000")
        ok, motivo = vendored.agree(self.ESTRELAS, outra)
        self.assertFalse(ok)
        self.assertIn("system 6", motivo)

    def test_a_tiny_save_cannot_agree_by_having_nothing_to_contradict(self):
        """O limite mede o que a SALA conhece. Medi-lo contra o save faz um
        save de três sistemas exigir três coincidências — e passar."""
        minusculo = {k: v for k, v in self.ESTRELAS.items() if int(k) <= 3}
        ok, motivo = vendored.agree(self.ESTRELAS, minusculo)
        self.assertFalse(ok)
        self.assertIn("3 system", motivo)

    def test_a_room_with_no_galaxy_yet_accepts_the_first_save(self):
        self.assertTrue(vendored.agree({}, self.ESTRELAS)[0])
