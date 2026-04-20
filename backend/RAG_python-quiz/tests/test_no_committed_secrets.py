import subprocess
import unittest
from pathlib import Path
import re


class NoCommittedSecretsTests(unittest.TestCase):
    def test_tracked_python_files_do_not_contain_obvious_live_tokens(self):
        backend_root = Path(__file__).resolve().parents[1]
        repo_root = Path(__file__).resolve().parents[3]

        try:
            result = subprocess.run(
                ["git", "ls-files", "backend/RAG_python-quiz"],
                cwd=repo_root,
                check=True,
                capture_output=True,
                text=True,
            )
            tracked_files = [
                repo_root / line.strip()
                for line in result.stdout.splitlines()
                if line.strip().endswith(".py")
            ]
        except (OSError, subprocess.CalledProcessError):
            tracked_files = [
                path
                for path in backend_root.rglob("*.py")
                if "__pycache__" not in path.parts
            ]

        token_prefix = "sk" + "-"
        openrouter_prefix = "sk" + "-or-v1-"
        bearer_prefix = "Bearer" + r"\s+" + token_prefix
        google_prefix = "AI" + "za"
        patterns = [
            re.compile(token_prefix + r"[A-Za-z0-9][A-Za-z0-9_-]{20,}"),
            re.compile(openrouter_prefix + r"[A-Za-z0-9_-]{20,}"),
            re.compile(bearer_prefix + r"[A-Za-z0-9_-]{20,}"),
            re.compile(google_prefix + r"[0-9A-Za-z_-]{20,}"),
        ]

        findings = []
        this_file = Path(__file__).resolve()

        for path in tracked_files:
            if path.resolve() == this_file:
                continue

            text = path.read_text(encoding="utf-8", errors="ignore")
            for pattern in patterns:
                match = pattern.search(text)
                if match:
                    findings.append(f"{path}: {match.group(0)[:16]}...")
                    break

        self.assertEqual(findings, [], "Found possible committed credentials:\n" + "\n".join(findings))
