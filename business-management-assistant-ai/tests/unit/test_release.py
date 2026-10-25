import hashlib
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest
import zipfile

from scripts.package_release import ROOT as PACKAGE_ROOT
from scripts.package_release import included

ROOT = pathlib.Path(__file__).resolve().parents[2]


class ReleaseConsistencyTests(unittest.TestCase):
    def test_versions_agree(self):
        pyproject = re.search(r'^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(), re.M).group(1)
        settings = re.search(r'version: str = "([^"]+)"', (ROOT / "app/core.py").read_text()).group(1)
        changelog = re.search(r"^## (\d+\.\d+\.\d+)", (ROOT / "CHANGELOG.md").read_text(), re.M).group(1)
        self.assertEqual((pyproject, settings), (changelog, changelog))

    def test_clean_release_package_is_deterministic_and_excludes_local_artifacts(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            script = ROOT / "scripts/package_release.py"
            for output in (first, second):
                subprocess.run([sys.executable, str(script), "--output-dir", output], cwd=ROOT, check=True, capture_output=True, text=True)
            archive_a = pathlib.Path(first) / "business-management-assistant-ai-v0.4.1.zip"
            archive_b = pathlib.Path(second) / "business-management-assistant-ai-v0.4.1.zip"
            digest_a = hashlib.sha256(archive_a.read_bytes()).hexdigest()
            digest_b = hashlib.sha256(archive_b.read_bytes()).hexdigest()
            self.assertEqual(digest_a, digest_b)
            with zipfile.ZipFile(archive_a) as archive:
                names = archive.namelist()
                self.assertIn("business-management-assistant-ai/config/.env.example", names)
                self.assertIn("business-management-assistant-ai/scripts/package_release.py", names)
                self.assertIn("business-management-assistant-ai/scripts/benchmark_core.py", names)
                self.assertIn("business-management-assistant-ai/docs/performance-and-validation.md", names)
                self.assertFalse(any(".pytest_cache/" in name for name in names))
                self.assertFalse(any("__pycache__/" in name for name in names))
                self.assertFalse(any(name.endswith(".db") or name.endswith("/results.jsonl") or name.endswith("/scores.json") for name in names))
                self.assertFalse(any(name.endswith("/.env") for name in names))

    def test_model_payloads_are_excluded_but_placeholder_is_kept(self):
        model_dir = PACKAGE_ROOT / "models"
        model_dir.mkdir(exist_ok=True)
        payload = model_dir / "unit-test-model-placeholder.safetensors"
        try:
            payload.write_bytes(b"not-a-real-model")
            self.assertFalse(included(payload))
            self.assertTrue(included(model_dir / ".gitkeep"))
        finally:
            payload.unlink(missing_ok=True)

    def test_release_packager_excludes_secret_files_and_credentials_directories(self):
        import tempfile

        with tempfile.TemporaryDirectory(dir=PACKAGE_ROOT) as directory:
            sandbox = pathlib.Path(directory)
            unsafe = [
                sandbox / "deploy.pem",
                sandbox / "PRIVATE.KEY",
                sandbox / "secrets.json",
                sandbox / ".ENV.production",
                sandbox / "credentials" / "token.txt",
                sandbox / ".ssh" / "id_rsa",
                sandbox / ".terraform" / "terraform.tfstate",
            ]
            for candidate in unsafe:
                candidate.parent.mkdir(parents=True, exist_ok=True)
                candidate.write_text("test-fixture-not-a-secret", encoding="utf-8")
            for candidate in unsafe:
                with self.subTest(path=str(candidate.relative_to(PACKAGE_ROOT))):
                    self.assertFalse(included(candidate))

    def test_env_example_documents_every_setting(self):
        source = (ROOT / "app/core.py").read_text()
        fields = set(re.findall(r"^    ([a-z_]+): ", source[source.index("class Settings"):source.index("def build_engine")], re.M))
        example = (ROOT / "config/.env.example").read_text().lower()
        undocumented = {f for f in fields if f not in example and f not in {"app_name", "version", "static_dir", "enable_docs", "models_dir", "model_policy"}}
        self.assertEqual(undocumented, set())


if __name__ == "__main__":
    unittest.main()
