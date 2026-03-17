#!/usr/bin/env python3

import argparse
import os
import re
import sys
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple


ANSI_CSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
ANSI_RESET = "\x1b[0m"
LABEL_COLORS = [
    "\x1b[36m",
    "\x1b[32m",
    "\x1b[33m",
    "\x1b[35m",
    "\x1b[34m",
]


def strip_ansi(s: str) -> str:
    return ANSI_CSI_RE.sub("", s)


@dataclass
class TailFile:
    path: str
    label: str
    fp: Optional[object] = None
    inode: Optional[int] = None
    pos: int = 0
    buf: str = ""

    def _stat_inode(self) -> Optional[int]:
        try:
            st = os.stat(self.path)
        except FileNotFoundError:
            return None
        return st.st_ino

    def _open_if_needed(self, from_start: bool) -> None:
        inode = self._stat_inode()
        if inode is None:
            if self.fp is not None:
                try:
                    self.fp.close()
                except Exception:
                    pass
            self.fp = None
            self.inode = None
            self.pos = 0
            self.buf = ""
            return

        if self.fp is None or self.inode != inode:
            if self.fp is not None:
                try:
                    self.fp.close()
                except Exception:
                    pass
            self.fp = open(self.path, "r", encoding="utf-8", errors="replace")
            self.inode = inode
            if from_start:
                self.pos = 0
                self.fp.seek(0)
            else:
                self.fp.seek(0, os.SEEK_END)
                self.pos = self.fp.tell()
            self.buf = ""

    def read_new_lines(self, from_start: bool) -> List[str]:
        self._open_if_needed(from_start=from_start)
        if self.fp is None:
            return []

        try:
            st = os.stat(self.path)
        except FileNotFoundError:
            return []

        if st.st_size < self.pos:
            self.fp.seek(0)
            self.pos = 0
            self.buf = ""

        self.fp.seek(self.pos)
        data = self.fp.read()
        if not data:
            return []

        self.pos = self.fp.tell()
        self.buf += data
        lines = self.buf.splitlines(keepends=True)
        if not lines:
            return []

        if not (lines[-1].endswith("\n") or lines[-1].endswith("\r")):
            self.buf = lines.pop()
        else:
            self.buf = ""

        return lines


def default_files() -> List[Tuple[str, str]]:
    return [
        ("logs/langgraph.log", "LangGraph"),
        ("logs/gateway.log", "Gateway"),
        ("logs/frontend.log", "Frontend"),
        ("logs/nginx.log", "Nginx"),
    ]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="follow-logs.py")
    p.add_argument("--from-start", action="store_true")
    p.add_argument("--poll", type=float, default=0.2)
    ansi_group = p.add_mutually_exclusive_group()
    ansi_group.add_argument("--strip-ansi", dest="strip_ansi", action="store_true")
    ansi_group.add_argument("--keep-ansi", dest="strip_ansi", action="store_false")
    p.set_defaults(strip_ansi=False)

    color_group = p.add_mutually_exclusive_group()
    color_group.add_argument("--color", dest="color", action="store_true")
    color_group.add_argument("--no-color", dest="color", action="store_false")
    p.set_defaults(color=None)
    p.add_argument(
        "files",
        nargs="*",
        help="Log files to follow. Defaults to DeerFlow logs/*.log if omitted.",
    )
    return p.parse_args()


def build_tail_files(files: List[str]) -> List[TailFile]:
    if not files:
        return [TailFile(path=path, label=label) for path, label in default_files()]

    out: List[TailFile] = []
    for f in files:
        label = os.path.basename(f)
        out.append(TailFile(path=f, label=label))
    return out


def _auto_color_enabled() -> bool:
    if not sys.stdout.isatty():
        return False
    if os.environ.get("NO_COLOR") is not None:
        return False
    if os.environ.get("TERM", "") == "dumb":
        return False
    return True


def _label_color(label: str) -> str:
    idx = sum(label.encode("utf-8", errors="ignore")) % len(LABEL_COLORS)
    return LABEL_COLORS[idx]


def main() -> int:
    args = parse_args()
    tails = build_tail_files(args.files)
    label_width = max((len(t.label) for t in tails), default=0)
    strip_content_ansi = bool(args.strip_ansi)
    color_enabled = _auto_color_enabled() if args.color is None else bool(args.color)
    from_start = bool(args.from_start)
    poll = float(args.poll)

    sys.stdout.reconfigure(line_buffering=True)

    while True:
        any_output = False
        for t in tails:
            for line in t.read_new_lines(from_start=from_start):
                any_output = True
                text = line
                if strip_content_ansi:
                    text = strip_ansi(text)
                padded_label = f"{t.label:<{label_width}}"
                if color_enabled:
                    prefix = f"{_label_color(t.label)}{padded_label}{ANSI_RESET} | "
                else:
                    prefix = f"{padded_label} | "
                sys.stdout.write(prefix + text)
                if not (text.endswith("\n") or text.endswith("\r")):
                    sys.stdout.write("\n")

        if from_start:
            from_start = False

        if not any_output:
            time.sleep(poll)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
