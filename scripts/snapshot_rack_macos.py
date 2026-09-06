"""Take a screenshot of every .vcv patch in a folder using VCV Rack on macOS.

For each patch a temporary copy is written with `zoom` / `gridOffset` adjusted so the
whole patch fits the Rack window, Rack is (re)launched with that file, and the window is
captured with `screencapture` into <dir>/catalog/snapshots/<stem>.png.

Usage:
    uv run python scripts/snapshot_rack_macos.py "<dir>" [--app "VCV Rack 2 Pro"]
        [--size 1700x1050] [--only STEM ...] [--force]

Requirements: macOS, the Rack app installed, and Screen Recording + Accessibility
permission for the terminal. Rack must be able to load every patch without dialogs
(run `vcvpatch validate` first). System volume is muted while the script runs.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from vcvpatch import fit_view, read_vcv, write_vcv
from vcvpatch.catalog import CATALOG_DIR, SNAPSHOTS_DIR
from vcvpatch.library import rack_user_dir

RACKWIN_SWIFT = r"""
import CoreGraphics
import Foundation
let opts = CGWindowListOption(arrayLiteral: .optionOnScreenOnly, .excludeDesktopElements)
guard let list = CGWindowListCopyWindowInfo(opts, kCGNullWindowID) as? [[String: Any]] else { exit(1) }
for w in list {
    let owner = w[kCGWindowOwnerName as String] as? String ?? ""
    let name = w[kCGWindowName as String] as? String ?? ""
    let num = w[kCGWindowNumber as String] as? Int ?? 0
    let layer = w[kCGWindowLayer as String] as? Int ?? 0
    if owner.contains("Rack") && layer == 0 {
        let b = w[kCGWindowBounds as String] as? [String: Any] ?? [:]
        print("\(num)\t\(owner)\t\(name)\t\(b["X"] ?? 0),\(b["Y"] ?? 0),\(b["Width"] ?? 0),\(b["Height"] ?? 0)")
    }
}
"""

MENU_BAR_PX = 40  # Rack's in-window menu bar + bottom scrollbar
SCROLLBAR_PX = 20


def sh(*args: str, check: bool = True, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(list(args), capture_output=True, text=True, check=check, **kw)


def osascript(script: str) -> str:
    return sh("osascript", "-e", script, check=False).stdout.strip()


def build_rackwin() -> Path:
    cache = Path.home() / ".cache" / "vcvpatch"
    cache.mkdir(parents=True, exist_ok=True)
    binary = cache / "rackwin"
    source = cache / "rackwin.swift"
    if not (binary.exists() and source.exists() and source.read_text() == RACKWIN_SWIFT):
        source.write_text(RACKWIN_SWIFT)
        sh("swiftc", "-O", str(source), "-o", str(binary))
    return binary


def rack_window(rackwin: Path) -> tuple[int, tuple[float, float, float, float]] | None:
    out = sh(str(rackwin), check=False).stdout.strip()
    if not out:
        return None
    first = out.splitlines()[0].split("\t")
    x, y, w, h = (float(v) for v in first[3].split(","))
    return int(first[0]), (x, y, w, h)


def rack_pids(app: str) -> list[int]:
    out = sh("pgrep", "-f", f"{app}.app/Contents/MacOS/Rack", check=False).stdout.split()
    return [int(p) for p in out]


def quit_rack(app: str, timeout: float = 15.0) -> None:
    if not rack_pids(app):
        return
    osascript(f'tell application "{app}" to quit')
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not rack_pids(app):
            return
        time.sleep(0.3)
    for pid in rack_pids(app):
        os.kill(pid, 9)
    time.sleep(1.0)


def wait_for_patch_loaded(log: Path, basename: str, timeout: float = 60.0) -> int:
    """Poll Rack's log until 'Loading patch <basename>' appears and widget creation stops."""
    deadline = time.time() + timeout
    last = -1
    stable = 0
    while time.time() < deadline:
        try:
            txt = log.read_text(errors="replace")
        except FileNotFoundError:
            txt = ""
        i = txt.rfind("Loading patch")
        if i >= 0 and basename in txt[i : i + 400]:
            n = txt[i:].count("Creating module widget")
            if n == last:
                stable += 1
                if stable >= 3:
                    return n
            else:
                stable = 0
            last = n
        time.sleep(0.5)
    raise TimeoutError(f"Rack did not finish loading {basename} within {timeout}s")


