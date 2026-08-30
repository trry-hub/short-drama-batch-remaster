#!/usr/bin/env python3
"""Evaluate an existing release manifest and write readiness reports."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from delivery_profiles import load_delivery_profile
from release_readiness import aggregate_report_status, reports_from_manifest, write_readiness_reports


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate local release readiness from a manifest.")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--profile-name", default="video-channels")
    parser.add_argument("--profile-version", type=int, default=1)
    args = parser.parse_args(argv)

    try:
        load_delivery_profile(args.profile_name, args.profile_version)
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        reports = reports_from_manifest(manifest)
        paths = write_readiness_reports(reports, args.output_dir)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1

    status = aggregate_report_status(reports)
    print(
        json.dumps(
            {
                "ok": status != "blocked",
                "status": status,
                "json": str(paths.json),
                "csv": str(paths.csv),
                "markdown": str(paths.markdown),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 2 if status == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
