import json
import subprocess
import sys
import unittest


class WorkerCliTests(unittest.TestCase):
    def run_worker(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "worker", *args],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )

    def test_once_reports_local_idle_without_remote_capabilities(self) -> None:
        result = self.run_worker("--once")
        self.assertEqual(result.returncode, 0, result.stderr)
        event = json.loads(result.stdout)
        self.assertEqual(event["status"], "idle")
        self.assertEqual(event["capabilities"], [])
        self.assertFalse(event["remoteConnected"])

    def test_run_exits_after_bounded_cycle(self) -> None:
        result = self.run_worker("--run", "--interval-seconds", "0.01", "--max-cycles", "1")
        self.assertEqual(result.returncode, 0, result.stderr)
        events = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual([event["status"] for event in events], ["idle", "stopped"])
        self.assertEqual(events[-1]["cycles"], 1)

    def test_invalid_cycle_count_fails_before_start(self) -> None:
        result = self.run_worker("--run", "--max-cycles", "0")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
