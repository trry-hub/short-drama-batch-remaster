#!/usr/bin/env python3
"""Check and optionally install tools for short-drama batch remastering."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from typing import Iterable


PY_PACKAGES = {
    "core": [
        ("cv2", "opencv-python"),
        ("numpy", "numpy"),
        ("PIL", "Pillow"),
    ],
    "whisper": [
        ("faster_whisper", "faster-whisper"),
    ],
    "jianying": [
        ("pyJianYingDraft", "pyJianYingDraft"),
    ],
    "docs": [
        ("docx", "python-docx"),
        ("fitz", "PyMuPDF"),
        ("reportlab", "reportlab"),
    ],
    "ui": [
        ("pyautogui", "pyautogui"),
    ],
    "publish": [
        ("playwright", "playwright"),
    ],
}

EXECUTABLES = {
    "core": ["ffmpeg", "ffprobe"],
    "whisper": [],
    "jianying": [],
    "docs": [],
    "ui": [],
    "publish": [],
}


@dataclass
class CheckResult:
    kind: str
    name: str
    present: bool
    installed: bool = False
    note: str = ""


def run(cmd: list[str], *, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        check=check,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def has_module(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


def install_python_package(package: str) -> tuple[bool, str]:
    cmd = [sys.executable, "-m", "pip", "install", "--upgrade", package]
    try:
        proc = run(cmd)
    except Exception as exc:  # pragma: no cover - defensive reporting
        return False, str(exc)
    return proc.returncode == 0, proc.stdout[-1200:]


def install_ffmpeg() -> tuple[bool, str]:
    system = platform.system().lower()
    candidates: list[list[str]] = []

    if system == "darwin" and shutil.which("brew"):
        candidates.append(["brew", "install", "ffmpeg"])
    elif system == "linux":
        if shutil.which("apt-get"):
            prefix = [] if os.geteuid() == 0 else ["sudo", "-n"]
            candidates.append(prefix + ["apt-get", "update"])
            candidates.append(prefix + ["apt-get", "install", "-y", "ffmpeg"])
        elif shutil.which("dnf"):
            prefix = [] if os.geteuid() == 0 else ["sudo", "-n"]
            candidates.append(prefix + ["dnf", "install", "-y", "ffmpeg"])
        elif shutil.which("pacman"):
            prefix = [] if os.geteuid() == 0 else ["sudo", "-n"]
            candidates.append(prefix + ["pacman", "-S", "--noconfirm", "ffmpeg"])
    elif system == "windows":
        if shutil.which("winget"):
            candidates.append(
                [
                    "winget",
                    "install",
                    "--id",
                    "Gyan.FFmpeg",
                    "-e",
                    "--accept-package-agreements",
                    "--accept-source-agreements",
                ]
            )
        elif shutil.which("choco"):
            candidates.append(["choco", "install", "ffmpeg", "-y"])

    if not candidates:
        return False, "No supported package manager found for automatic FFmpeg installation."

    output_parts: list[str] = []
    for cmd in candidates:
        try:
            proc = run(cmd)
        except Exception as exc:  # pragma: no cover - defensive reporting
            output_parts.append(f"{' '.join(cmd)} failed: {exc}")
            return False, "\n".join(output_parts)
        output_parts.append(proc.stdout[-1200:])
        if proc.returncode != 0:
            return False, "\n".join(output_parts)

    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None, "\n".join(output_parts)


def normalize_features(raw: str) -> list[str]:
    features = [part.strip() for part in raw.split(",") if part.strip()]
    unknown = sorted(set(features) - set(PY_PACKAGES))
    if unknown:
        raise SystemExit(f"Unknown feature(s): {', '.join(unknown)}")
    return features


def check_executables(features: Iterable[str], install: bool) -> list[CheckResult]:
    results: list[CheckResult] = []
    needed = sorted({exe for feature in features for exe in EXECUTABLES.get(feature, [])})

    ffmpeg_missing = {"ffmpeg", "ffprobe"}.intersection({exe for exe in needed if not shutil.which(exe)})
    ffmpeg_installed = False
    ffmpeg_note = ""
    if ffmpeg_missing and install:
        ffmpeg_installed, ffmpeg_note = install_ffmpeg()

    for exe in needed:
        present = shutil.which(exe) is not None
        results.append(
            CheckResult(
                kind="executable",
                name=exe,
                present=present,
                installed=ffmpeg_installed if exe in {"ffmpeg", "ffprobe"} and present else False,
                note=ffmpeg_note if exe in {"ffmpeg", "ffprobe"} and not present else "",
            )
        )
    return results


def check_python(features: Iterable[str], install: bool) -> list[CheckResult]:
    results: list[CheckResult] = []
    seen: set[str] = set()
    for feature in features:
        for module, package in PY_PACKAGES[feature]:
            if module in seen:
                continue
            seen.add(module)
            present = has_module(module)
            installed = False
            note = ""
            if not present and install:
                ok, note = install_python_package(package)
                installed = ok
                present = has_module(module)
            results.append(
                CheckResult(
                    kind="python",
                    name=package,
                    present=present,
                    installed=installed,
                    note="" if present else note,
                )
            )
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--features",
        default="core,whisper,jianying,docs,ui",
        help="Comma-separated feature set: core,whisper,jianying,docs,ui,publish",
    )
    parser.add_argument("--install", action="store_true", help="Attempt automatic installation of missing dependencies.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args()

    features = normalize_features(args.features)
    results = check_executables(features, args.install) + check_python(features, args.install)
    missing = [result for result in results if not result.present]

    if args.json:
        print(json.dumps({"ok": not missing, "results": [asdict(r) for r in results]}, ensure_ascii=False, indent=2))
    else:
        for result in results:
            status = "OK" if result.present else "MISSING"
            action = " installed" if result.installed else ""
            print(f"[{status}]{action} {result.kind}: {result.name}")
            if result.note and not result.present:
                print(result.note.strip())
        if missing:
            print(f"\nMissing {len(missing)} dependency item(s). Some workflow stages may be blocked.")

    return 0 if not missing else 1


if __name__ == "__main__":
    raise SystemExit(main())
