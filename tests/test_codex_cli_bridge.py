import unittest

import codex_cli_bridge


class TestCodexCliBridge(unittest.TestCase):
    def test_clamp_detail_collapses_whitespace(self):
        s = "hello\n   world\t\t!"
        self.assertEqual(codex_cli_bridge.clamp_detail(s, 100), "hello world !")

    def test_clamp_detail_truncates(self):
        s = "x" * 50
        out = codex_cli_bridge.clamp_detail(s, 10)
        self.assertTrue(out.endswith("…"))
        self.assertLessEqual(len(out), 10)

    def test_guess_action_user_is_plan(self):
        self.assertEqual(codex_cli_bridge.guess_action("user", "anything"), "plan")

    def test_guess_action_detects_tests(self):
        self.assertEqual(
            codex_cli_bridge.guess_action("assistant", "run pytest -q"), "test"
        )

    def test_guess_action_detects_run(self):
        self.assertEqual(
            codex_cli_bridge.guess_action("assistant", "run python3 foo.py"), "run"
        )


if __name__ == "__main__":
    unittest.main()
