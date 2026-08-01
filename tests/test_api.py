"""
Testes da API contra um Postgres de verdade.

Não há banco falso aqui de propósito. As garantias que mais importam nesta fase
são do próprio banco — o índice único que permite um empréstimo aberto por
jogador é o que impede duplicação por sessão paralela, e um dublê não testaria
isso.

Precisa de `DATABASE_URL` apontando para um Postgres com a migração aplicada.
Sem isso, os testes se declaram pulados: um teste que não rodou não é um teste
que passou.

    docker run -d --name db -e POSTGRES_PASSWORD=test -p 55432:5432 postgres:17-alpine
    psql ... < migrations/001_initial.sql
    DATABASE_URL=postgresql://... python3 -m unittest tests.test_api -v
"""

from __future__ import annotations

import io
import os
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

HAS_DB = bool(os.environ.get("DATABASE_URL"))

if HAS_DB:
    os.environ.setdefault("BLOB_ROOT", tempfile.mkdtemp(prefix="sgalaxy-test-"))
    from fastapi.testclient import TestClient

    from server.api import db
    from server.api.app import app, store
    from server.storage import blobs
    from tests import synthetic


def _save_zip(age_days: float | None = None, **kwargs) -> bytes:
    """Um savegame sintético compactado, como o cliente mandaria.

    Por padrão é uma partida RECÉM-CRIADA, porque é isso que uma sala espera
    receber de quem entra. Passe `age_days` para simular uma colônia velha.
    """
    date = (synthetic.FRESH_DATE if age_days is None
            else int(age_days * 86400))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("game", synthetic.build_game(**kwargs))
        zf.writestr("info", f'<info version="21" date="{date}"/>')
    return buf.getvalue()


