"""Round-trip every .vcv in a directory through vcvpatch and report mismatches.

Usage: uv run python scripts/roundtrip_check.py <dir-with-vcv-files>
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from vcvpatch import read_vcv, write_vcv


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    files = sorted(Path(argv[1]).glob("*.vcv"))
    failures = 0
    with tempfile.TemporaryDirectory() as tmp:
        for f in files:
            try:
                original = read_vcv(f)
                out = write_vcv(original, Path(tmp) / f.name, overwrite=True)
                again = read_vcv(out)
                same = again.raw == original.raw and again.assets == original.assets
            except Exception as exc:  # noqa: BLE001 - report everything
                print(f"FAIL  {f.name}: {exc}")
                failures += 1
                continue
            status = "ok  " if same else "FAIL"
            if not same:
                failures += 1
            print(
                f"{status}  {f.name}  modules={len(original.modules)} "
                f"cables={len(original.cables)} assets={len(original.assets)}"
            )
    print(f"{len(files) - failures}/{len(files)} files round-trip cleanly")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
