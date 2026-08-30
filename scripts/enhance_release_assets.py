#!/usr/bin/env python3
"""Generate optional editable enhancement assets for one release episode."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from content_enhancements import EnhancementRequest, NeedsInput, artifacts_to_dict, enhance_episode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate authorized release enhancement assets.")
    parser.add_argument("video", type=Path)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--episode", type=int, required=True)
    parser.add_argument("--subtitles", action="store_true")
    parser.add_argument("--covers", action="store_true")
    parser.add_argument("--copy", action="store_true")
    parser.add_argument("--narration-script", type=Path)
    parser.add_argument("--approve-narration-script", action="store_true")
    parser.add_argument("--editorial-recommendations", action="store_true")
    args = parser.parse_args(argv)

    request = EnhancementRequest(
        episode=args.episode,
        video_path=args.video.resolve(),
        output_root=args.output_root.resolve(),
        subtitles=args.subtitles,
        covers=args.covers,
        copy=args.copy,
        narration=args.narration_script is not None,
        editorial_recommendations=args.editorial_recommendations,
        narration_script=args.narration_script.resolve() if args.narration_script else None,
        narration_script_approved=args.approve_narration_script,
    )
    try:
        artifacts = enhance_episode(request)
    except NeedsInput as exc:
        print(json.dumps({"ok": False, "status": "needs_input", "error": str(exc)}, ensure_ascii=False))
        return 3
    report_path = args.output_root / "reports" / "content_enhancements.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"episode": args.episode, "artifacts": artifacts_to_dict(artifacts)}
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "report": str(report_path), **payload}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
