#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 记忆储存和管理器

默认启动图形界面：
    python memory_manager.py

也可以作为命令行工具使用：
    python memory_manager.py --list
    python memory_manager.py --stats
    python memory_manager.py --search "关键词"
    python memory_manager.py --check
    python memory_manager.py --export-md 记忆.md
    python memory_manager.py --export-html 记忆.html
    python memory_manager.py --import 某个对话.json

所有数据逻辑在 memory_core.py，图形界面在 memory_gui.py。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import unicodedata
from typing import Any, List, Optional, Sequence

from memory_core import (
    VERSION,
    DataError,
    Library,
    atomic_write_text,
    conversation_title,
    library_stats,
    search_library,
    to_html,
    to_markdown,
    validate_library,
)


# ---------------------------------------------------------------------------
# 终端表格（按中文双宽对齐）
# ---------------------------------------------------------------------------

def _char_width(char: str) -> int:
    return 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1


def _display_width(text: Any) -> int:
    return sum(_char_width(ch) for ch in str(text))


def _truncate(text: Any, width: int) -> str:
    text = str(text)
    if _display_width(text) <= width:
        return text
    out: List[str] = []
    used = 0
    for char in text:
        cost = _char_width(char)
        if used + cost > width - 1:
            break
        out.append(char)
        used += cost
    return "".join(out) + "…"


def _pad(text: Any, width: int, align: str = "left") -> str:
    text = str(text)
    gap = max(width - _display_width(text), 0)
    if align == "right":
        return " " * gap + text
    return text + " " * gap


def _table(headers: Sequence[str], rows: Sequence[Sequence[Any]],
           aligns: Optional[Sequence[str]] = None) -> str:
    aligns = list(aligns or ["left"] * len(headers))
    widths = [_display_width(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], _display_width(cell))
    lines = ["  ".join(_pad(h, widths[i]) for i, h in enumerate(headers))]
    lines.append("  ".join("-" * widths[i] for i in range(len(headers))))
    for row in rows:
        lines.append("  ".join(
            _pad(cell, widths[i], aligns[i]) for i, cell in enumerate(row)))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 命令实现
# ---------------------------------------------------------------------------

def _print_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def cmd_list(args, lib: Library) -> int:
    fnames = lib.sorted_fnames(sort=args.sort, reverse=not args.ascending)
    rows = []
    for fname in fnames:
        meta = lib.convs[fname]
        rows.append([
            _truncate(meta.get("title", fname), 30),
            meta.get("count", 0),
            (meta.get("exported_at") or meta.get("added_at") or "")[:10],
            _truncate(fname, 38),
        ])
    if args.json:
        _print_json({
            "root": lib.root,
            "conversations": [
                {
                    "file": fname,
                    "title": lib.convs[fname].get("title", fname),
                    "count": lib.convs[fname].get("count", 0),
                    "exported_at": lib.convs[fname].get("exported_at", ""),
                    "added_at": lib.convs[fname].get("added_at", ""),
                    "tags": lib.convs[fname].get("tags", []),
                    "starred": lib.convs[fname].get("starred", False),
                }
                for fname in fnames
            ],
        })
        return 0
    if not rows:
        print("对话库是空的。可以运行 `python memory_manager.py` 打开界面导入。")
        return 0
    total = sum(int(lib.convs[f].get("count", 0) or 0) for f in fnames)
    print(f"{len(rows)} 个对话 · {total:,} 组问答 · {lib.root}\n")
    print(_table(["标题", "问答", "日期", "文件"], rows,
                 ["left", "right", "left", "left"]))
    return 0


def cmd_stats(args, lib: Library) -> int:
    stats = library_stats(lib)
    if args.json:
        _print_json(stats)
        return 0
    totals = stats["totals"]
    print(f"对话 {totals['conversations']} 个 · 问答 {totals['qa']:,} 组 · "
          f"正文 {totals['question_chars'] + totals['answer_chars']:,} 字 · "
          f"思考 {totals['thinking_seconds'] / 60:.1f} 分钟\n")
    rows = sorted(stats["rows"], key=lambda r: r["answer_chars"], reverse=True)
    table_rows = [[
        _truncate(row["title"], 28),
        row["count"],
        row["question_chars"],
        row["answer_chars"],
        row["avg_answer_chars"],
        f"{row['thinking_seconds'] / 60:.1f}",
        _truncate("、".join(row["tags"]), 18) if row["tags"] else "",
    ] for row in rows]
    print(_table(
        ["标题", "问答", "提问字数", "回答字数", "平均回答", "思考(分)", "标签"],
        table_rows, ["left", "right", "right", "right", "right", "right", "left"]))
    return 0


