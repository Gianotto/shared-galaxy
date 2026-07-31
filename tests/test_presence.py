"""
Testes da leitura de presença.

O que o mapa da sala mostra e o que a fase 2 vai usar para decidir quem é
vizinho de quem. O erro caro aqui é confundir os dois ids de corpo celeste: o
um lugar é `(systemId, x, y)`, e trocar isso por um id de catálogo significa a
mesma coisa para todos os jogadores da sala. Trocar os dois põe o vizinho no
setor errado, sem erro nenhum aparecer.

    python3 -m unittest tests.test_presence -v
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.galaxy import presence  # noqa: E402
from tests import synthetic  # noqa: E402


class PresenceTestCase(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _save(self, xml: str, info: str | None = None) -> str:
        folder = synthetic.write_save(os.path.join(self.tmp.name, "s"), xml)
        with open(os.path.join(folder, "info"), "w", encoding="utf-8") as fh:
            fh.write(info or '<info version="21" date="111660"/>')
        return folder

    def test_reads_ship_name_and_position(self):
        folder = self._save(synthetic.build_game())
        here = presence.read(folder)
        self.assertEqual(here["shipName"], "Homestead")
        self.assertEqual(here["system"], "6")
        self.assertEqual(here["crew"], 2)

    def test_position_is_the_body_coordinates(self):
        """Um lugar é `(systemId, x, y)` — findings item 24.

        Não é `celeid`, que nomeia o tipo de lugar, nem o `id` local, que dois
        jogadores alocam para lugares diferentes conforme exploram.
        """
        folder = self._save(synthetic.build_game())
        aqui = presence.read(folder)
        self.assertEqual((aqui["x"], aqui["y"]), ("84119", "214759"))
        self.assertEqual(aqui["body"], "Asteroid")

    def test_the_fleets_own_coordinates_are_not_trusted(self):
        """A frota anuncia de onde saiu, não onde está.

        Medido em "E7c": a frota estava num planeta de x=75924 declarando
        x=75724, que era o asteroide anterior. Acreditar nela põe duas pessoas
        no mesmo planeta em lugares diferentes — e a mescla de descoberta da
        fase 2 casa corpos justamente por essa chave.
        """
        xml = synthetic.build_game().replace(
            '<f id="0" isPlayer="true" factionId="461">',
            '<f id="0" isPlayer="true" factionId="461" x="11111" y="22222">')
        aqui = presence.read(self._save(xml))
        self.assertEqual((aqui["x"], aqui["y"]), ("84119", "214759"),
                         "seguiu as coordenadas da frota em vez das do corpo")

    def test_a_fleet_in_open_space_still_has_a_position(self):
        """Sem corpo não há de quem herdar, e aí a frota é a fonte.

        Salvar em trânsito é jogo normal (findings item 22), e antes disso
        ficava sem posição no mapa da sala.
        """
        # Fora de qualquer corpo: sai do asteroide e vai para um setor vazio,
        # que é onde o jogo põe quem salvou em trânsito.
        xml = synthetic.build_game().replace(
            synthetic.FLEETS_TEMPLATE.format(npc_fleet=""), ""
        ).replace(
            "<emptySectors/>",
            '<emptySectors><l sectorId="7">'
            '<fleet><l id="0" isPlayer="true" factionId="461"'
            ' x="33333" y="44444"><createdShips/></l></fleet>'
            '</l></emptySectors>')
        aqui = presence.read(self._save(xml))
        self.assertEqual((aqui["x"], aqui["y"]), ("33333", "44444"))
        self.assertIsNone(aqui["body"], "espaço aberto não é um corpo")

    def test_age_days_comes_from_info(self):
        folder = self._save(synthetic.build_game(),
                            info='<info version="21" date="864000"/>')
        self.assertEqual(presence.read(folder)["ageDays"], 10.0)

    def test_counts_every_ship_but_names_only_the_player_one(self):
        ships = [synthetic.default_player_ship(), synthetic.npc_trader_ship()]
        folder = self._save(synthetic.build_game(ships=ships))
        here = presence.read(folder)
        self.assertEqual(here["ships"], 2)
        self.assertEqual(here["shipName"], "Homestead",
                         "nomeou uma nave que não é do jogador")

    def test_survives_a_save_without_info(self):
        """Campo nulo é melhor que exceção: perder o save de alguém por causa
        de um enfeite do mapa seria o pior resultado possível."""
        folder = synthetic.write_save(os.path.join(self.tmp.name, "sem-info"),
                                      synthetic.build_game())
        os.remove(os.path.join(folder, "info"))
        here = presence.read(folder)
        self.assertIsNone(here["ageDays"])
        self.assertEqual(here["shipName"], "Homestead")

    def test_survives_a_folder_that_is_not_a_save(self):
        empty = os.path.join(self.tmp.name, "vazio")
        os.makedirs(empty)
        here = presence.read(empty)
        self.assertIsNone(here["shipName"])
        self.assertIsNone(here["x"])


if __name__ == "__main__":
    unittest.main()