def wait_for_window(rackwin: Path, width: float, timeout: float = 20.0) -> int:
    deadline = time.time() + timeout
    while time.time() < deadline:
        found = rack_window(rackwin)
        if found and found[1][2] >= width - 10:
            return found[0]
        time.sleep(0.4)
    raise TimeoutError("Rack window did not reach the requested size")


def png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()[:24]
    return struct.unpack(">II", data[16:24])


def snapshot_one(
    src: Path, dest: Path, *, app: str, size: tuple[int, int], tmp_dir: Path, log: Path, rackwin: Path
) -> None:
    patch = read_vcv(src)
    bbox = patch.bbox()
    if bbox is None:
        raise ValueError("patch has no modules")
    view_w, view_h = size[0] - SCROLLBAR_PX, size[1] - MENU_BAR_PX
    zoom, offset = fit_view(bbox, view_w, view_h)
    patch.raw["zoom"] = zoom
    patch.raw["gridOffset"] = offset
    tmp_file = tmp_dir / src.name
    write_vcv(patch, tmp_file, overwrite=True)

    quit_rack(app)
    sh("open", "-a", app, str(tmp_file))
    widgets = wait_for_patch_loaded(log, src.name)
    wid = wait_for_window(rackwin, size[0])
    time.sleep(1.5)
    for attempt in range(2):
        sh("screencapture", "-x", "-o", "-l", str(wid), str(dest))
        if dest.is_file() and dest.stat().st_size > 0:
            w, h = png_size(dest)
            if w >= size[0]:
                break
        time.sleep(2.0)
    print(f"  {src.name}: {widgets} widgets, zoom={zoom:.2f}, {w}x{h}px -> {dest.name}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("directory")
    parser.add_argument("--app", default="VCV Rack 2 Pro", help="Rack application name (default: VCV Rack 2 Pro)")
    parser.add_argument("--size", default="1700x1050", help="Rack window size in points, WxH")
    parser.add_argument("--only", nargs="*", default=None, help="only these file stems")
    parser.add_argument("--force", action="store_true", help="re-take snapshots that already exist")
    args = parser.parse_args(argv)

    if sys.platform != "darwin":
        print("this script only works on macOS", file=sys.stderr)
        return 2
    width, height = (int(v) for v in args.size.lower().split("x"))
    directory = Path(args.directory)
    snaps_dir = directory / CATALOG_DIR / SNAPSHOTS_DIR
    snaps_dir.mkdir(parents=True, exist_ok=True)
    files = sorted(directory.glob("*.vcv"))
    if args.only:
        files = [f for f in files if f.stem in set(args.only)]
    todo = [f for f in files if args.force or not (snaps_dir / f"{f.stem}.png").is_file()]
    print(f"{len(todo)} of {len(files)} patches to snapshot -> {snaps_dir}")
    if not todo:
        return 0

    rackwin = build_rackwin()
    user_dir = rack_user_dir()
    settings_path = user_dir / "settings.json"
    log = user_dir / "log.txt"
    tmp_dir = Path(tempfile.mkdtemp(prefix="vcvpatch_snapshots_"))

    quit_rack(args.app)
    original_settings = json.loads(settings_path.read_text(encoding="utf-8"))
    settings = dict(original_settings)
    settings.update({"windowSize": [float(width), float(height)], "windowPos": [0.0, 28.0], "windowMaximized": False})
    settings_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    volume = osascript("output volume of (get volume settings)")
    osascript("set volume output volume 0")

    failures: list[tuple[str, str]] = []
    try:
        for f in todo:
            dest = snaps_dir / f"{f.stem}.png"
            try:
                snapshot_one(f, dest, app=args.app, size=(width, height), tmp_dir=tmp_dir, log=log, rackwin=rackwin)
            except Exception as exc:  # noqa: BLE001 - keep going, report at the end
                failures.append((f.name, str(exc)))
                print(f"  {f.name}: FAILED - {exc}")
    finally:
        quit_rack(args.app)
        current = json.loads(settings_path.read_text(encoding="utf-8"))
        for key in ("windowSize", "windowPos", "windowMaximized"):
            if key in original_settings:
                current[key] = original_settings[key]
        settings_path.write_text(json.dumps(current, indent=2), encoding="utf-8")
        if volume:
            osascript(f"set volume output volume {volume}")
        shutil.rmtree(tmp_dir, ignore_errors=True)

    print(f"done: {len(todo) - len(failures)} ok, {len(failures)} failed")
    for name, reason in failures:
        print(f"  FAILED {name}: {reason}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
