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
    from server.api.app import app
    from tests import synthetic


def _save_zip(**kwargs) -> bytes:
    """Um savegame sintético compactado, como o cliente mandaria."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("game", synthetic.build_game(**kwargs))
        zf.writestr("info", '<info version="21" date="3289920"/>')
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
        self.assertIn("não há como recuperá-lo", r.json()["detail"])

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
        self.assertIn("limite", r.json()["detail"])

    # -- entrada -----------------------------------------------------------

    def test_join_adopts_the_save_and_defines_the_galaxy(self):
        player = self._player()
        room = self._room(player)
        r = self._join(player, room["id"])
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertIn("canônico", body["message"])
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

    def test_different_galaxy_is_refused_with_the_likely_cause(self):
        dono, forasteiro = self._player(), self._player()
        room = self._room(dono)
        self._join(dono, room["id"])
        # Outra galáxia de verdade: o tamanho do mapa entra na impressão
        # digital. Mudar `pa` não serviria — ele é referência, não parâmetro de
        # geração, e fica de fora do digest de propósito.
        outro = _save_zip(galaxy_w=777000)
        r = self._join(forasteiro, room["id"], data=outro)
        self.assertEqual(r.status_code, 409)
        self.assertIn("opção de criação", r.json()["detail"])

    def test_join_twice_is_refused(self):
        player = self._player()
        room = self._room(player)
        self._join(player, room["id"])
        r = self._join(player, room["id"])
        self.assertEqual(r.status_code, 409)
        self.assertIn("já está nesta sala", r.json()["detail"])

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
        self.assertIn("cheia", r.json()["detail"])

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
        self.assertIn("guardado", back.json()["message"])

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
        self.assertIn("já está com este save retirado", r.json()["detail"])

    def test_checkin_without_checkout_is_refused(self):
        player = self._player()
        room = self._room(player)
        self._join(player, room["id"])
        r = self.client.post(f"/api/v1/rooms/{room['id']}/checkin",
                             content=_save_zip(), headers=self._auth(player))
        self.assertEqual(r.status_code, 409)
        self.assertIn("Retire antes", r.json()["detail"])

    def test_checkin_of_another_galaxy_is_refused(self):
        player = self._player()
        room = self._room(player)
        self._join(player, room["id"])
        self.client.post(f"/api/v1/rooms/{room['id']}/checkout",
                         headers=self._auth(player))
        r = self.client.post(f"/api/v1/rooms/{room['id']}/checkin",
                             content=_save_zip(galaxy_w=777000), headers=self._auth(player))
        self.assertEqual(r.status_code, 409)
        self.assertIn("não é o save que foi emprestado", r.json()["detail"])

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
        r = self.client.get("/privacidade")
        self.assertEqual(r.status_code, 200)
        for trecho in ("savegame inteiro", "perde a conta", "apagar tudo",
                       "não finge", "Bugbyte"):
            self.assertIn(trecho, r.text, f"a política não diz {trecho!r}")

    def test_delete_requires_explicit_confirmation(self):
        player = self._player()
        r = self.client.delete("/api/v1/me", headers=self._auth(player))
        self.assertEqual(r.status_code, 400)
        self.assertIn("apagar tudo", r.json()["detail"])

    def test_delete_removes_account_saves_and_blobs(self):
        """A promessa de 'apagar tudo e sair' vale se o disco esvaziar."""
        player = self._player()
        room = self.client.post("/api/v1/rooms", json={"seed": "1"},
                                headers=self._auth(player)).json()
        self.client.post(f"/api/v1/rooms/{room['id']}/join",
                         content=_save_zip(), headers=self._auth(player))
        self.assertEqual(self.client.get("/api/v1/health").json()["storage"]["blobs"], 1)

        r = self.client.delete("/api/v1/me?confirm=apagar tudo",
                               headers=self._auth(player))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["deleted"])
        self.assertEqual(self.client.get("/api/v1/health").json()["storage"]["blobs"], 0,
                         "o save continuou no disco depois de 'apagar tudo'")
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

        r = self.client.delete("/api/v1/me?confirm=apagar tudo",
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
