"""
Testes de `tools/save_diff.py` contra saves sinteticos.

O que estes testes provam: que o diff acha o que mudou, que nao inventa mudanca
onde nao houve, e que casa elementos por id em vez de por posicao — que e o
ponto onde um diff ingenuo erraria e inventaria uma transacao inexistente.

O que eles NAO provam: nada sobre o jogo. Se o Space Haven grava uma compra do
jeito que este projeto supoe, so um save real responde.

    python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests import synthetic  # noqa: E402
from tools.save_diff import (  # noqa: E402
    apply_filters, compare, learn_noise,
)


class DiffTestCase(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _pair(self, before_xml: str, after_xml: str,
              before_ships=None, after_ships=None):
        a = synthetic.write_save(
            os.path.join(self.tmp.name, "a"), before_xml, before_ships)
        b = synthetic.write_save(
            os.path.join(self.tmp.name, "b"), after_xml, after_ships)
        return compare(a, b)["changes"]

    # -- o caso base: nada mudou -------------------------------------------

    def test_identical_saves_have_no_changes(self):
        xml = synthetic.build_game()
        self.assertEqual(self._pair(xml, xml), [])

    # -- uma transacao de compra -------------------------------------------

    def test_purchase_shows_as_credits_and_cargo(self):
        """O jogador compra 10 de um recurso do NPC por 500 creditos."""
        npc_before = synthetic.npc_trader_ship(
            credits=12309, stock=[{"element": 2053, "amount": 100}])
        npc_after = synthetic.npc_trader_ship(
            credits=11809, stock=[{"element": 2053, "amount": 90}])

        player_before = synthetic.default_player_ship()
        player_after = synthetic.default_player_ship()
        player_after["cargo"] = [{"element": 2053, "amount": 50},
                                 {"element": 2054, "amount": 12}]

        before = synthetic.build_game(
            player_credits=5000, ships=[player_before, npc_before])
        after = synthetic.build_game(
            player_credits=4500, ships=[player_after, npc_after])

        changes = self._pair(before, after)
        summary = {str(c) for c in changes}

        # Creditos do jogador cairam.
        self.assertTrue(
            any("playerBank" in s and "5000 -> 4500" in s for s in summary),
            f"nao achou a mudanca de creditos do jogador em {summary}")
        # Estoque do NPC caiu.
        self.assertTrue(
            any("100 -> 90" in s for s in summary),
            f"nao achou a queda de estoque do NPC em {summary}")
        # Carga do jogador subiu.
        self.assertTrue(
            any("40 -> 50" in s for s in summary),
            f"nao achou o aumento de carga do jogador em {summary}")
        # Creditos da nave do NPC subiram... na direcao contraria, que e o que
        # o shipBank registra quando ele vende.
        self.assertTrue(
            any("12309 -> 11809" in s for s in summary),
            f"nao achou a mudanca do shipBank em {summary}")

    # -- o erro que um diff ingenuo cometeria ------------------------------

    def test_reordered_cargo_is_not_a_change(self):
        """Inverter a ordem do inventario nao e transacao nenhuma.

        E o teste que justifica casar por `elementId` em vez de por posicao:
        um diff posicional reportaria duas mudancas aqui e o experimento
        concluiria que houve comercio onde so houve reordenacao.
        """
        ship_a = synthetic.default_player_ship()
        ship_b = synthetic.default_player_ship()
        ship_b["cargo"] = list(reversed(ship_a["cargo"]))

        changes = self._pair(synthetic.build_game(ships=[ship_a]),
                             synthetic.build_game(ships=[ship_b]))
        self.assertEqual(changes, [],
                         f"reordenacao virou mudanca: {[str(c) for c in changes]}")

    def test_ship_matched_by_sid_not_position(self):
        """Trocar a ordem das naves no arquivo nao e mudanca."""
        player = synthetic.default_player_ship()
        npc = synthetic.npc_trader_ship()
        changes = self._pair(synthetic.build_game(ships=[player, npc]),
                             synthetic.build_game(ships=[npc, player]))
        self.assertEqual(changes, [],
                         f"reordenar naves virou mudanca: "
                         f"{[str(c) for c in changes]}")

    # -- estrutura ---------------------------------------------------------

    def test_new_ship_is_reported_as_added(self):
        changes = self._pair(
            synthetic.build_game(ships=[synthetic.default_player_ship()]),
            synthetic.build_game(ships=[synthetic.default_player_ship(),
                                        synthetic.npc_trader_ship()]))
        kinds = {c.kind for c in changes}
        self.assertIn("added", kinds,
                      f"nave nova nao apareceu como adicionada: "
                      f"{[str(c) for c in changes]}")

    def test_ship_file_appearing_is_reported(self):
        """Uma nave que sai de ships/ e o jogo movendo nave entre setores."""
        xml = synthetic.build_game()
        ship = '<ship sid="7100" sname="Distante"><settings of="461" ' \
               'owner="Player"/></ship>\n'
        changes = self._pair(xml, xml, None, {"ship7100": ship})
        self.assertTrue(
            any(c.kind == "added" and "ship7100" in c.path for c in changes),
            f"arquivo de nave novo nao foi reportado: "
            f"{[str(c) for c in changes]}")

    # -- o defeito que so o save real encontrou -----------------------------

    def test_sentinel_ids_do_not_pair_everything_together(self):
        """Centenas de irmaos com id="-1" nao sao o mesmo elemento.

        Regressao de um defeito real. Todo elemento <e> dentro de uma nave vem
        com id="-1" no save 1.0.4 — o jogo usa isso para dizer "sem id". A
        primeira versao tratava como identidade, entao so o primeiro irmao
        casava e os outros viravam remocao mais adicao: 358 mudancas fantasma
        em dois saves que diferiam em seis atributos.
        """
        cells = "".join(
            f'<e id="-1" m="{900 + i}" rot="R90" x="{i}" y="7"/>'
            for i in range(200))
        ship = f'<ship sid="55" sname="Scrapper">{cells}</ship>'
        xml = f'<game><masterData idCounter="99"/><ships>{ship}</ships></game>\n'

        self.assertEqual(self._pair(xml, xml), [],
                         "irmaos com id sentinela viraram mudanca")

        # E uma mudanca de verdade no meio ainda aparece.
        changed = xml.replace('m="1000" rot="R90"', 'm="1000" rot="R180"')
        self.assertNotEqual(xml, changed, "o teste nao alterou nada")
        found = self._pair(xml, changed)
        self.assertTrue(found, "a mudanca real sumiu junto com o ruido")
        self.assertLessEqual(
            len(found), 4,
            f"uma mudanca virou muitas: {[str(c) for c in found]}")

    def test_hostmap_rows_are_identified_by_faction_pair(self):
        """Cada linha do hostmap e um par `s1`/`s2`, e sem id nenhum.

        Sem identidade por par, as 92 linhas do save real produzem caminhos
        iguais e uma assinatura de ruido aprendida numa silenciaria todas.
        """
        changes = self._pair(
            synthetic.build_game(other_side="Civilian", trade="true"),
            synthetic.build_game(other_side="Civilian", trade="false"))
        self.assertTrue(changes, "a mudanca de permissao nao apareceu")
        self.assertTrue(
            all("s1=Player,s2=Civilian" in c.path for c in changes),
            f"a linha do hostmap nao foi identificada pelo par: "
            f"{[c.path for c in changes]}")

    # -- ruido e foco ------------------------------------------------------

    def test_noise_profile_suppresses_known_churn(self):
        """O piso de ruido do E1 some quando o perfil e aplicado."""
        before = synthetic.build_game(id_counter=1000)
        noisy = synthetic.build_game(id_counter=1042)

        noise = set(learn_noise(self._pair(before, noisy))["signatures"])
        self.assertTrue(noise, "o perfil de ruido saiu vazio")

        # Mesmo ruido, mais uma transacao de verdade por cima.
        real = synthetic.build_game(id_counter=1042, player_credits=4500)
        changes = self._pair(before, real)
        filtered = apply_filters(changes, noise, None)

        self.assertTrue(filtered, "o filtro comeu a mudanca de verdade tambem")
        self.assertTrue(
            all("idCounter" not in (c.attr or "") for c in filtered),
            f"o ruido conhecido sobreviveu ao filtro: "
            f"{[str(c) for c in filtered]}")
        self.assertTrue(
            any("playerBank" in c.path for c in filtered),
            f"a mudanca de creditos nao sobreviveu: "
            f"{[str(c) for c in filtered]}")

    def test_focus_economy_drops_unrelated_paths(self):
        before = synthetic.build_game(player_credits=5000, relation=70)
        after = synthetic.build_game(player_credits=4500, relation=55)

        changes = self._pair(before, after)
        economy = apply_filters(changes, None, "economy")
        relations = apply_filters(changes, None, "relations")

        self.assertTrue(any("playerBank" in c.path for c in economy))
        self.assertFalse(any("hostmap" in c.path for c in economy),
                         "hostmap vazou para o foco de economia")
        self.assertTrue(any("hostmap" in c.path for c in relations))

    def test_relation_change_is_visible(self):
        """A tabela de relacoes e o painel de controle do servidor (1.8)."""
        changes = self._pair(synthetic.build_game(trade="true", vision="true"),
                             synthetic.build_game(trade="false", vision="false"))
        attrs = {c.attr for c in changes}
        self.assertIn("accessTrade", attrs)
        self.assertIn("accessVision", attrs)


if __name__ == "__main__":
    unittest.main()
