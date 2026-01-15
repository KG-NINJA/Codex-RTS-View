import json
import sys
import tempfile
import unittest
from pathlib import Path

import rtswrap


class TestRtswrap(unittest.TestCase):
    def test_run_once_appends_start_and_end_events(self):
        with tempfile.TemporaryDirectory() as td:
            log_path = str(Path(td) / "events.ndjson")
            rc = rtswrap.run_once(
                log_path=log_path,
                agent="test-agent",
                cmd=[sys.executable, "-c", "print('ok')"],
                reset=True,
            )
            self.assertEqual(rc, 0)

            lines = Path(log_path).read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 2)
            start = json.loads(lines[0])
            end = json.loads(lines[1])

            self.assertEqual(start["agent"], "test-agent")
            self.assertEqual(end["agent"], "test-agent")
            self.assertIsNone(start["ok"])
            self.assertIs(end["ok"], True)
            self.assertLessEqual(start["t"], end["t"])


if __name__ == "__main__":
    unittest.main()
