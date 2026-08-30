from __future__ import annotations

import sys
import unittest
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from ensure_tools import CheckResult, PY_PACKAGES  # noqa: E402
from install_skill import default_skill_root, install_skill  # noqa: E402


def make_skill(path: Path, marker: str = "first") -> Path:
    path.mkdir(parents=True)
    (path / "SKILL.md").write_text(
        f"---\nname: sample-skill\ndescription: {marker}\n---\n",
        encoding="utf-8",
    )
    return path


class InstallSkillTests(unittest.TestCase):
    def test_default_host_roots_are_platform_neutral(self) -> None:
        with TemporaryDirectory() as raw:
            home = Path(raw)
            self.assertEqual(default_skill_root("codex", home, "darwin"), home / ".codex" / "skills")
            self.assertEqual(
                default_skill_root("opencode", home, "darwin"),
                home / ".config" / "opencode" / "skills",
            )
            self.assertEqual(default_skill_root("workbuddy", home, "windows"), home / ".workbuddy" / "skills")

    def test_copy_install_refuses_existing_target_without_force(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            source = make_skill(root / "sample-skill")
            target_root = root / "host" / "skills"
            installed = install_skill(source, target_root, mode="copy", force=False)
            self.assertTrue((installed / "SKILL.md").is_file())
            with self.assertRaises(FileExistsError):
                install_skill(source, target_root, mode="copy", force=False)

    def test_force_install_keeps_recoverable_backup(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            source = make_skill(root / "sample-skill", "version-one")
            target_root = root / "host" / "skills"
            installed = install_skill(source, target_root, mode="copy", force=False)
            (source / "SKILL.md").write_text("version-two\n", encoding="utf-8")
            install_skill(source, target_root, mode="copy", force=True)
            backups = list(target_root.glob("sample-skill.backup-*"))
            self.assertEqual(len(backups), 1)
            self.assertIn("version-one", (backups[0] / "SKILL.md").read_text(encoding="utf-8"))
            self.assertEqual((installed / "SKILL.md").read_text(encoding="utf-8"), "version-two\n")

    def test_link_mode_creates_directory_symlink(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            source = make_skill(root / "sample-skill")
            installed = install_skill(source, root / "host" / "skills", mode="link", force=False)
            self.assertTrue(installed.is_symlink())
            self.assertEqual(installed.resolve(), source.resolve())

    def test_tool_result_marks_user_action_separately(self) -> None:
        payload = asdict(CheckResult("executable", "ffmpeg", False, requires_user_action=True, note="install manually"))
        self.assertTrue(payload["requires_user_action"])

    def test_core_does_not_require_optional_computer_vision_packages(self) -> None:
        self.assertEqual(PY_PACKAGES["core"], [])
        self.assertIn(("cv2", "opencv-python"), PY_PACKAGES["vision"])


if __name__ == "__main__":
    unittest.main()
