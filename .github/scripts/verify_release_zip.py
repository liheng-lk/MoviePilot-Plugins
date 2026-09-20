#!/usr/bin/env python3
"""校验 MoviePilot Release ZIP 的安装布局。"""

from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("asset", type=Path)
    parser.add_argument("plugin_root")
    args = parser.parse_args()

    if not args.asset.is_file():
        print(f"Release asset not found: {args.asset}", file=sys.stderr)
        return 1

    with zipfile.ZipFile(args.asset) as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]

    if not names:
        print("Release asset is empty", file=sys.stderr)
        return 1

    required = f"{args.plugin_root}/__init__.py"
    if required not in names:
        print(f"Release asset missing required entry: {required}", file=sys.stderr)
        return 1

    prefix = f"{args.plugin_root}/"
    invalid = [
        name
        for name in names
        if (
            name.startswith("/")
            or "\\" in name
            or ".." in Path(name).parts
            or not name.startswith(prefix)
        )
    ]
    if invalid:
        print(f"Release asset contains invalid entries: {invalid[:5]}", file=sys.stderr)
        return 1

    print(f"Release ZIP layout OK: {required}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
