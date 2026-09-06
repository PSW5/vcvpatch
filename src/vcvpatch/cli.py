"""Command-line interface: vcvpatch unpack|pack|info|validate|library|mcp."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .archive import pack_path, read_vcv, unpack_vcv
from .catalog import write_catalog
from .errors import RackNotFoundError, VcvPatchError
from .library import Library
from .summary import summarize
from .validate import has_errors, validate


def _library_or_warn() -> Library | None:
    try:
        return Library.scan()
    except RackNotFoundError as exc:
        print(f"warning: {exc}; skipping installed-plugin checks", file=sys.stderr)
        return None


def _cmd_unpack(args: argparse.Namespace) -> int:
    src = Path(args.file)
    out_dir = Path(args.output) if args.output else src.with_suffix("")
    unpack_vcv(src, out_dir)
    print(f"unpacked {src} -> {out_dir}")
    return 0


def _cmd_pack(args: argparse.Namespace) -> int:
    dest = pack_path(args.source, args.output, overwrite=args.force)
    print(f"packed {args.source} -> {dest}")
    return 0


def _cmd_info(args: argparse.Namespace) -> int:
    patch = read_vcv(args.file)
    if args.json:
        print(patch.to_json(), end="")
        return 0
    library = None if args.no_library else _library_or_warn()
    print(summarize(patch, library, fmt="markdown" if args.markdown else "text"), end="")
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    patch = read_vcv(args.file)
    library = None if args.no_library else _library_or_warn()
    issues = validate(patch, library)
    if not issues:
        print(f"{args.file}: no issues")
        return 0
    for issue in issues:
        print(str(issue))
    return 1 if has_errors(issues) else 0


def _cmd_library(args: argparse.Namespace) -> int:
    library = Library.scan()
    for warning in library.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    results = library.search(" ".join(args.query), tags=args.tags, limit=args.limit)
    if args.json:
        print(json.dumps([m.as_dict() for m in results], indent=2))
        return 0
    for m in results:
        tags = f"  [{', '.join(m.tags)}]" if m.tags else ""
        print(f"{m.plugin}/{m.slug}  {m.name}{tags}")
    print(f"{len(results)} module(s)", file=sys.stderr)
    return 0


def _cmd_catalog(args: argparse.Namespace) -> int:
    library = None if args.no_library else _library_or_warn()
    result = write_catalog(args.directory, library)
    print(f"{result['count']} patches -> {result['index']}")
    if result["added_annotations"]:
        print(f"added {len(result['added_annotations'])} inferred annotation(s) to {result['annotations']}; please review")
    return 0


def _cmd_mcp(args: argparse.Namespace) -> int:
    from .mcp_server import run

    run()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vcvpatch", description="Read, write and inspect VCV Rack 2 .vcv patch files."
    )
    parser.add_argument("--version", action="version", version=f"vcvpatch {__version__}")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("unpack", help="extract a .vcv file into a directory")
    p.add_argument("file")
    p.add_argument("-o", "--output", help="output directory (default: file name without extension)")
    p.set_defaults(func=_cmd_unpack)

    p = sub.add_parser("pack", help="pack a directory (or a patch .json) into a .vcv file")
    p.add_argument("source")
    p.add_argument("-o", "--output", required=True, help="output .vcv path")
    p.add_argument("--force", action="store_true", help="overwrite an existing output file")
    p.set_defaults(func=_cmd_pack)

    p = sub.add_parser("info", help="summarise a patch")
    p.add_argument("file")
    p.add_argument("--json", action="store_true", help="print the raw patch.json instead")
    p.add_argument("--markdown", action="store_true", help="markdown summary")
    p.add_argument("--no-library", action="store_true", help="do not look up installed plugins")
    p.set_defaults(func=_cmd_info)

    p = sub.add_parser("validate", help="check a patch; exit 1 if there are errors")
    p.add_argument("file")
    p.add_argument("--no-library", action="store_true", help="skip installed-plugin checks")
    p.set_defaults(func=_cmd_validate)

    p = sub.add_parser("library", help="search installed modules")
    p.add_argument("query", nargs="*")
    p.add_argument("--tags", nargs="+", default=None, help="require all of these tags")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cmd_library)

    p = sub.add_parser("catalog", help="write INDEX.md, catalog.json and per-patch pages for a folder of .vcv files")
    p.add_argument("directory")
    p.add_argument("--no-library", action="store_true", help="do not look up installed plugins for module names")
    p.set_defaults(func=_cmd_catalog)

    p = sub.add_parser("mcp", help="run the MCP server over stdio")
    p.set_defaults(func=_cmd_mcp)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_usage(sys.stderr)
        return 2
    try:
        return args.func(args)
    except FileExistsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except VcvPatchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