def _resolve_scope(lib: Library, scope: Optional[str]) -> Optional[str]:
    if not scope:
        return None
    if scope in lib.convs:
        return scope
    scoped = scope.lower()
    for fname, meta in lib.convs.items():
        if scoped in str(meta.get("title", "")).lower():
            return fname
    print(f"找不到对话：{scope}", file=sys.stderr)
    return ""


def cmd_search(args, lib: Library) -> int:
    scope = _resolve_scope(lib, args.scope)
    if scope == "":
        return 2
    roles: List[str] = []
    for role in args.role or ["user", "ai"]:
        if role == "all":
            roles = ["user", "thinking", "ai"]
            break
        if role not in roles:
            roles.append(role)
    try:
        result = search_library(
            lib, args.search, roles=roles,
            case_sensitive=args.case, use_regex=args.regex,
            fname=scope, max_rows=args.max_rows,
        )
    except ValueError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    if args.json:
        _print_json(result.to_dict())
        return 0
    if not result.rows:
        print(f"没有找到「{args.search}」。")
        return 0
    print(f"命中 {len(result.rows)} 条问答/角色，共 {result.total_matches} 处匹配 · "
          f"{result.elapsed * 1000:.0f} ms"
          + ("（已截断）" if result.truncated else ""))
    current = None
    for hit in result.rows:
        if hit.fname != current:
            current = hit.fname
            print(f"\n■ {hit.title}  ({hit.fname})")
        print(f"  第 {hit.index} 条 · {hit.role_label}（{hit.count} 处）")
        print(f"    {hit.snippet}")
    return 0


def cmd_check(args, lib: Library) -> int:
    report = validate_library(lib)
    if args.json:
        _print_json(report)
    else:
        if not report["issues"]:
            print(f"检查了 {report['conversations']} 个对话，未发现问题。")
        else:
            print(f"发现 {report['errors']} 个错误、{report['warnings']} 个警告：\n")
            for issue in report["issues"]:
                mark = "错误" if issue["severity"] == "error" else "警告"
                print(f"[{mark}] {issue['file']}")
                print(f"       {issue['message']}")
    return 1 if report["errors"] else 0


def _select_for_export(lib: Library, only: Optional[Sequence[str]]) -> List[str]:
    fnames = lib.sorted_fnames()
    if only:
        needles = [n.lower() for n in only]
        fnames = [
            f for f in fnames
            if any(n in str(lib.convs[f].get("title", "")).lower()
                   or n in f.lower() for n in needles)
        ]
    return fnames


def cmd_export_markdown(args, lib: Library) -> int:
    fnames = _select_for_export(lib, args.only)
    if not fnames:
        print("没有匹配的对话。", file=sys.stderr)
        return 2
    blocks = [to_markdown(lib.read_conversation(fname)) for fname in fnames]
    try:
        atomic_write_text(args.export_md, "\n\n".join(blocks))
    except OSError as exc:
        print(f"写入失败：{exc}", file=sys.stderr)
        return 1
    print(f"已导出 {len(fnames)} 个对话到 {args.export_md}")
    return 0


def cmd_export_html(args, lib: Library) -> int:
    fnames = _select_for_export(lib, args.only)
    if not fnames:
        print("没有匹配的对话。", file=sys.stderr)
        return 2
    docs = [lib.read_conversation(fname) for fname in fnames]
    title = (conversation_title(docs[0]) if len(docs) == 1
             else f"AI 记忆导出 · {len(docs)} 个对话")
    try:
        atomic_write_text(args.export_html, to_html(docs, title=title))
    except OSError as exc:
        print(f"写入失败：{exc}", file=sys.stderr)
        return 1
    print(f"已导出 {len(fnames)} 个对话到 {args.export_html}")
    return 0