@unittest.skipUnless(HAS_DB, "defina DATABASE_URL para rodar os testes da API")
class ApiTestCase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def setUp(self):
        # Cada teste parte de banco E volume limpos: o estado de um não pode
        # explicar o resultado do outro. Esquecer o volume fez um teste de
        # "lixo não custa disco" contar blobs de testes anteriores.
        with db.pool().connection() as conn:
            conn.execute("TRUNCATE lease, membership, save_version, room, "
                         "player RESTART IDENTITY CASCADE")
        import shutil
        from server.api.app import store
        shutil.rmtree(store().root, ignore_errors=True)
        os.makedirs(store().root, exist_ok=True)

    # -- helpers -----------------------------------------------------------

    def _player(self, name="Jogador"):
        r = self.client.post("/api/v1/players", json={"name": name})
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()

    def _auth(self, player):
        return {"Authorization": f"Bearer {player['token']}"}

    def _room(self, player, **kw):
        payload = {"seed": "1654267488", "name": "Sala de teste", **kw}
        r = self.client.post("/api/v1/rooms", json=payload, headers=self._auth(player))
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()

    def _join(self, player, room_id, data=None, headers=None):
        return self.client.post(
            f"/api/v1/rooms/{room_id}/join",
            content=data if data is not None else _save_zip(),
            headers={**self._auth(player), **(headers or {})})

    # -- identidade --------------------------------------------------------

    def test_token_is_issued_once_and_works(self):
        player = self._player("Ana")
        self.assertIn("token", player)
        self.assertIn("recoveryCode", player)
        self.assertIn("Guarde", player["warning"])

        me = self.client.get("/api/v1/me", headers=self._auth(player))
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["name"], "Ana")

    def test_recovery_code_authenticates_too(self):
        """A pessoa vai copiar o código do papel, não o token cru."""
        player = self._player()
        r = self.client.get("/api/v1/me", headers={
            "Authorization": f"Bearer {player['recoveryCode']}"})
        self.assertEqual(r.status_code, 200)

    def test_unknown_token_is_refused_with_the_hard_truth(self):
        r = self.client.get("/api/v1/me",
                            headers={"Authorization": "Bearer INVENTADO"})
        self.assertEqual(r.status_code, 401)
        self.assertIn("no way to recover it", r.json()["detail"])

    def test_missing_auth_explains_the_header(self):
        self.assertEqual(self.client.get("/api/v1/me").status_code, 401)

    # -- salas -------------------------------------------------------------

    def test_room_creation_and_listing(self):
        player = self._player()
        room = self._room(player, name="Fronteira")
        self.assertEqual(len(room["id"]), 6)

        listing = self.client.get("/api/v1/rooms").json()["rooms"]
        self.assertEqual(len(listing), 1)
        self.assertEqual(listing[0]["name"], "Fronteira")
        self.assertEqual(listing[0]["players"], 0)

    def test_public_listing_does_not_leak_the_seed(self):
        """A seed é o convite para reproduzir a galáxia; não sai na vitrine."""
        player = self._player()
        self._room(player, password="segredo")
        listing = self.client.get("/api/v1/rooms").json()["rooms"][0]
        self.assertNotIn("seed", listing)
        self.assertTrue(listing["hasPassword"])

    def test_room_requires_a_seed(self):
        player = self._player()
        r = self.client.post("/api/v1/rooms", json={"name": "sem seed"},
                             headers=self._auth(player))
        self.assertEqual(r.status_code, 400)
        self.assertIn("seed", r.json()["detail"])

    def test_room_quota_is_enforced(self):
        from server.domain.rules import MAX_ROOMS_PER_PLAYER
        player = self._player()
        for _ in range(MAX_ROOMS_PER_PLAYER):
            self._room(player)
        r = self.client.post("/api/v1/rooms", json={"seed": "1"},
                             headers=self._auth(player))
        self.assertEqual(r.status_code, 403)
        self.assertIn("limit", r.json()["detail"])

    # -- entrada -----------------------------------------------------------

    def test_join_adopts_the_save_and_defines_the_galaxy(self):
        player = self._player()
        room = self._room(player)
        r = self._join(player, room["id"])
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertIn("canonical", body["message"])
        self.assertTrue(body["galaxy"]["digest"])

        detail = self.client.get(f"/api/v1/rooms/{room['id']}",
                                 headers=self._auth(player)).json()
        self.assertEqual(detail["galaxyDigest"], body["galaxy"]["digest"])
        self.assertEqual(detail["saveVersion"], "21")

    def test_second_player_with_the_same_galaxy_is_accepted(self):
        dono, vizinho = self._player("Dono"), self._player("Vizinho")
        room = self._room(dono)
        self._join(dono, room["id"])
        r = self._join(vizinho, room["id"])
        self.assertEqual(r.status_code, 200, r.text)

        estado = self.client.get(f"/api/v1/rooms/{room['id']}/state",
                                 headers=self._auth(dono)).json()
        self.assertEqual(len(estado["players"]), 2)

    # -- a loja: um armazem da propria nave --------------------------------

    def _com_armazem(self) -> bytes:
        """Um save com dois armazéns e um produtor, como uma nave de verdade."""
        import io as _io, zipfile as _zip
        xml = synthetic.build_game().replace(
            "<inv>", "<e><l id=\"435\" x=\"28\" y=\"20\"><feat><inv>"
            "<s elementaryId=\"712\" inStorage=\"25\" onTheWayIn=\"0\""
            " onTheWayOut=\"0\"/></inv></feat></l></e>"
            "<e><l id=\"608\" x=\"25\" y=\"20\"><feat><inv>"
            "<s elementaryId=\"712\" inStorage=\"200\" onTheWayIn=\"0\""
            " onTheWayOut=\"0\"/></inv></feat></l></e>"
            "<e><l id=\"900\" x=\"10\" y=\"10\"><feat><prod><inv>"
            "<s elementaryId=\"2053\" inStorage=\"40\" onTheWayIn=\"0\""
            " onTheWayOut=\"0\"/></inv></prod></feat></l></e><inv>", 1)
        buf = _io.BytesIO()
        with _zip.ZipFile(buf, "w") as zf:
            zf.writestr("game", xml)
            zf.writestr("info", f'<info version="21" date="{synthetic.FRESH_DATE}"/>')
        return buf.getvalue()

    def test_nothing_is_for_sale_by_default(self):
        """Consentimento é a pessoa mover carga, não o servidor decidir."""
        eu = self._player()
        room = self._room(eu)
        self._join(eu, room["id"], data=self._com_armazem())
        r = self.client.get(f"/api/v1/rooms/{room['id']}/shop",
                            headers=self._auth(eu))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIsNone(r.json()["shopStorageId"])

    def test_the_storages_come_from_the_stored_save(self):
        """O servidor não adivinha o que há na nave: lê o que foi devolvido."""
        eu = self._player()
        room = self._room(eu)
        self._join(eu, room["id"], data=self._com_armazem())
        armazens = self.client.get(f"/api/v1/rooms/{room['id']}/shop",
                                   headers=self._auth(eu)).json()["storages"]
        ids = {a["id"] for a in armazens}
        self.assertEqual(ids, {"435", "608"})
        self.assertNotIn("900", ids, "ofereceu o insumo de uma máquina")

    def test_choosing_a_storage_opens_the_shop(self):
        eu = self._player()
        room = self._room(eu)
        self._join(eu, room["id"], data=self._com_armazem())
        r = self.client.put(f"/api/v1/rooms/{room['id']}/shop",
                            json={"storageId": "435"}, headers=self._auth(eu))
        self.assertEqual(r.status_code, 200, r.text)
        estado = self.client.get(f"/api/v1/rooms/{room['id']}/shop",
                                 headers=self._auth(eu)).json()
        self.assertEqual(estado["shopStorageId"], "435")
        loja = [a for a in estado["storages"] if a["isShop"]][0]
        self.assertEqual(loja["resources"], {"712": 25})

    def test_a_storage_that_is_not_there_is_refused_with_the_list(self):
        """Aceitar um id inventado daria uma loja que nunca enche, e a pessoa
        passaria a sessão sem entender por que ninguém compra dela."""
        eu = self._player()
        room = self._room(eu)
        self._join(eu, room["id"], data=self._com_armazem())
        r = self.client.put(f"/api/v1/rooms/{room['id']}/shop",
                            json={"storageId": "999"}, headers=self._auth(eu))
        self.assertEqual(r.status_code, 400)
        detalhe = r.json()["detail"]
        self.assertIn("435", detalhe)
        self.assertIn("608", detalhe)

    def test_a_machine_cannot_be_made_a_shop(self):
        """Vender o insumo de um produtor é vender o combustível do motor."""
        eu = self._player()
        room = self._room(eu)
        self._join(eu, room["id"], data=self._com_armazem())
        r = self.client.put(f"/api/v1/rooms/{room['id']}/shop",
                            json={"storageId": "900"}, headers=self._auth(eu))
        self.assertEqual(r.status_code, 400)

    def test_the_shop_can_be_closed_again(self):
        eu = self._player()
        room = self._room(eu)
        self._join(eu, room["id"], data=self._com_armazem())
        self.client.put(f"/api/v1/rooms/{room['id']}/shop",
                        json={"storageId": "435"}, headers=self._auth(eu))
        r = self.client.put(f"/api/v1/rooms/{room['id']}/shop",
                            json={"storageId": None}, headers=self._auth(eu))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIsNone(r.json()["shopStorageId"])

    def test_only_members_have_a_shop(self):
        forasteiro, dono = self._player(), self._player()
        room = self._room(dono)
        self._join(dono, room["id"], data=self._com_armazem())
        r = self.client.get(f"/api/v1/rooms/{room['id']}/shop",
                            headers=self._auth(forasteiro))
        self.assertEqual(r.status_code, 403)

    # -- vizinhos no setor -------------------------------------------------

    def _com_casco(self, **kw) -> bytes:
        """Um save com uma nave NPC viva de onde montar a vitrine."""
        import io as _io, zipfile as _zip
        # Uma NPC VIVA, com tripulação: é dela que a vitrine é feita. Um casco
        # de destroço faria a vitrine aparecer como sucata desmontável.
        xml = synthetic.build_game(
            ships=[synthetic.default_player_ship(),
                   synthetic.npc_trader_ship()], **kw)
        buf = _io.BytesIO()
        with _zip.ZipFile(buf, "w") as zf:
            zf.writestr("game", xml)
            zf.writestr("info", f'<info version="21" date="{synthetic.FRESH_DATE}"/>')
        return buf.getvalue()

    def _naves(self, data: bytes) -> list:
        from sgalaxy.savefile import SaveFile
        with blobs.with_unpacked(data) as folder:
            return [s.get("sname") for _d, s in SaveFile(folder).ships()]

    def test_a_neighbour_in_the_same_system_shows_up(self):
        """O momento que vende o projeto: a loja de alguém no teu setor."""
        vizinha, eu = self._player(), self._player()
        room = self._room(vizinha)
        self._join(vizinha, room["id"], data=self._com_casco())
        self._join(eu, room["id"], data=self._com_casco())

        r = self._checkout(eu, room["id"])
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.headers.get("x-neighbours"), "1")
        nomes = self._naves(r.content)
        self.assertTrue(any(vizinha["name"] in (n or "") for n in nomes),
                        f"a vitrine não apareceu: {nomes}")

    def test_the_storefront_carries_the_account_not_just_the_ship(self):
        """Findings item 20: o nome da nave é texto livre e mutável.

        Se a vitrine só mostrasse o nome da nave, bastaria alguém renomear a
        sua para se passar por outro — dentro do jogo, onde custa mais.
        """
        vizinha, eu = self._player(), self._player()
        room = self._room(vizinha)
        self._join(vizinha, room["id"], data=self._com_casco())
        self._join(eu, room["id"], data=self._com_casco())
        nomes = self._naves(self._checkout(eu, room["id"]).content)
        vitrine = [n for n in nomes if n and vizinha["name"] in n][0]
        self.assertIn("Homestead", vitrine, "perdeu o nome da nave")
        self.assertIn(vizinha["name"], vitrine, "perdeu a conta")

    def test_a_storefront_never_becomes_part_of_your_game(self):
        """O par obrigatório: o que foi montado tem que sair na devolução.

        Sem isto a nave do vizinho seria guardada como canônica, voltaria na
        próxima retirada, e empilharia uma a cada sessão.
        """
        vizinha, eu = self._player(), self._player()
        room = self._room(vizinha)
        self._join(vizinha, room["id"], data=self._com_casco())
        self._join(eu, room["id"], data=self._com_casco())
        entregue = self._checkout(eu, room["id"]).content
        self.assertEqual(len(self._naves(entregue)), 3, "não montou a vitrine")

        r = self.client.post(f"/api/v1/rooms/{room['id']}/checkin",
                             content=entregue, headers=self._auth(eu))
        self.assertEqual(r.status_code, 200, r.text)
        with db.pool().connection() as conn:
            sha = conn.execute("SELECT sha256 FROM save_version WHERE id = %s",
                               (r.json()["versionId"],)).fetchone()["sha256"]
        guardado = self._naves(store().get(sha))
        self.assertEqual(len(guardado), 2,
                         f"a vitrine ficou guardada na partida: {guardado}")

    def test_storefronts_do_not_stack_across_sessions(self):
        """A consequência de esquecer a remoção, virada teste."""
        vizinha, eu = self._player(), self._player()
        room = self._room(vizinha)
        self._join(vizinha, room["id"], data=self._com_casco())
        self._join(eu, room["id"], data=self._com_casco())
        for _volta in range(3):
            entregue = self._checkout(eu, room["id"]).content
            self.assertEqual(len(self._naves(entregue)), 3,
                             "acumulou vitrine entre sessões")
            self.client.post(f"/api/v1/rooms/{room['id']}/checkin",
                             content=entregue, headers=self._auth(eu))

    def test_the_checkout_says_which_ships_it_assembled(self):
        """O mod precisa distinguir a vitrine de um NPC de verdade.

        O jogo só sabe chamar o jogador por FACÇÃO, nunca por nave (medido em
        `Communication.npcHailsPlayer(FactionSide)`). Sem esta lista, calar a
        vitrine calaria também os encontros que o próprio jogo criou.
        """
        vizinha, eu = self._player(), self._player()
        room = self._room(vizinha)
        self._join(vizinha, room["id"], data=self._com_casco())
        self._join(eu, room["id"], data=self._com_casco())

        r = self._checkout(eu, room["id"])
        sids = r.headers.get("x-neighbour-sids", "")
        self.assertTrue(sids, "o checkout não disse o que montou")
        naves_no_zip = self._naves(r.content)
        self.assertEqual(len(sids.split(",")), 1)
        self.assertEqual(len(naves_no_zip), 3)

    def test_the_checkout_tells_the_mod_which_storage_is_the_shop(self):
        """A metade que faltava: o canal tem que ser de ida E volta.

        Sem isto o botão no jogo esqueceria, a cada sessão, o que foi escolhido
        na anterior — e mostraria SET AS SHOP num armazém que já é a loja.
        """
        eu = self._player()
        room = self._room(eu)
        self._join(eu, room["id"], data=self._com_armazem())
        self.client.put(f"/api/v1/rooms/{room['id']}/shop",
                        json={"storageId": "435"}, headers=self._auth(eu))

        r = self._checkout(eu, room["id"])
        self.assertEqual(r.headers.get("x-shop-storage"), "435")

    def test_with_no_shop_the_header_is_empty(self):
        eu = self._player()
        room = self._room(eu)
        self._join(eu, room["id"], data=self._com_armazem())
        r = self._checkout(eu, room["id"])
        self.assertEqual(r.headers.get("x-shop-storage"), "")

    def test_with_no_neighbours_the_list_is_empty(self):
        """Lista velha faria o mod calar naves que não são mais nossas."""
        eu = self._player()
        room = self._room(eu)
        self._join(eu, room["id"], data=self._com_casco())
        r = self._checkout(eu, room["id"])
        self.assertEqual(r.headers.get("x-neighbour-sids", ""), "")

    def test_nobody_from_another_system_appears(self):
        longe, eu = self._player(), self._player()
        room = self._room(longe)
        self._join(longe, room["id"], data=self._com_casco())
        self._join(eu, room["id"], data=self._com_casco())
        with db.pool().connection() as conn:
            conn.execute("UPDATE membership SET at_system = '99' "
                         "WHERE room_id = %s AND player_id = %s",
                         (room["id"], longe["playerId"]))
        r = self._checkout(eu, room["id"])
        self.assertEqual(r.headers.get("x-neighbours"), "0")

    def test_a_save_with_no_hull_still_checks_out(self):
        """Sem casco não há vitrine — e isso não pode custar a sessão."""
        vizinha, eu = self._player(), self._player()
        room = self._room(vizinha)
        self._join(vizinha, room["id"], data=self._com_casco())
        self._join(eu, room["id"])            # sem casco nenhum
        r = self._checkout(eu, room["id"])
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.headers.get("x-neighbours"), "0")

    # -- descoberta compartilhada -----------------------------------------

    def _explorado(self, **kw) -> bytes:
        """Um save de alguém que esteve no asteroide inicial."""
        import io as _io, zipfile as _zip
        xml = synthetic.build_game(**kw).replace(
            '<info visited="false" isVisible="false" isst="1"/>',
            '<info visited="true" isVisible="true" isst="1"/>')
        buf = _io.BytesIO()
        with _zip.ZipFile(buf, "w") as zf:
            zf.writestr("game", xml)
            zf.writestr("info", f'<info version="21" date="{synthetic.FRESH_DATE}"/>')
        return buf.getvalue()

    def _visitados_no_zip(self, data: bytes) -> int:
        from sgalaxy import discovery
        from sgalaxy.savefile import SaveFile
        with blobs.with_unpacked(data) as folder:
            return len(discovery.visited(SaveFile(folder)))

    def test_the_room_learns_where_someone_has_been(self):
        dono = self._player()
        room = self._room(dono)
        r = self._join(dono, room["id"], data=self._explorado())
        self.assertEqual(r.status_code, 200, r.text)
        with db.pool().connection() as conn:
            self.assertEqual(db.count_discoveries(conn, room["id"]), 1)

    def test_a_newcomer_receives_the_rooms_travels(self):
        """O ponto todo: quem nunca foi lá recebe o lugar cartografado."""
        veterano, novato = self._player(), self._player()
        room = self._room(veterano)
        self._join(veterano, room["id"], data=self._explorado())
        self._join(novato, room["id"])          # nunca visitou nada

        r = self.client.post(f"/api/v1/rooms/{room['id']}/checkout",
                             headers=self._auth(novato))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self._visitados_no_zip(r.content), 1,
                         "o save entregue não trouxe a descoberta da sala")

    def test_what_is_stored_is_not_rewritten(self):
        """A descoberta entra no que sai, não no que fica guardado."""
        veterano, novato = self._player(), self._player()
        room = self._room(veterano)
        self._join(veterano, room["id"], data=self._explorado())
        entrada = self._join(novato, room["id"]).json()

        self.client.post(f"/api/v1/rooms/{room['id']}/checkout",
                         headers=self._auth(novato))
        with db.pool().connection() as conn:
            sha = conn.execute("SELECT sha256 FROM save_version WHERE id = %s",
                               (entrada["versionId"],)).fetchone()["sha256"]
        self.assertEqual(self._visitados_no_zip(store().get(sha)), 0,
                         "reescreveu a versão guardada do jogador")

    def test_the_galaxy_still_matches_after_sharing(self):
        """A impressão digital conta ESTRELAS justamente para sobreviver a isto.

        Se mudasse, o save entregue voltaria e seria recusado na devolução —
        e o jogador perderia a sessão por causa de um enfeite coletivo.
        """
        veterano, novato = self._player(), self._player()
        room = self._room(veterano)
        self._join(veterano, room["id"], data=self._explorado())
        self._join(novato, room["id"])
        entregue = self.client.post(f"/api/v1/rooms/{room['id']}/checkout",
                                    headers=self._auth(novato)).content

        r = self.client.post(f"/api/v1/rooms/{room['id']}/checkin",
                             content=entregue, headers=self._auth(novato))
        self.assertEqual(r.status_code, 200, r.text)

    def test_a_checkpoint_shares_discovery_during_the_session(self):
        """Descobrir aparece para os outros durante a sessão, não só no fim."""
        dono = self._player()
        room = self._room(dono)
        self._join(dono, room["id"])
        self._checkout(dono, room["id"])
        with db.pool().connection() as conn:
            self.assertEqual(db.count_discoveries(conn, room["id"]), 0)

        r = self._checkpoint(dono, room["id"], data=self._explorado())
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["discovered"], 1)

    def test_the_first_to_chart_a_place_keeps_it(self):
        """Ninguém é creditado duas vezes pela mesma pedra."""
        a, b = self._player(), self._player()
        room = self._room(a)
        self._join(a, room["id"], data=self._explorado())
        self._join(b, room["id"], data=self._explorado())
        with db.pool().connection() as conn:
            linha = conn.execute(
                "SELECT first_by FROM room_body WHERE room_id = %s",
                (room["id"],)).fetchone()
            self.assertEqual(db.count_discoveries(conn, room["id"]), 1)
        self.assertEqual(linha["first_by"], a["playerId"])

    # -- checkpoint: o autosave chega ao servidor no meio da sessao -------

    def _checkout(self, player, room_id):
        return self.client.post(f"/api/v1/rooms/{room_id}/checkout",
                                headers=self._auth(player))

    def _checkpoint(self, player, room_id, data=None):
        return self.client.post(
            f"/api/v1/rooms/{room_id}/checkpoint",
            content=data if data is not None else _save_zip(age_days=3.0),
            headers=self._auth(player))

    def test_a_checkpoint_is_stored_without_ending_the_session(self):
        """O ponto todo: chegar ao servidor sem entregar a vez."""
        dono = self._player()
        room = self._room(dono)
        self._join(dono, room["id"])
        self._checkout(dono, room["id"])

        r = self._checkpoint(dono, room["id"])
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["ageDays"], 3.0)

        with db.pool().connection() as conn:
            versao = conn.execute(
                "SELECT kind FROM save_version WHERE id = %s",
                (r.json()["versionId"],)).fetchone()
            emprestimo = conn.execute(
                "SELECT state FROM lease WHERE room_id = %s AND player_id = %s",
                (room["id"], dono["playerId"])).fetchone()
        self.assertEqual(versao["kind"], "checkpoint")
        self.assertEqual(emprestimo["state"], "open",
                         "o checkpoint fechou o empréstimo; ele não entrega a vez")

    def test_a_checkpoint_does_not_become_the_canonical(self):
        """Quem decide o que fica é o `checkin`. Trocar isso quebraria a regra
        de uma sessão por vez: bastaria autosalvar para publicar."""
        dono = self._player()
        room = self._room(dono)
        entrada = self._join(dono, room["id"]).json()
        self._checkout(dono, room["id"])
        self._checkpoint(dono, room["id"])

        with db.pool().connection() as conn:
            canonica = conn.execute(
                "SELECT canonical_id FROM membership WHERE room_id = %s AND player_id = %s",
                (room["id"], dono["playerId"])).fetchone()["canonical_id"]
        self.assertEqual(canonica, entrada["versionId"],
                         "o checkpoint virou canônico")

    def test_a_checkpoint_moves_the_player_on_the_map(self):
        """É metade da razão de existir: a sala anda durante a sessão."""
        dono = self._player()
        room = self._room(dono)
        self._join(dono, room["id"])
        self._checkout(dono, room["id"])
        self._checkpoint(dono, room["id"])

        estado = self.client.get(f"/api/v1/rooms/{room['id']}/state",
                                 headers=self._auth(dono)).json()
        eu = estado["players"][0]
        self.assertEqual((eu["x"], eu["y"]), ("84119", "214759"))

    def test_a_checkpoint_needs_an_open_session(self):
        """Sem empréstimo aberto não há sessão, e sem sessão não há autosave."""
        dono = self._player()
        room = self._room(dono)
        self._join(dono, room["id"])
        r = self._checkpoint(dono, room["id"])
        self.assertEqual(r.status_code, 409)
        self.assertIn("no open lease", r.json()["detail"])

    def test_a_checkpoint_from_another_galaxy_is_refused(self):
        """Seria outra pessoa jogando outra coisa, entrando no mapa desta."""
        dono = self._player()
        room = self._room(dono)
        self._join(dono, room["id"])
        self._checkout(dono, room["id"])
        r = self._checkpoint(dono, room["id"],
                             data=_save_zip(age_days=3.0, galaxy_w=777000))
        self.assertEqual(r.status_code, 409)

    def test_checkin_still_closes_the_session_after_checkpoints(self):
        """O ciclo inteiro tem que continuar valendo com checkpoints no meio."""
        dono = self._player()
        room = self._room(dono)
        self._join(dono, room["id"])
        self._checkout(dono, room["id"])
        self._checkpoint(dono, room["id"], data=_save_zip(age_days=3.0))
        self._checkpoint(dono, room["id"], data=_save_zip(age_days=4.0))

        r = self.client.post(f"/api/v1/rooms/{room['id']}/checkin",
                             content=_save_zip(age_days=5.0),
                             headers=self._auth(dono))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["ageDays"], 5.0)
        with db.pool().connection() as conn:
            estados = [row["state"] for row in conn.execute(
                "SELECT state FROM lease WHERE room_id = %s", (room["id"],))]
        self.assertEqual(estados, ["returned"])

    # -- todo mundo comeca junto -----------------------------------------

    def test_a_new_game_is_accepted(self):
        """O caso normal: partida recém-criada, por volta do dia 1.3."""
        dono = self._player()
        room = self._room(dono)
        r = self._join(dono, room["id"])
        self.assertEqual(r.status_code, 200, r.text)
        self.assertLess(r.json()["ageDays"], 5)

    def test_an_old_colony_is_refused_and_told_why(self):
        """O enxerto preserva nave, tripulação e banco — de propósito.

        Por isso entrar com uma colônia de meio ano é chegar com meio ano de
        vantagem, e isso é decisão da sala, não do save.
        """
        dono, veterano = self._player(), self._player()
        room = self._room(dono)
        self._join(dono, room["id"])
        r = self._join(veterano, room["id"], data=_save_zip(age_days=178.0))
        self.assertEqual(r.status_code, 409)
        detalhe = r.json()["detail"]
        self.assertIn("178", detalhe)
        self.assertIn("new game", detalhe,
                      "recusou sem dizer o que a pessoa deve fazer")

    def test_the_age_rule_runs_before_the_graft(self):
        """Enxerto nenhum conserta idade, e enxertar para depois recusar é
        trabalho jogado fora — de megabytes, no caminho de uma requisição."""
        dono, veterano = self._player(), self._player()
        room = self._room(dono)
        self._join(dono, room["id"])
        r = self._join(veterano, room["id"],
                       data=_save_zip(age_days=178.0, galaxy_w=777000))
        self.assertEqual(r.status_code, 409)
        self.assertIn("days old", r.json()["detail"],
                      "recusou pela galáxia; a idade tinha que vir antes")

    def test_a_room_can_waive_the_rule(self):
        """Uma sala de veteranos pode querer que cada um traga o que tem."""
        dono, veterano = self._player(), self._player()
        room = self._room(dono, maxJoinAgeDays=None)
        self._join(dono, room["id"])
        r = self._join(veterano, room["id"], data=_save_zip(age_days=178.0))
        self.assertEqual(r.status_code, 200, r.text)

    def test_the_owner_can_change_the_rule_later(self):
        dono = self._player()
        room = self._room(dono)
        self.assertEqual(room["maxJoinAgeDays"], 5.0)
        r = self.client.patch(f"/api/v1/rooms/{room['id']}",
                              json={"maxJoinAgeDays": 30},
                              headers=self._auth(dono))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["maxJoinAgeDays"], 30.0)

    def test_age_does_not_limit_playing_only_joining(self):
        """Entrou, joga o quanto quiser: a regra é de entrada, não de estadia."""
        dono = self._player()
        room = self._room(dono)
        self._join(dono, room["id"])
        self.client.post(f"/api/v1/rooms/{room['id']}/checkout",
                         headers=self._auth(dono))
        r = self.client.post(f"/api/v1/rooms/{room['id']}/checkin",
                             content=_save_zip(age_days=200.0),
                             headers=self._auth(dono))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["ageDays"], 200.0)

    def test_a_different_galaxy_is_grafted_instead_of_refused(self):
        """O atrito que fazia alguém desistir: acertar cada opção de cenário.

        O servidor passa a consertar em vez de recusar — enxerta a galáxia da
        sala no save de quem chegou, preservando nave, tripulação e banco.
        """
        dono, forasteiro = self._player(), self._player()
        room = self._room(dono)
        self._join(dono, room["id"])

        outro = _save_zip(galaxy_w=777000)
        r = self._join(forasteiro, room["id"], data=outro)
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertTrue(body["grafted"], "aceitou sem enxertar")
        detalhe = self.client.get(f"/api/v1/rooms/{room['id']}",
                                  headers=self._auth(dono)).json()
        self.assertEqual(body["galaxy"]["digest"], detalhe["galaxyDigest"],
                         "o save guardado não ficou na galáxia da sala")

    def test_without_a_donor_a_different_galaxy_is_still_refused(self):
        """Sem de onde enxertar, a recusa antiga continua — com o motivo."""
        dono, forasteiro = self._player(), self._player()
        room = self._room(dono)
        self._join(dono, room["id"])
        with db.pool().connection() as conn:
            conn.execute("UPDATE room SET galaxy_sha256 = NULL WHERE id = %s",
                         (room["id"],))
        r = self._join(forasteiro, room["id"], data=_save_zip(galaxy_w=777000))
        self.assertEqual(r.status_code, 409)
        self.assertIn("creation option", r.json()["detail"])

    def test_join_twice_is_refused(self):
        player = self._player()
        room = self._room(player)
        self._join(player, room["id"])
        r = self._join(player, room["id"])
        self.assertEqual(r.status_code, 409)
        self.assertIn("already in this room", r.json()["detail"])

    def test_join_respects_the_room_password(self):
        dono, outro = self._player(), self._player()
        room = self._room(dono, password="abrete")
        r = self._join(outro, room["id"])
        self.assertEqual(r.status_code, 403)
        r = self._join(outro, room["id"], headers={"X-Room-Password": "abrete"})
        self.assertEqual(r.status_code, 200, r.text)

    def test_join_refuses_garbage_before_storing_anything(self):
        player = self._player()
        room = self._room(player)
        r = self._join(player, room["id"], data=b"isto nao e um zip")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.client.get("/api/v1/health").json()["storage"]["blobs"], 0,
                         "lixo custou disco numa sala aberta")

    def test_join_refuses_a_zip_without_a_save(self):
        player = self._player()
        room = self._room(player)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("leiame.txt", "oi")
        r = self._join(player, room["id"], data=buf.getvalue())
        self.assertEqual(r.status_code, 400)

    def test_join_refuses_when_the_room_is_full(self):
        dono = self._player()
        room = self._room(dono, maxPlayers=1)
        self._join(dono, room["id"])
        r = self._join(self._player(), room["id"])
        self.assertEqual(r.status_code, 409)
        self.assertIn("the room is full", r.json()["detail"])

    # -- ciclo de sessao ---------------------------------------------------

    def test_full_cycle(self):
        player = self._player()
        room = self._room(player)
        self._join(player, room["id"])

        out = self.client.post(f"/api/v1/rooms/{room['id']}/checkout",
                               headers=self._auth(player))
        self.assertEqual(out.status_code, 200, out.text)
        self.assertEqual(out.headers["content-type"], "application/zip")
        self.assertIn("X-Lease-Expires", out.headers)
        # O que volta é um save de verdade, não um blob qualquer.
        with zipfile.ZipFile(io.BytesIO(out.content)) as zf:
            self.assertIn("game", zf.namelist())

        back = self.client.post(f"/api/v1/rooms/{room['id']}/checkin",
                                content=out.content, headers=self._auth(player))
        self.assertEqual(back.status_code, 200, back.text)
        self.assertIn("stored", back.json()["message"])

    def test_second_checkout_is_blocked_while_open(self):
        """É o que impede duplicação por sessão paralela."""
        player = self._player()
        room = self._room(player)
        self._join(player, room["id"])
        self.client.post(f"/api/v1/rooms/{room['id']}/checkout",
                         headers=self._auth(player))
        r = self.client.post(f"/api/v1/rooms/{room['id']}/checkout",
                             headers=self._auth(player))
        self.assertEqual(r.status_code, 409)
        self.assertIn("already have this save checked out", r.json()["detail"])

    def test_checkin_without_checkout_is_refused(self):
        player = self._player()
        room = self._room(player)
        self._join(player, room["id"])
        r = self.client.post(f"/api/v1/rooms/{room['id']}/checkin",
                             content=_save_zip(), headers=self._auth(player))
        self.assertEqual(r.status_code, 409)
        self.assertIn("Check it out before", r.json()["detail"])

    def test_checkin_of_another_galaxy_is_refused(self):
        player = self._player()
        room = self._room(player)
        self._join(player, room["id"])
        self.client.post(f"/api/v1/rooms/{room['id']}/checkout",
                         headers=self._auth(player))
        r = self.client.post(f"/api/v1/rooms/{room['id']}/checkin",
                             content=_save_zip(galaxy_w=777000), headers=self._auth(player))
        self.assertEqual(r.status_code, 409)
        self.assertIn("not the save that was lent out", r.json()["detail"])

    def test_checkout_requires_membership(self):
        dono, estranho = self._player(), self._player()
        room = self._room(dono)
        self._join(dono, room["id"])
        r = self.client.post(f"/api/v1/rooms/{room['id']}/checkout",
                             headers=self._auth(estranho))
        self.assertEqual(r.status_code, 403)

    def test_expired_lease_frees_a_new_checkout(self):
        """Perder a sessão é o castigo; perder o direito de jogar não é."""
        player = self._player()
        room = self._room(player)
        self._join(player, room["id"])
        self.client.post(f"/api/v1/rooms/{room['id']}/checkout",
                         headers=self._auth(player))
        with db.pool().connection() as conn:
            conn.execute("UPDATE lease SET expires_at = now() - interval '1 hour'")
        r = self.client.post(f"/api/v1/rooms/{room['id']}/checkout",
                             headers=self._auth(player))
        self.assertEqual(r.status_code, 200, r.text)

    def test_identical_save_is_stored_once(self):
        """Retirar e devolver sem jogar não deve custar disco."""
        player = self._player()
        room = self._room(player)
        self._join(player, room["id"])
        antes = self.client.get("/api/v1/health").json()["storage"]["blobs"]
        out = self.client.post(f"/api/v1/rooms/{room['id']}/checkout",
                               headers=self._auth(player))
        self.client.post(f"/api/v1/rooms/{room['id']}/checkin",
                         content=out.content, headers=self._auth(player))
        depois = self.client.get("/api/v1/health").json()["storage"]["blobs"]
        self.assertEqual(antes, depois, "o mesmo save virou dois blobs")

    def test_retention_prunes_but_never_the_canonical(self):
        player = self._player()
        room = self._room(player, retentionN=2)
        self._join(player, room["id"])
        for dia in range(5):
            out = self.client.post(f"/api/v1/rooms/{room['id']}/checkout",
                                   headers=self._auth(player))
            self.client.post(
                f"/api/v1/rooms/{room['id']}/checkin",
                content=_save_zip(id_counter=1000 + dia), headers=self._auth(player))
        with db.pool().connection() as conn:
            versoes = conn.execute(
                "SELECT count(*) AS n FROM save_version").fetchone()["n"]
            canonica = conn.execute(
                """SELECT v.id FROM membership m
                     JOIN save_version v ON v.id = m.canonical_id""").fetchone()
        self.assertLessEqual(versoes, 4, "a janela de retenção não foi aplicada")
        self.assertIsNotNone(canonica, "a versão canônica foi podada")

    def test_health_reports_storage(self):
        r = self.client.get("/api/v1/health")
        self.assertEqual(r.status_code, 200)
        self.assertIn("blobs", r.json()["storage"])


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(HAS_DB, "defina DATABASE_URL para rodar os testes da API")
class PrivacyTestCase(unittest.TestCase):
    """A política de dados promete coisas; estes testes cobram."""

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def setUp(self):
        with db.pool().connection() as conn:
            conn.execute("TRUNCATE lease, membership, save_version, room, "
                         "player RESTART IDENTITY CASCADE")
        import shutil
        from server.api.app import store
        shutil.rmtree(store().root, ignore_errors=True)
        os.makedirs(store().root, exist_ok=True)

    def _player(self):
        return self.client.post("/api/v1/players", json={"name": "Some"}).json()

    def _auth(self, p):
        return {"Authorization": f"Bearer {p['token']}"}

    def _room(self, player, **kw):
        payload = {"seed": "1654267488", "name": "Sala de teste", **kw}
        r = self.client.post("/api/v1/rooms", json=payload,
                             headers=self._auth(player))
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()

    def test_policy_page_is_served_and_says_the_hard_parts(self):
        r = self.client.get("/privacy")
        self.assertEqual(r.status_code, 200)
        for trecho in ("entire savegame", "losing the account",
                       "delete%20everything", "does not pretend", "Bugbyte"):
            self.assertIn(trecho, r.text, f"a política não diz {trecho!r}")

    def test_delete_requires_explicit_confirmation(self):
        player = self._player()
        r = self.client.delete("/api/v1/me", headers=self._auth(player))
        self.assertEqual(r.status_code, 400)
        self.assertIn("delete everything", r.json()["detail"])

    def test_delete_removes_account_saves_and_blobs(self):
        """A promessa de 'apagar tudo e sair' vale se o disco esvaziar."""
        player = self._player()
        room = self.client.post("/api/v1/rooms", json={"seed": "1"},
                                headers=self._auth(player)).json()
        self.client.post(f"/api/v1/rooms/{room['id']}/join",
                         content=_save_zip(), headers=self._auth(player))
        self.assertEqual(self.client.get("/api/v1/health").json()["storage"]["blobs"], 1)

        r = self.client.delete("/api/v1/me?confirm=delete everything",
                               headers=self._auth(player))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["deleted"])
        self.assertEqual(self.client.get("/api/v1/health").json()["storage"]["blobs"], 0,
                         "the save stayed on disk after 'delete everything'")
        # E o token para de funcionar.
        self.assertEqual(
            self.client.get("/api/v1/me", headers=self._auth(player)).status_code, 401)

    def test_delete_does_not_destroy_other_players_saves(self):
        """Sumir com a sala de terceiros para atender ao pedido de um seria
        destruir o save de quem não pediu nada."""
        dono, vizinho = self._player(), self._player()
        room = self.client.post("/api/v1/rooms", json={"seed": "1"},
                                headers=self._auth(dono)).json()
        self.client.post(f"/api/v1/rooms/{room['id']}/join",
                         content=_save_zip(), headers=self._auth(dono))
        self.client.post(f"/api/v1/rooms/{room['id']}/join",
                         content=_save_zip(), headers=self._auth(vizinho))

        r = self.client.delete("/api/v1/me?confirm=delete everything",
                               headers=self._auth(dono))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["roomsKept"], 1)
        # O vizinho continua com o save dele e consegue retirar.
        out = self.client.post(f"/api/v1/rooms/{room['id']}/checkout",
                               headers=self._auth(vizinho))
        self.assertEqual(out.status_code, 200, out.text)

    def test_recipe_is_visible_to_who_wants_to_join(self):
        """Sem a seed não há como criar a partida, e sem partida não há save.

        A primeira versão escondia a receita de não-membros e tornava o fluxo
        de entrada impossível.
        """
        dono, forasteiro = self._player(), self._player()
        room = self._room(dono)
        r = self.client.get(f"/api/v1/rooms/{room['id']}",
                            headers=self._auth(forasteiro))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["seed"], "1654267488",
                         "quem quer entrar não conseguiu ver a seed")

    def test_recipe_of_a_locked_room_needs_the_password(self):
        dono, forasteiro = self._player(), self._player()
        room = self._room(dono, password="abrete")
        r = self.client.get(f"/api/v1/rooms/{room['id']}",
                            headers=self._auth(forasteiro))
        self.assertNotIn("seed", r.json())
        r = self.client.get(f"/api/v1/rooms/{room['id']}",
                            headers={**self._auth(forasteiro),
                                     "X-Room-Password": "abrete"})
        self.assertIn("seed", r.json())

    def test_owner_publishes_the_recipe_afterwards(self):
        """A receita fica completa depois: só ao criar a partida a pessoa sabe
        o nome exato da nave e das opções que marcou."""
        dono = self._player()
        room = self._room(dono)
        r = self.client.patch(f"/api/v1/rooms/{room['id']}",
                              json={"options": {"nave": "Compact",
                                                "dificuldade": "Normal"}},
                              headers=self._auth(dono))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["options"]["nave"], "Compact")

    def test_only_the_owner_changes_the_room(self):
        dono, outro = self._player(), self._player()
        room = self._room(dono)
        r = self.client.patch(f"/api/v1/rooms/{room['id']}",
                              json={"name": "sequestrada"},
                              headers=self._auth(outro))
        self.assertEqual(r.status_code, 403)

    def test_seed_cannot_be_changed(self):
        """Trocar a seed de uma sala com gente dentro invalidaria o save de
        todos de uma vez."""
        dono = self._player()
        room = self._room(dono)
        self.client.patch(f"/api/v1/rooms/{room['id']}",
                          json={"seed": "outra"}, headers=self._auth(dono))
        r = self.client.get(f"/api/v1/rooms/{room['id']}", headers=self._auth(dono))
        self.assertEqual(r.json()["seed"], "1654267488")


