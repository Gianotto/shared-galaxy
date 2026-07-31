"""
Testes da leitura de presença.

O que o mapa da sala mostra e o que a fase 2 vai usar para decidir quem é
vizinho de quem. O erro caro aqui é confundir os dois ids de corpo celeste: o
`id` é local ao save e o `celeid` deriva da seed, e só o segundo significa a
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
            fh.write(info or '<info version="21" date="3289920"/>')
        return folder

    def test_reads_ship_name_and_position(self):
        folder = self._save(synthetic.build_game())
        here = presence.read(folder)
        self.assertEqual(here["shipName"], "Homestead")
        self.assertEqual(here["system"], "6")
        self.assertEqual(here["crew"], 2)

    def test_position_is_the_celeid_not_the_local_id(self):
        """O erro que o item 1 do findings registra, virado teste.

        No molde, a frota do jogador está no corpo `celeid=102`. Se a leitura
        devolvesse o `id` local, o servidor mandaria o vizinho para outro setor.
        """
        folder = self._save(synthetic.build_game())
        self.assertEqual(presence.read(folder)["celeid"], "102")

    def test_game_day_comes_from_info(self):
        folder = self._save(synthetic.build_game(),
                            info='<info version="21" date="864000"/>')
        self.assertEqual(presence.read(folder)["gameDay"], 10.0)

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
        self.assertIsNone(here["gameDay"])
        self.assertEqual(here["shipName"], "Homestead")

    def test_survives_a_folder_that_is_not_a_save(self):
        empty = os.path.join(self.tmp.name, "vazio")
        os.makedirs(empty)
        here = presence.read(empty)
        self.assertIsNone(here["shipName"])
        self.assertIsNone(here["celeid"])


if __name__ == "__main__":
    unittest.main()
