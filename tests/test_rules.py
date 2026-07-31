"""
Testes das regras da custódia.

São as decisões que determinam o que acontece com o save de alguém: quem pode
retirar, quem pode devolver, o que pode ser apagado, e que save entra numa sala.
Cada uma delas errada tem consequência concreta — jogador sem save, sessão
duplicada, ou entrada recusada sem motivo.

    python3 -m unittest tests.test_rules -v
"""

from __future__ import annotations

import datetime as dt
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.domain import rules  # noqa: E402

AGORA = dt.datetime(2026, 7, 31, 12, 0, tzinfo=dt.timezone.utc)


class IdentityTestCase(unittest.TestCase):

    def test_tokens_are_unique_and_long(self):
        tokens = {rules.new_token() for _ in range(200)}
        self.assertEqual(len(tokens), 200, "houve colisão de token")
        self.assertGreaterEqual(len(tokens.pop()), 50)

    def test_hash_is_stable_and_tolerates_whitespace(self):
        token = rules.new_token()
        self.assertEqual(rules.hash_token(token), rules.hash_token(f"  {token}\n"))

    def test_hash_does_not_leak_the_token(self):
        token = rules.new_token()
        self.assertNotIn(token, rules.hash_token(token))

    def test_recovery_code_round_trip(self):
        """O código é copiado de um papel; tem que voltar mesmo mal digitado."""
        token = rules.new_token()
        code = rules.recovery_code(token)
        self.assertIn("-", code)
        self.assertEqual(rules.parse_recovery_code(code), token)
        self.assertEqual(rules.parse_recovery_code(code.lower()), token)
        self.assertEqual(rules.parse_recovery_code(f" {code} "), token)


class RoomTestCase(unittest.TestCase):

    def test_room_ids_avoid_vowels_and_lookalikes(self):
        """Id ditado em voz alta e digitado de volta, sem virar palavra."""
        for _ in range(100):
            rid = rules.new_room_id()
            self.assertEqual(len(rid), rules.ROOM_ID_LEN)
            self.assertFalse(set(rid) & set("AEIOU01IL"),
                             f"{rid} tem caractere ambíguo ou vogal")

    def test_room_quota(self):
        ok, _ = rules.can_create_room(0, blocked=False)
        self.assertTrue(ok)
        ok, motivo = rules.can_create_room(rules.MAX_ROOMS_PER_PLAYER, blocked=False)
        self.assertFalse(ok)
        self.assertIn("limit", motivo)
        ok, motivo = rules.can_create_room(0, blocked=True)
        self.assertFalse(ok)
        self.assertIn("blocked", motivo)


class JoinTestCase(unittest.TestCase):

    def test_first_save_defines_the_galaxy(self):
        ok, _ = rules.check_join({"digest": "abc123", "saveVersion": "21"},
                                 {"galaxy_digest": None, "save_version": None})
        self.assertTrue(ok)

    def test_matching_galaxy_is_accepted(self):
        ok, _ = rules.check_join({"digest": "abc123", "saveVersion": "21"},
                                 {"galaxy_digest": "abc123", "save_version": "21"})
        self.assertTrue(ok)

    def test_wrong_galaxy_is_refused_with_the_likely_cause(self):
        ok, motivo = rules.check_join(
            {"digest": "outra", "saveVersion": "21"},
            {"galaxy_digest": "abc123", "save_version": "21"})
        self.assertFalse(ok)
        self.assertIn("creation option", motivo)

    def test_wrong_save_format_is_refused_before_the_galaxy(self):
        """Jogo atualizado é outro problema, e merece outra mensagem."""
        ok, motivo = rules.check_join(
            {"digest": "abc123", "saveVersion": "22"},
            {"galaxy_digest": "abc123", "save_version": "21"})
        self.assertFalse(ok)
        self.assertIn("updated", motivo)


class LeaseTestCase(unittest.TestCase):

    def _lease(self, horas_restantes: float, state: str = "open") -> dict:
        return {"state": state,
                "expires_at": AGORA + dt.timedelta(hours=horas_restantes)}

    def test_expiry_uses_room_setting(self):
        self.assertEqual(rules.lease_expiry(AGORA, 12),
                         AGORA + dt.timedelta(hours=12))

    def test_checkout_is_free_when_nothing_is_open(self):
        ok, _ = rules.can_checkout(None, AGORA)
        self.assertTrue(ok)

    def test_checkout_is_blocked_while_a_lease_is_open(self):
        """É o que impede duplicação por sessão paralela."""
        ok, motivo = rules.can_checkout(self._lease(3), AGORA)
        self.assertFalse(ok)
        self.assertIn("3.0h", motivo)

    def test_expired_lease_does_not_block_a_new_checkout(self):
        """Perder a sessão é o castigo; perder o direito de jogar não é."""
        ok, _ = rules.can_checkout(self._lease(-1), AGORA)
        self.assertTrue(ok)

    def test_checkin_needs_an_open_lease(self):
        ok, motivo = rules.can_checkin(None, AGORA)
        self.assertFalse(ok)
        self.assertIn("Check it out before", motivo)

    def test_checkin_within_the_window(self):
        ok, _ = rules.can_checkin(self._lease(2), AGORA)
        self.assertTrue(ok)

    def test_checkin_after_expiry_is_refused_and_says_so(self):
        ok, motivo = rules.can_checkin(self._lease(-2.5), AGORA)
        self.assertFalse(ok)
        self.assertIn("2.5h", motivo)
        self.assertIn("reverted to the", motivo)

    def test_checkin_twice_is_refused(self):
        ok, motivo = rules.can_checkin(self._lease(2, state="returned"), AGORA)
        self.assertFalse(ok)
        self.assertIn("already been returned", motivo)


class RetentionTestCase(unittest.TestCase):

    def _versions(self, n: int) -> list:
        return [{"id": i, "sha256": f"{i:064d}"} for i in range(n, 0, -1)]

    def test_keeps_the_window(self):
        podar = rules.versions_to_prune(self._versions(30), 20, set())
        self.assertEqual(len(podar), 10)
        self.assertEqual([v["id"] for v in podar], list(range(10, 0, -1)),
                         "podou as versões erradas; deveria sair a mais antiga")

    def test_keeps_everything_below_the_window(self):
        self.assertEqual(rules.versions_to_prune(self._versions(5), 20, set()), [])

    def test_never_prunes_protected_versions(self):
        """A canônica e a emprestada nunca saem, mesmo fora da janela."""
        versions = self._versions(30)
        protegidas = {1, 2}
        podar = rules.versions_to_prune(versions, 20, protegidas)
        self.assertFalse(protegidas & {v["id"] for v in podar},
                         "podou uma versão protegida — isso deixa jogador sem save")

    def test_protected_versions_do_not_consume_the_window(self):
        """Proteger a canônica antiga não pode encurtar o histórico recente."""
        versions = self._versions(25)
        podar = rules.versions_to_prune(versions, 20, {1})
        mantidas = {v["id"] for v in versions} - {v["id"] for v in podar}
        self.assertIn(1, mantidas)
        self.assertGreaterEqual(len(mantidas), 21)

    def test_live_hashes_covers_every_version(self):
        versions = self._versions(3)
        self.assertEqual(rules.live_hashes(versions),
                         {v["sha256"] for v in versions})


if __name__ == "__main__":
    unittest.main()