@unittest.skipUnless(HAS_DB, "defina DATABASE_URL para rodar os testes da API")
class WebPagesTestCase(unittest.TestCase):
    """As páginas que alguém vê antes de instalar qualquer coisa (2.11)."""

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def setUp(self):
        with db.pool().connection() as conn:
            conn.execute("TRUNCATE lease, membership, save_version, "
                         "galaxy_system, room, player RESTART IDENTITY CASCADE")
        import shutil
        from server.api.app import store
        shutil.rmtree(store().root, ignore_errors=True)
        os.makedirs(store().root, exist_ok=True)

    def _player(self):
        return self.client.post("/api/v1/players", json={"name": "Ana"}).json()

    def _auth(self, p):
        return {"Authorization": f"Bearer {p['token']}"}

    def test_index_lists_rooms_without_an_account(self):
        player = self._player()
        self.client.post("/api/v1/rooms", json={"seed": "1", "name": "Fronteira"},
                         headers=self._auth(player))
        r = self.client.get("/")          # sem cabeçalho de autenticação
        self.assertEqual(r.status_code, 200)
        self.assertIn("Fronteira", r.text)
        self.assertIn("Bugbyte", r.text, "faltou o aviso legal")

    def test_room_page_shows_the_recipe_and_the_players(self):
        player = self._player()
        room = self.client.post("/api/v1/rooms",
                                json={"seed": "1654267488", "name": "Fronteira",
                                      "options": {"nave": "Compact"}},
                                headers=self._auth(player)).json()
        self.client.post(f"/api/v1/rooms/{room['id']}/join",
                         content=_save_zip(), headers=self._auth(player))
        r = self.client.get(f"/room/{room['id']}")
        self.assertEqual(r.status_code, 200)
        self.assertIn("1654267488", r.text, "a receita não apareceu")
        self.assertIn("Compact", r.text)
        self.assertIn("Homestead", r.text, "a nave do jogador não apareceu")

    def test_room_page_draws_the_map_after_the_first_join(self):
        player = self._player()
        room = self.client.post("/api/v1/rooms", json={"seed": "1"},
                                headers=self._auth(player)).json()
        antes = self.client.get(f"/room/{room['id']}").text
        self.assertNotIn("<svg", antes, "desenhou mapa sem galáxia definida")

        self.client.post(f"/api/v1/rooms/{room['id']}/join",
                         content=_save_zip(), headers=self._auth(player))
        depois = self.client.get(f"/room/{room['id']}").text
        self.assertIn("<svg", depois, "não desenhou o mapa depois do primeiro save")

    def test_locked_room_does_not_publish_the_seed_on_the_web(self):
        """A página é pública; a receita de uma sala com senha não é."""
        player = self._player()
        room = self.client.post("/api/v1/rooms",
                                json={"seed": "SEGREDO123", "password": "x"},
                                headers=self._auth(player)).json()
        r = self.client.get(f"/room/{room['id']}")
        self.assertNotIn("SEGREDO123", r.text)

    def test_unknown_room_is_a_clean_404(self):
        self.assertEqual(self.client.get("/room/NOSUCHROOM").status_code, 404)

    def test_room_name_is_escaped(self):
        """Nome de sala é texto de quem criou, e a página é pública."""
        player = self._player()
        room = self.client.post(
            "/api/v1/rooms",
            json={"seed": "1", "name": "<script>alert(1)</script>"},
            headers=self._auth(player)).json()
        r = self.client.get(f"/room/{room['id']}")
        self.assertNotIn("<script>alert(1)</script>", r.text)
        self.assertIn("&lt;script&gt;", r.text)

    def test_map_marks_only_systems_the_room_actually_visited(self):
        """Visitado é o que o servidor registrou, não o que tem nome.

        A versão anterior usava 'sistema nomeado' como proxy de visitado, e o
        jogo nomeia todos de uma vez — o mapa inteiro acendia (findings 15).
        """
        player = self._player()
        room = self.client.post("/api/v1/rooms", json={"seed": "1"},
                                headers=self._auth(player)).json()
        self.client.post(f"/api/v1/rooms/{room['id']}/join",
                         content=_save_zip(), headers=self._auth(player))
        with db.pool().connection() as conn:
            visitas = conn.execute(
                "SELECT system_id, x, y FROM room_visit WHERE room_id = %s",
                (room["id"],)).fetchall()
        self.assertEqual(len(visitas), 1, "registrou visita a mais de um sistema")
        self.assertEqual(visitas[0]["system_id"], "6")
        self.assertEqual((visitas[0]["x"], visitas[0]["y"]), ("84119", "214759"))

        # O molde tem um sistema só, e o jogador está nele — vira marcador de
        # jogador, não ponto visitado. O destaque em si é testado à parte, em
        # tests/test_map.py, sem precisar de banco.

    def test_every_system_has_a_hover_target(self):
        """Um ponto de 1,8px é quase impossível de acertar com o mouse."""
        player = self._player()
        room = self.client.post("/api/v1/rooms", json={"seed": "1"},
                                headers=self._auth(player)).json()
        self.client.post(f"/api/v1/rooms/{room['id']}/join",
                         content=_save_zip(), headers=self._auth(player))
        page = self.client.get(f"/room/{room['id']}").text
        self.assertIn('fill="transparent"', page,
                      "não há área de captura para o hover")

    def test_room_cap_can_go_well_past_eight(self):
        """O limite de 8 era arbitrário; o real é por setor, não por sala."""
        player = self._player()
        r = self.client.post("/api/v1/rooms",
                             json={"seed": "1", "maxPlayers": 200},
                             headers=self._auth(player))
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual(r.json()["maxPlayers"], 200)