def cmd_import(args, lib: Library) -> int:
    paths: List[str] = []
    for raw in args.import_paths:
        path = os.path.abspath(raw)
        if os.path.isdir(path):
            for dirpath, dirnames, filenames in os.walk(path):
                dirnames[:] = [d for d in dirnames if not d.startswith(".")]
                paths.extend(os.path.join(dirpath, f) for f in filenames
                             if f.lower().endswith(".json"))
        else:
            paths.append(path)
    if not paths:
        print("没有找到 JSON 文件。", file=sys.stderr)
        return 2
    result = lib.import_paths(paths)
    if args.json:
        _print_json({
            "added": result.added,
            "duplicates": result.duplicates,
            "skipped": result.skipped,
        })
        return 0
    print(f"新增 {len(result.added)} 个对话。")
    if result.duplicates:
        print(f"跳过重复 {len(result.duplicates)} 个：")
        for name, existing in result.duplicates:
            print(f"  · {name} → {existing}")
    if result.skipped:
        print(f"跳过 {len(result.skipped)} 个：")
        for name, reason in result.skipped:
            print(f"  · {name}：{reason}")
    return 0


# ---------------------------------------------------------------------------
# 参数解析
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="memory_manager.py",
        description="AI 记忆储存和管理器：不带参数启动图形界面，带参数使用命令行。",
        epilog="示例：python memory_manager.py --search 服务器 --role all",
    )
    parser.add_argument("--root", default=None,
                        help="数据目录（默认是本脚本所在目录）")
    parser.add_argument("--version", action="version",
                        version=f"%(prog)s {VERSION}")

    group = parser.add_mutually_exclusive_group()
    group.add_argument("--list", action="store_true", help="列出对话库")
    group.add_argument("--stats", action="store_true", help="输出统计")
    group.add_argument("--search", metavar="关键词", help="全文搜索")
    group.add_argument("--check", action="store_true", help="检查对话库完整性")
    group.add_argument("--export-md", metavar="文件", help="导出 Markdown")
    group.add_argument("--export-html", metavar="文件", help="导出单文件 HTML")
    group.add_argument("--import", dest="import_paths", action="append",
                       metavar="路径", help="导入 JSON 文件或文件夹（可重复）")
    group.add_argument("--gui", action="store_true", help="启动图形界面")

    parser.add_argument("--role", action="append",
                        choices=["user", "thinking", "ai", "all"],
                        help="搜索角色，可重复；默认 user 与 ai")
    parser.add_argument("--case", action="store_true", help="区分大小写")
    parser.add_argument("--regex", action="store_true", help="按正则表达式搜索")
    parser.add_argument("--max-rows", type=int, default=200,
                        help="搜索结果上限（默认 200）")
    parser.add_argument("--scope", metavar="对话", help="只搜索某个对话（文件名或标题）")
    parser.add_argument("--only", action="append", metavar="标题",
                        help="只导出标题/文件名包含该文字的对话，可重复")
    parser.add_argument("--sort", choices=["date", "title", "count"], default="date",
                        help="--list 的排序字段")
    parser.add_argument("--ascending", action="store_true", help="--list 升序")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.root and not os.path.isdir(args.root):
        print(f"错误：数据目录不存在：{args.root}", file=sys.stderr)
        return 2

    root = args.root
    try:
        lib = Library(root).load()
    except (OSError, DataError) as exc:
        print(f"错误：无法加载对话库：{exc}", file=sys.stderr)
        return 1

    if lib.recovered_from_backup:
        print("提示：library.json 已从 library.json.bak 自动恢复。", file=sys.stderr)
    elif lib.load_error:
        print(f"提示：library.json 无法读取，已重建索引（{lib.load_error}）。",
              file=sys.stderr)

    if args.import_paths:
        return cmd_import(args, lib)
    if args.check:
        return cmd_check(args, lib)
    if args.list:
        return cmd_list(args, lib)
    if args.stats:
        return cmd_stats(args, lib)
    if args.search:
        return cmd_search(args, lib)
    if args.export_md:
        return cmd_export_markdown(args, lib)
    if args.export_html:
        return cmd_export_html(args, lib)

    # 默认：图形界面
    try:
        from memory_gui import run
    except ImportError as exc:
        print(f"无法启动图形界面（{exc}）。\n"
              "可以使用 --list / --stats / --search / --export-md 等命令行功能。",
              file=sys.stderr)
        return 1
    run(root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