@unittest.skipUnless(HAS_DB, "defina DATABASE_URL para rodar os testes da API")
class WebOnboardingTestCase(unittest.TestCase):
    """Registrar e criar sala pelo navegador, sem instalar nada (2.11)."""

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def setUp(self):
        with db.pool().connection() as conn:
            conn.execute("TRUNCATE lease, membership, save_version, room_visit,"
                         " galaxy_system, room, player RESTART IDENTITY CASCADE")

    def test_register_by_form_shows_the_code_once(self):
        r = self.client.post("/register", data={"name": "Ana"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn("Ana", r.text)
        self.assertIn("recovery code", r.text.lower())
        self.assertIn("losing it means losing", r.text)

    def test_registering_signs_you_in(self):
        self.client.post("/register", data={"name": "Ana"})
        r = self.client.get("/new-room")
        self.assertIn("Ana", r.text, "não reconheceu quem acabou de registrar")
        self.assertNotIn("You need an account", r.text)

    def test_the_session_cookie_is_locked_down(self):
        """O token no cookie fora do alcance de script e de POST de outro site."""
        r = self.client.post("/register", data={"name": "Ana"})
        raw = r.headers.get("set-cookie", "")
        self.assertIn("httponly", raw.lower())
        self.assertIn("samesite=strict", raw.lower())

    def test_new_room_needs_an_account(self):
        r = self.client.get("/new-room")
        self.assertIn("You need an account", r.text)

    def test_create_room_by_form_and_land_on_it(self):
        self.client.post("/register", data={"name": "Ana"})
        r = self.client.post("/new-room",
                             data={"name": "Frontier", "seed": "1654267488"},
                             follow_redirects=True)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn("Frontier", r.text)
        self.assertIn("1654267488", r.text, "a receita não apareceu")
        self.assertIn("upload your game", r.text.lower(),
                      "não diz ao dono qual é o próximo passo")

    def test_the_room_belongs_to_who_created_it(self):
        self.client.post("/register", data={"name": "Ana"})
        self.client.post("/new-room", data={"name": "R", "seed": "1"})
        with db.pool().connection() as conn:
            dono = conn.execute(
                """SELECT p.display_name FROM room r
                     JOIN player p ON p.id = r.owner_id""").fetchone()
        self.assertEqual(dono["display_name"], "Ana")

    def test_a_room_without_a_seed_is_refused_with_the_form_back(self):
        self.client.post("/register", data={"name": "Ana"})
        r = self.client.post("/new-room", data={"name": "R", "seed": "  "})
        self.assertEqual(r.status_code, 400)
        self.assertIn("seed is required", r.text)
        self.assertIn("<form", r.text, "perdeu o formulário na recusa")

    def test_the_room_quota_holds_on_the_web_too(self):
        from server.domain.rules import MAX_ROOMS_PER_PLAYER
        self.client.post("/register", data={"name": "Ana"})
        for i in range(MAX_ROOMS_PER_PLAYER):
            self.client.post("/new-room", data={"name": f"R{i}", "seed": "1"})
        r = self.client.post("/new-room", data={"name": "extra", "seed": "1"})
        self.assertEqual(r.status_code, 403)
        self.assertIn("limit", r.text.lower())

    def test_the_front_page_offers_the_way_in(self):
        r = self.client.get("/")
        self.assertIn("/register", r.text)
