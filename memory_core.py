#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 记忆储存和管理器 · 数据核心

这里只做数据层的事情：读写对话库、回收站、搜索、统计与导出。
不依赖 tkinter，因此 GUI、命令行和单元测试都可以复用。

设计目标：
- 用户数据永不因半截写入而损坏（原子写入 + library.json.bak 自动恢复）
- 删除可撤销（回收站 + 元数据还原）
- 导入去重（内容 SHA-1），不会因为重复导入产生 _1、_2 副本
- 外部修改可感知（同步时按 mtime + size 刷新）
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

VERSION = "1.1.1"

APP_DIR = os.path.dirname(os.path.abspath(__file__))
LIB_DIRNAME = "conversations"
TRASH_DIRNAME = "trash"
LIB_FILENAME = "library.json"
TRASH_INDEX_FILENAME = "trash_index.json"
SETTINGS_FILENAME = "settings.json"

# 兼容不同导出脚本的字段名
Q_KEYS = ("question", "user", "q")
A_KEYS = ("deepseek", "answer", "ai", "response")
T_KEYS = ("thinking", "think", "reasoning")

ROLE_KEYS = {"user": Q_KEYS, "thinking": T_KEYS, "ai": A_KEYS}
ROLE_LABELS = {"user": "用户", "thinking": "思考过程", "ai": "AI"}
ROLE_ORDER = ("user", "thinking", "ai")

DataLoader = Callable[[str], Dict[str, Any]]


class DataError(Exception):
    """对话库数据损坏或格式不正确。"""


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------

def load_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _atomic_write(path: str, text: str) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", suffix=".part", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def atomic_write_json(path: str, data: Any, indent: int = 2) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=indent) + "\n"
    _atomic_write(path, text)


def atomic_write_text(path: str, text: str) -> None:
    _atomic_write(path, text)


def backup_file(path: str) -> bool:
    """把文件复制为 path.bak（先写临时文件，避免留下半截备份）。"""
    if not os.path.isfile(path):
        return False
    directory = os.path.dirname(os.path.abspath(path))
    try:
        fd, tmp = tempfile.mkstemp(prefix=".bak-", suffix=".part", dir=directory)
        os.close(fd)
        shutil.copy2(path, tmp)
        os.replace(tmp, path + ".bak")
        return True
    except OSError:
        try:
            if "tmp" in locals():
                os.unlink(tmp)
        except OSError:
            pass
        return False


def load_json_recover(path: str) -> Tuple[Any, bool]:
    """读取 JSON；主文件损坏时自动回退到 .bak。

    返回 (data, 是否来自备份)。主文件不存在但备份存在也算恢复。
    两边都不可用时抛出 DataError。
    """
    errors: List[str] = []
    for candidate, used_backup in ((path, False), (path + ".bak", True)):
        if not os.path.exists(candidate):
            errors.append(f"{os.path.basename(candidate)} 不存在")
            continue
        try:
            return load_json(candidate), used_backup
        except (ValueError, OSError) as exc:
            errors.append(f"{os.path.basename(candidate)}: {exc}")
    raise DataError("；".join(errors) or "文件不存在")


def file_sha1(path: str) -> str:
    digest = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def first_key(mapping: Dict[str, Any], keys: Sequence[str]) -> Any:
    if not isinstance(mapping, dict):
        return ""
    for key in keys:
        if key not in mapping:
            continue
        value = mapping[key]
        if value is None:
            continue
        if isinstance(value, str):
            if value.strip():
                return value
        elif value != "" and value != [] and value != {}:
            return value
    return ""


def qa_field(qa: Dict[str, Any], role: str) -> str:
    value = first_key(qa, ROLE_KEYS.get(role, Q_KEYS))
    return "" if value is None else str(value)


def parse_seconds(value: Any) -> float:
    """把 '12.45秒' / '1分20秒' / 12.45 统一成秒数。"""
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return max(float(value), 0.0)
    text = str(value or "").strip()
    if not text:
        return 0.0
    minute = re.search(r"(\d+(?:\.\d+)?)\s*分(?:钟)?\s*(?:(\d+(?:\.\d+)?)\s*秒)?", text)
    if minute:
        return max(float(minute.group(1)) * 60 + float(minute.group(2) or 0), 0.0)
    second = re.search(r"(\d+(?:\.\d+)?)", text)
    return max(float(second.group(1)), 0.0) if second else 0.0


def fmt_count(n: Any) -> str:
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return str(n)


def format_size(size: int) -> str:
    size = max(int(size or 0), 0)
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / 1024 / 1024:.1f} MB"


def unique_path(directory: str, filename: str) -> str:
    """目录下同名文件时自动加序号。"""
    filename = filename or "未命名.json"
    path = os.path.join(directory, filename)
    if not os.path.exists(path):
        return path
    stem, ext = os.path.splitext(filename)
    index = 1
    while True:
        path = os.path.join(directory, f"{stem}_{index}{ext}")
        if not os.path.exists(path):
            return path
        index += 1


def is_conversation(data: Any) -> bool:
    return isinstance(data, dict) and isinstance(data.get("qa_pairs"), list)


def conversation_title(data: Dict[str, Any], fallback: str = "未命名对话") -> str:
    title = str(data.get("conversation_title") or "").strip()
    return title or fallback


# ---------------------------------------------------------------------------
# 全文搜索
# ---------------------------------------------------------------------------

@dataclass
class SearchHit:
    fname: str
    title: str
    index: int
    role: str
    role_label: str
    count: int
    snippet: str
    match_text: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file": self.fname,
            "title": self.title,
            "index": self.index,
            "role": self.role,
            "role_label": self.role_label,
            "count": self.count,
            "snippet": self.snippet,
            "match_text": self.match_text,
        }


@dataclass
class SearchResult:
    keyword: str
    rows: List[SearchHit] = field(default_factory=list)
    elapsed: float = 0.0
    truncated: bool = False
    total_matches: int = 0
    scope: Optional[str] = None

    @property
    def total_rows(self) -> int:
        return len(self.rows)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "keyword": self.keyword,
            "rows": [row.to_dict() for row in self.rows],
            "total_rows": self.total_rows,
            "total_matches": self.total_matches,
            "truncated": self.truncated,
            "elapsed_seconds": round(self.elapsed, 4),
            "scope": self.scope,
        }


def _snippet(text: str, start: int, end: int, before: int = 32, after: int = 76) -> str:
    left = max(0, start - before)
    right = min(len(text), end + after)
    raw = re.sub(r"\s+", " ", text[left:right]).strip()
    if left > 0:
        raw = "…" + raw
    if right < len(text):
        raw += "…"
    return raw


def search_library(
    library: "Library",
    keyword: str,
    roles: Sequence[str] = ("user", "ai"),
    case_sensitive: bool = False,
    use_regex: bool = False,
    fname: Optional[str] = None,
    max_rows: int = 1000,
    data_loader: Optional[DataLoader] = None,
) -> SearchResult:
    """跨对话搜索。每条命中的 (问答, 角色) 占一行，count 是该字段的命中次数。"""
    if not keyword:
        raise ValueError("搜索关键词不能为空")

    if isinstance(roles, str):
        roles = (roles,)
    wanted = [r for r in ROLE_ORDER if r in set(roles or ROLE_ORDER)]
    if not wanted:
        wanted = list(ROLE_ORDER)

    try:
        pattern = re.compile(
            keyword if use_regex else re.escape(keyword),
            0 if case_sensitive else re.IGNORECASE,
        )
    except re.error as exc:
        raise ValueError(f"正则表达式无效：{exc}") from exc

    loader = data_loader or library.read_conversation
    result = SearchResult(keyword=keyword, scope=fname)
    started = time.perf_counter()

    fnames = [fname] if fname else library.sorted_fnames()
    stop = False
    for current in fnames:
        if current not in library.convs:
            continue
        try:
            data = loader(current)
        except (OSError, ValueError, DataError):
            continue
        title = library.convs[current].get("title") or current
        for index, qa in enumerate(data.get("qa_pairs", []), 1):
            if not isinstance(qa, dict):
                continue
            for role in wanted:
                text = qa_field(qa, role)
                if not text:
                    continue
                matches = list(pattern.finditer(text))
                if not matches:
                    continue
                result.total_matches += len(matches)
                if len(result.rows) >= max_rows:
                    result.truncated = True
                    stop = True
                    break
                first = matches[0]
                result.rows.append(SearchHit(
                    fname=current,
                    title=title,
                    index=index,
                    role=role,
                    role_label=ROLE_LABELS[role],
                    count=len(matches),
                    snippet=_snippet(text, first.start(), first.end()),
                    match_text=first.group(0),
                ))
            if stop:
                break
        if stop:
            break

    result.elapsed = time.perf_counter() - started
    return result


# ---------------------------------------------------------------------------
# 合并 / 导出
# ---------------------------------------------------------------------------

def merge_conversations(
    library: "Library",
    fnames: Sequence[str],
    data_loader: Optional[DataLoader] = None,
) -> Dict[str, Any]:
    """按给定顺序合并，保留原格式并给每条标上 source_title。"""
    loader = data_loader or library.read_conversation
    pairs: List[Dict[str, Any]] = []
    titles: List[str] = []
    for fname in fnames:
        if fname not in library.convs:
            continue
        data = loader(fname)
        title = library.convs[fname].get("title") or conversation_title(data, fname)
        titles.append(title)
        for qa in data.get("qa_pairs", []):
            if isinstance(qa, dict):
                item = dict(qa)
                item["source_title"] = title
                item["source_file"] = fname
                pairs.append(item)
    for index, pair in enumerate(pairs, 1):
        pair["index"] = index
    return {
        "conversation_title": "合并: " + " + ".join(titles) if titles else "合并导出",
        "exported_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source_url": "",
        "source_type": "merged",
        "merged_from": list(fnames),
        "qa_pairs": pairs,
    }


def to_markdown(data: Dict[str, Any]) -> str:
    title = conversation_title(data)
    lines = [f"# {title}", ""]
    if data.get("exported_at"):
        lines.append(f"> 导出时间: {data['exported_at']}  ")
    if data.get("source_url"):
        lines.append(f"> 来源: {data['source_url']}")
    lines.append(f"\n共 {len(data.get('qa_pairs', []))} 组问答\n")
    for qa in data.get("qa_pairs", []):
        if not isinstance(qa, dict):
            continue
        source = f"（来自: {qa['source_title']}）" if qa.get("source_title") else ""
        lines.append("---\n")
        lines.append(f"## [{qa.get('index', '?')}] 用户 {source}\n")
        lines.append(qa_field(qa, "user") + "\n")
        thinking = qa_field(qa, "thinking")
        if thinking:
            seconds = parse_seconds(qa.get("thinking_seconds"))
            lines.append(
                "<details>\n<summary>思考过程"
                f"（{seconds:.1f} 秒）</summary>\n\n{thinking}\n\n</details>\n"
            )
        answer = qa_field(qa, "ai")
        if answer:
            lines.append(f"## AI\n\n{answer}\n")
    return "\n".join(lines).rstrip() + "\n"


_HTML_CSS = """
:root{
  color-scheme: light;
  --bg:#f5f6f8; --card:#ffffff; --text:#1f2328; --muted:#6b7280;
  --border:#dfe3e8; --user:#1a5fb4; --user-bg:#eaf2fb;
  --ai:#1f9d63; --ai-bg:#e9f7f0; --think:#6b7280; --think-bg:#fafbfc;
  --hl:#ffe98a;
}
body.dark{
  color-scheme: dark;
  --bg:#14171c; --card:#1c2027; --text:#e6e9ef; --muted:#9aa4b2;
  --border:#30363f; --user:#7aa7e8; --user-bg:#1b2a3d;
  --ai:#5cc99a; --ai-bg:#17342a; --think:#9aa4b2; --think-bg:#191d24;
  --hl:#6b5b1f;
}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--text);
  font:16px/1.8 "Microsoft YaHei UI","Microsoft YaHei","PingFang SC","Noto Sans CJK SC",sans-serif}
.wrap{max-width:940px;margin:0 auto;padding:28px 20px 90px}
.toolbar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;
  margin-bottom:18px;padding:10px 12px;background:var(--card);
  border:1px solid var(--border);border-radius:12px}
.toolbar .spacer{flex:1}
button{font:inherit;font-size:13px;padding:5px 11px;border-radius:8px;
  border:1px solid var(--border);background:var(--bg);color:var(--text);cursor:pointer}
button:hover{border-color:var(--muted)}
header h1{margin:18px 0 6px;font-size:30px;line-height:1.35}
header .meta{color:var(--muted);font-size:13px;margin:0 0 6px}
header .meta a{color:var(--user)}
.toc{background:var(--card);border:1px solid var(--border);border-radius:12px;
  padding:12px 18px;margin:18px 0 26px}
.toc strong{font-size:13px;color:var(--muted);letter-spacing:.08em}
.toc ol{margin:6px 0 0;padding-left:22px}
.toc li{margin:3px 0}
.toc a{color:var(--text);text-decoration:none}
.toc a:hover{color:var(--user);text-decoration:underline}
.toc .count{color:var(--muted);font-size:12px}
section.conv{margin:0 0 34px}
section.conv>h2{font-size:22px;margin:30px 0 4px;padding-bottom:8px;
  border-bottom:1px solid var(--border)}
.qa{background:var(--card);border:1px solid var(--border);border-radius:14px;
  margin:16px 0;overflow:hidden;box-shadow:0 1px 2px rgba(0,0,0,.04)}
.block{padding:0}
.block+.block{border-top:1px solid var(--border)}
.block-head{display:flex;align-items:center;gap:8px;padding:7px 16px;
  font-size:12px;font-weight:700;letter-spacing:.04em}
.block-head .anchor{margin-left:auto;color:var(--muted);text-decoration:none;
  font-weight:400;font-size:12px;opacity:.6}
.block-head .anchor:hover{opacity:1;color:var(--user)}
.block-body{padding:4px 18px 14px;white-space:pre-wrap;word-wrap:break-word;
  overflow-wrap:anywhere}
.user .block-head{background:var(--user-bg);color:var(--user)}
.assistant .block-head{background:var(--ai-bg);color:var(--ai)}
.thinking{background:var(--think-bg);border-top:1px solid var(--border)}
.thinking summary{cursor:pointer;padding:8px 18px;color:var(--think);
  font-size:12px;font-weight:700;letter-spacing:.04em;user-select:none}
.thinking summary:hover{color:var(--text)}
.thinking .block-body{color:var(--think);font-size:14px;line-height:1.75;
  padding-top:0}
.thinking[open] summary{border-bottom:1px dashed var(--border)}
footer{margin-top:60px;padding-top:18px;border-top:1px solid var(--border);
  color:var(--muted);font-size:12px;text-align:center}
@media (max-width:640px){
  .wrap{padding:18px 12px 60px}
  header h1{font-size:24px}
  .block-body{padding:4px 13px 12px}
}
@media print{
  .toolbar{display:none}
  body{background:#fff;color:#000}
  .qa{box-shadow:none;break-inside:avoid}
  .thinking{border:1px solid #ddd}
}
"""

_HTML_JS = """
(function(){
  var think=document.getElementById('toggle-think');
  if(think){var open=false;think.addEventListener('click',function(){
    open=!open;
    document.querySelectorAll('details').forEach(function(d){d.open=open;});
    think.textContent=open?'收起全部思考':'展开全部思考';
  });}
  var dark=document.getElementById('toggle-dark');
  try{
    if(localStorage.getItem('mm-theme')==='dark'){document.body.classList.add('dark');}
  }catch(e){}
  if(dark){dark.addEventListener('click',function(){
    document.body.classList.toggle('dark');
    try{localStorage.setItem('mm-theme',
      document.body.classList.contains('dark')?'dark':'light');}catch(e){}
  });}
  var top=document.getElementById('back-top');
  if(top){top.addEventListener('click',function(){window.scrollTo({top:0,behavior:'smooth'});});}
})();
"""


def _safe_url(url: str) -> str:
    url = str(url or "").strip()
    if not url:
        return ""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return ""
    return url


def to_html(documents: Sequence[Dict[str, Any]], title: Optional[str] = None) -> str:
    """把若干对话导出为单文件、可离线阅读的 HTML。"""
    docs = [d for d in documents if isinstance(d, dict)]
    if title:
        page_title = title
    elif len(docs) == 1:
        page_title = conversation_title(docs[0])
    else:
        page_title = "AI 记忆导出"

    esc = lambda value: html.escape(str(value if value is not None else ""), quote=True)

    is_single = len(docs) == 1
    single_meta: List[str] = []
    toc_items = []
    sections = []
    for ci, data in enumerate(docs, 1):
        conv_title = conversation_title(data)
        pairs = [qa for qa in data.get("qa_pairs", []) if isinstance(qa, dict)]
        toc_items.append(
            f'<li><a href="#conv-{ci}">{esc(conv_title)}</a> '
            f'<span class="count">{fmt_count(len(pairs))} 组问答</span></li>'
        )

        header_meta = []
        if data.get("exported_at"):
            header_meta.append(f"导出时间 {esc(data['exported_at'])}")
        header_meta.append(f"{fmt_count(len(pairs))} 组问答")
        url = _safe_url(data.get("source_url", ""))
        if url:
            header_meta.append(f'来源 <a href="{esc(url)}" target="_blank" rel="noopener">{esc(url)}</a>')
        if is_single:
            single_meta = header_meta

        qa_blocks = []
        for qi, qa in enumerate(pairs, 1):
            anchor = f"qa-{ci}-{qi}"
            blocks = []
            question = qa_field(qa, "user")
            if question:
                blocks.append(
                    f'<div class="block user"><div class="block-head">用户 '
                    f'<a class="anchor" href="#{anchor}">#{qi}</a></div>'
                    f'<div class="block-body">{esc(question)}</div></div>'
                )
            thinking = qa_field(qa, "thinking")
            if thinking:
                seconds = parse_seconds(qa.get("thinking_seconds"))
                label = f"思考过程 · {seconds:.1f} 秒" if seconds else "思考过程"
                blocks.append(
                    f'<details class="block thinking"><summary>{esc(label)}</summary>'
                    f'<div class="block-body">{esc(thinking)}</div></details>'
                )
            answer = qa_field(qa, "ai")
            if answer:
                blocks.append(
                    f'<div class="block assistant"><div class="block-head">AI'
                    f'<a class="anchor" href="#{anchor}">#{qi}</a></div>'
                    f'<div class="block-body">{esc(answer)}</div></div>'
                )
            qa_blocks.append(f'<article class="qa" id="{anchor}">{"".join(blocks)}</article>')

        section_head = ""
        if not is_single:
            section_head = (
                f"<h2>{esc(conv_title)}</h2>"
                f'<p class="meta">{" · ".join(header_meta)}</p>'
            )
        sections.append(
            f'<section class="conv" id="conv-{ci}">'
            f"{section_head}{''.join(qa_blocks)}</section>"
        )

    toc = ""
    if len(docs) > 1:
        toc = (
            '<nav class="toc"><strong>目录</strong><ol>'
            + "".join(toc_items)
            + "</ol></nav>"
        )

    generated = datetime.now().strftime("%Y-%m-%d %H:%M")
    if is_single:
        page_meta = " · ".join(single_meta)
    else:
        page_meta = f"共 {fmt_count(len(docs))} 个对话 · 导出于 {esc(generated)}"
    return (
        "<!DOCTYPE html>\n"
        '<html lang="zh-CN">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{esc(page_title)}</title>\n"
        f"<style>{_HTML_CSS}</style>\n</head>\n<body>\n"
        '<div class="wrap">\n'
        '<div class="toolbar">'
        '<button id="toggle-think" type="button">展开全部思考</button>'
        '<button id="toggle-dark" type="button">夜间模式</button>'
        '<span class="spacer"></span>'
        '<button id="back-top" type="button">回到顶部</button>'
        "</div>\n"
        f"<header><h1>{esc(page_title)}</h1>"
        f'<p class="meta">{page_meta}</p></header>\n'
        f"{toc}\n"
        '<main id="top">\n' + "\n".join(sections) + "\n</main>\n"
        f'<footer>由 AI 记忆储存和管理器 v{VERSION} 生成 · 单文件离线存档</footer>\n'
        "</div>\n"
        f"<script>{_HTML_JS}</script>\n"
        "</body>\n</html>\n"
    )


# ---------------------------------------------------------------------------
# 统计与体检
# ---------------------------------------------------------------------------

def library_stats(
    library: "Library",
    data_loader: Optional[DataLoader] = None,
) -> Dict[str, Any]:
    loader = data_loader or library.read_conversation
    rows: List[Dict[str, Any]] = []
    for fname in library.sorted_fnames():
        meta = library.convs[fname]
        try:
            data = loader(fname)
        except (OSError, ValueError, DataError) as exc:
            rows.append({
                "file": fname, "title": meta.get("title", fname), "count": 0,
                "question_chars": 0, "answer_chars": 0, "thinking_chars": 0,
                "thinking_seconds": 0.0, "avg_answer_chars": 0,
                "tags": meta.get("tags", []), "error": str(exc),
            })
            continue
        pairs = [qa for qa in data.get("qa_pairs", []) if isinstance(qa, dict)]
        question_chars = sum(len(qa_field(qa, "user")) for qa in pairs)
        answer_chars = sum(len(qa_field(qa, "ai")) for qa in pairs)
        thinking_chars = sum(len(qa_field(qa, "thinking")) for qa in pairs)
        think_seconds = sum(parse_seconds(qa.get("thinking_seconds")) for qa in pairs)
        rows.append({
            "file": fname,
            "title": meta.get("title", fname),
            "count": len(pairs),
            "question_chars": question_chars,
            "answer_chars": answer_chars,
            "thinking_chars": thinking_chars,
            "thinking_seconds": think_seconds,
            "avg_answer_chars": answer_chars // len(pairs) if pairs else 0,
            "tags": list(meta.get("tags", [])),
            "error": "",
        })

    totals = {
        "conversations": len(rows),
        "missing": len(library.missing),
        "qa": sum(r["count"] for r in rows),
        "question_chars": sum(r["question_chars"] for r in rows),
        "answer_chars": sum(r["answer_chars"] for r in rows),
        "thinking_chars": sum(r["thinking_chars"] for r in rows),
        "thinking_seconds": sum(r["thinking_seconds"] for r in rows),
    }
    return {"rows": rows, "totals": totals}


def validate_library(library: "Library") -> Dict[str, Any]:
    """只读检查：缺文件、坏 JSON、空对话、字段缺失、重复内容。"""
    issues: List[Dict[str, str]] = []
    seen_hashes: Dict[str, str] = {}

    for fname in sorted(library.convs):
        meta = library.convs[fname]
        path = library.path(fname)
        if not os.path.isfile(path):
            issues.append({"severity": "error", "file": fname,
                           "message": "对话文件不存在"})
            continue
        try:
            data = load_json(path)
        except (ValueError, OSError) as exc:
            issues.append({"severity": "error", "file": fname,
                           "message": f"JSON 无法解析：{exc}"})
            continue
        if not is_conversation(data):
            issues.append({"severity": "error", "file": fname,
                           "message": "缺少 qa_pairs 数组，不是有效的对话文件"})
            continue

        digest = meta.get("sha1") or ""
        if not digest:
            try:
                digest = file_sha1(path)
            except OSError:
                digest = ""
        if digest:
            if digest in seen_hashes:
                issues.append({
                    "severity": "warning", "file": fname,
                    "message": f"内容与 {seen_hashes[digest]} 完全相同（重复导入）",
                })
            else:
                seen_hashes[digest] = fname

        pairs = data.get("qa_pairs", [])
        if not pairs:
            issues.append({"severity": "warning", "file": fname,
                           "message": "对话有 0 组问答"})
        empty_q = empty_a = 0
        for qa in pairs:
            if not isinstance(qa, dict):
                issues.append({"severity": "warning", "file": fname,
                               "message": "qa_pairs 中存在非对象条目"})
                break
            if not qa_field(qa, "user").strip():
                empty_q += 1
            if not qa_field(qa, "ai").strip():
                empty_a += 1
        if empty_q:
            issues.append({"severity": "warning", "file": fname,
                           "message": f"{empty_q} 组问答缺少用户提问"})
        if empty_a:
            issues.append({"severity": "warning", "file": fname,
                           "message": f"{empty_a} 组问答缺少 AI 回答"})

    for fname in sorted(library.missing):
        issues.append({
            "severity": "warning", "file": fname,
            "message": "对话文件缺失，元数据已保留"
                       "（把文件放回 conversations/ 后按 F5 自动恢复）",
        })

    errors = sum(1 for i in issues if i["severity"] == "error")
    return {
        "ok": errors == 0,
        "errors": errors,
        "warnings": len(issues) - errors,
        "issues": issues,
        "conversations": len(library.convs),
        "missing": len(library.missing),
    }


# ---------------------------------------------------------------------------
# 导入结果
# ---------------------------------------------------------------------------

@dataclass
class ImportResult:
    added: List[str] = field(default_factory=list)
    restored: List[str] = field(default_factory=list)
    duplicates: List[Tuple[str, str]] = field(default_factory=list)
    skipped: List[Tuple[str, str]] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.added) + len(self.restored) + len(self.duplicates) + len(self.skipped)


# ---------------------------------------------------------------------------
# 对话库
# ---------------------------------------------------------------------------

class Library:
    """管理 conversations/、trash/ 与 library.json 元数据。"""

    def __init__(self, root: Optional[str] = None):
        self.root = os.path.abspath(root or APP_DIR)
        self.dir = os.path.join(self.root, LIB_DIRNAME)
        self.trash_dir = os.path.join(self.root, TRASH_DIRNAME)
        self.file = os.path.join(self.root, LIB_FILENAME)
        self.trash_index_file = os.path.join(self.trash_dir, TRASH_INDEX_FILENAME)
        self.convs: Dict[str, Dict[str, Any]] = {}
        self.missing: Dict[str, Dict[str, Any]] = {}
        self.trash: Dict[str, Dict[str, Any]] = {}
        self.load_error = ""
        self.recovered_from_backup = False
        self.last_sync_changes = 0
        self._skip_backup_once = False

    # --- 初始化与元数据 ---

    def load(self) -> "Library":
        os.makedirs(self.dir, exist_ok=True)
        os.makedirs(self.trash_dir, exist_ok=True)
        self.convs = {}
        self.missing = {}
        self.load_error = ""
        self.recovered_from_backup = False

        if os.path.exists(self.file) or os.path.exists(self.file + ".bak"):
            try:
                data, recovered = load_json_recover(self.file)
                if not isinstance(data, dict):
                    raise DataError("library.json 顶层不是对象")
                raw = data.get("conversations", {})
                if not isinstance(raw, dict):
                    raise DataError("library.json 的 conversations 字段不是对象")
                self.convs = {
                    str(name): meta for name, meta in raw.items()
                    if isinstance(meta, dict)
                }
                raw_missing = data.get("missing", {})
                if isinstance(raw_missing, dict):
                    self.missing = {
                        str(name): meta for name, meta in raw_missing.items()
                        if isinstance(meta, dict)
                    }
                self.recovered_from_backup = recovered
                if recovered:
                    self._skip_backup_once = True
                    if os.path.exists(self.file):
                        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                        try:
                            shutil.copy2(self.file, self.file + f".corrupt-{stamp}")
                        except OSError:
                            pass
            except DataError as exc:
                self.load_error = str(exc)
                self.convs = {}
                if os.path.exists(self.file):
                    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                    try:
                        shutil.copy2(self.file, self.file + f".corrupt-{stamp}")
                    except OSError:
                        pass

        for fname, meta in self.convs.items():
            if "title_custom" not in meta:
                # v1.0 元数据没有这个字段；同步时根据“标题是否与文件不同”
                # 判断用户是否曾经手动重命名过。
                meta["_legacy_meta"] = True
            self._sanitize_meta(meta, fname)
        for fname, meta in self.missing.items():
            self._sanitize_meta(meta, fname)

        self._load_trash_index()
        changed = self.sync(save=False)
        if changed or self.recovered_from_backup or self.load_error:
            self.save(backup=not self._skip_backup_once)
        self._skip_backup_once = False
        self._sync_trash(save=True)
        return self

    def save(self, backup: bool = True) -> None:
        if backup and os.path.isfile(self.file):
            backup_file(self.file)
        payload: Dict[str, Any] = {
            "version": VERSION,
            "conversations": self.convs,
        }
        if self.missing:
            payload["missing"] = self.missing
        atomic_write_json(self.file, payload)

    def _sanitize_meta(self, meta: Dict[str, Any], fname: str) -> None:
        fallback = os.path.splitext(fname)[0]
        if not isinstance(meta.get("title"), str) or not meta["title"].strip():
            meta["title"] = fallback
        tags = meta.get("tags")
        meta["tags"] = [str(t) for t in tags if str(t).strip()] if isinstance(tags, list) else []
        meta["starred"] = bool(meta.get("starred"))
        try:
            meta["count"] = int(meta.get("count", 0))
        except (TypeError, ValueError):
            meta["count"] = 0
        if not isinstance(meta.get("added_at"), str):
            meta["added_at"] = ""
        if not isinstance(meta.get("exported_at"), str):
            meta["exported_at"] = ""
        if not isinstance(meta.get("sha1"), str):
            meta["sha1"] = ""
        meta["title_custom"] = bool(meta.get("title_custom"))

    def _make_meta(
        self,
        fname: str,
        data: Dict[str, Any],
        path: str,
        digest: Optional[str] = None,
    ) -> Dict[str, Any]:
        try:
            stat = os.stat(path)
            mtime_ns, size = stat.st_mtime_ns, stat.st_size
        except OSError:
            mtime_ns, size = 0, 0
        if digest is None:
            try:
                digest = file_sha1(path)
            except OSError:
                digest = ""
        return {
            "title": conversation_title(data, os.path.splitext(fname)[0]),
            "tags": [],
            "starred": False,
            "added_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "count": len(data.get("qa_pairs", [])),
            "exported_at": str(data.get("exported_at") or ""),
            "sha1": digest,
            "title_custom": False,
            "_mtime_ns": mtime_ns,
            "_size": size,
        }

    def _refresh_meta(self, meta: Dict[str, Any], fname: str, data: Dict[str, Any], path: str) -> None:
        new_title = conversation_title(data, os.path.splitext(fname)[0])
        if meta.get("_legacy_meta"):
            if meta.get("title") and meta.get("title") != new_title:
                meta["title_custom"] = True
            meta.pop("_legacy_meta", None)
        if not meta.get("title_custom"):
            meta["title"] = new_title
        meta["count"] = len(data.get("qa_pairs", []))
        meta["exported_at"] = str(data.get("exported_at") or "")
        try:
            stat = os.stat(path)
            meta["_mtime_ns"] = stat.st_mtime_ns
            meta["_size"] = stat.st_size
        except OSError:
            meta["_mtime_ns"] = 0
            meta["_size"] = 0
        try:
            meta["sha1"] = file_sha1(path)
        except OSError:
            meta["sha1"] = ""
        meta.pop("_invalid", None)

    # --- 同步 ---

    def sync(self, save: bool = True) -> bool:
        """让元数据跟目录里的文件保持一致，并刷新被外部修改的文件。"""
        changed = False
        changes = 0
        try:
            files = sorted(os.listdir(self.dir))
        except OSError:
            files = []

        for fname in files:
            if not fname.lower().endswith(".json") or fname.startswith("."):
                continue
            path = os.path.join(self.dir, fname)
            if not os.path.isfile(path):
                continue
            try:
                stat = os.stat(path)
            except OSError:
                continue
            meta = self.convs.get(fname)
            restored = False
            if meta is None and fname in self.missing:
                # 文件回来了：接回原来的元数据，保留星标/标签/自定义标题。
                meta = self.missing.pop(fname)
                self.convs[fname] = meta
                restored = True
            if (meta is not None
                    and meta.get("_mtime_ns") == stat.st_mtime_ns
                    and meta.get("_size") == stat.st_size):
                if restored:
                    changed = True
                    changes += 1
                continue
            try:
                data = load_json(path)
            except (ValueError, OSError):
                if meta is not None:
                    meta["_invalid"] = True
                    meta["_mtime_ns"] = stat.st_mtime_ns
                    meta["_size"] = stat.st_size
                    changed = True
                    changes += 1
                continue
            if not is_conversation(data):
                if restored:
                    self.convs.pop(fname, None)
                    self.missing[fname] = meta
                    changed = True
                    changes += 1
                continue
            if meta is None:
                self.convs[fname] = self._make_meta(fname, data, path)
            else:
                self._refresh_meta(meta, fname, data, path)
            changed = True
            changes += 1

        for fname in list(self.convs):
            path = os.path.join(self.dir, fname)
            if not os.path.isfile(path) or not fname.lower().endswith(".json"):
                # 文件缺失时不要丢掉元数据：归档到 missing，放回文件后自动恢复。
                meta = self.convs.pop(fname)
                meta.pop("_invalid", None)
                self.missing[fname] = meta
                changed = True
                changes += 1

        for fname in list(self.missing):
            if fname in self.convs:
                # 同名对话已经恢复，清掉过期的 missing 记录。
                del self.missing[fname]
                changed = True
                changes += 1

        self.last_sync_changes = changes
        if changed and save:
            self.save()
        return changed

    # --- 路径与读取 ---

    def path(self, fname: str) -> str:
        return os.path.join(self.dir, fname)

    def read_conversation(self, fname: str) -> Dict[str, Any]:
        path = self.path(fname)
        data = load_json(path)
        if not is_conversation(data):
            raise DataError(f"{fname} 不是有效的对话文件")
        return data

    # 兼容旧名字
    load_conversation = read_conversation

    def sorted_fnames(self, sort: str = "date", reverse: bool = True) -> List[str]:
        if sort == "title":
            key = lambda f: str(self.convs[f].get("title", "")).lower()
        elif sort == "count":
            key = lambda f: int(self.convs[f].get("count", 0))
        else:
            key = lambda f: (self.convs[f].get("exported_at")
                             or self.convs[f].get("added_at") or "")
        return sorted(self.convs, key=key, reverse=reverse)

    def all_tags(self) -> List[str]:
        tags = set()
        for meta in self.convs.values():
            tags.update(meta.get("tags", []))
        return sorted(tags)

    def missing_items(self) -> List[Dict[str, Any]]:
        items = []
        for fname, meta in self.missing.items():
            items.append({
                "file": fname,
                "title": meta.get("title") or os.path.splitext(fname)[0],
                "count": int(meta.get("count", 0) or 0),
            })
        items.sort(key=lambda item: item["title"])
        return items

    def tag_counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for meta in self.convs.values():
            for tag in meta.get("tags", []):
                counts[tag] = counts.get(tag, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))

    # --- 导入 ---

    def import_paths(self, paths: Iterable[str]) -> ImportResult:
        result = ImportResult()
        hash_index = {
            meta.get("sha1"): fname
            for fname, meta in self.convs.items()
            if meta.get("sha1")
        }
        missing_index = {
            meta.get("sha1"): fname
            for fname, meta in self.missing.items()
            if meta.get("sha1")
        }
        for src in paths:
            src = os.path.abspath(str(src))
            display = os.path.basename(src)
            if not os.path.isfile(src) or not src.lower().endswith(".json"):
                result.skipped.append((display, "不是 JSON 文件"))
                continue
            if os.path.normcase(os.path.dirname(src)) == os.path.normcase(
                    os.path.abspath(self.dir)):
                result.skipped.append((display, "文件已在对话库目录中"))
                continue
            try:
                data = load_json(src)
            except (ValueError, OSError) as exc:
                result.skipped.append((display, f"无法读取：{exc}"))
                continue
            if not is_conversation(data):
                result.skipped.append((display, "不是有效的对话 JSON"))
                continue
            try:
                digest = file_sha1(src)
            except OSError:
                digest = ""
            if digest and digest in hash_index:
                result.duplicates.append((display, self.convs[hash_index[digest]]["title"]))
                continue
            if digest and digest in missing_index:
                # 重新导入一个“文件缺失但元数据还在”的对话：恢复标题/标签/星标。
                old_fname = missing_index[digest]
                dst = unique_path(self.dir, display)
                try:
                    shutil.copy2(src, dst)
                except OSError as exc:
                    try:
                        if os.path.exists(dst):
                            os.remove(dst)
                    except OSError:
                        pass
                    result.skipped.append((display, f"复制失败：{exc}"))
                    continue
                fname = os.path.basename(dst)
                meta = self.missing.pop(old_fname, None)
                if isinstance(meta, dict):
                    self._sanitize_meta(meta, fname)
                    self._refresh_meta(meta, fname, data, dst)
                else:
                    meta = self._make_meta(fname, data, dst, digest=digest)
                self.convs[fname] = meta
                self.missing.pop(fname, None)
                hash_index[digest] = fname
                result.restored.append(fname)
                continue
            dst = unique_path(self.dir, display)
            try:
                shutil.copy2(src, dst)
            except OSError as exc:
                try:
                    if os.path.exists(dst):
                        os.remove(dst)
                except OSError:
                    pass
                result.skipped.append((display, f"复制失败：{exc}"))
                continue
            fname = os.path.basename(dst)
            self.convs[fname] = self._make_meta(fname, data, dst, digest=digest)
            self.missing.pop(fname, None)
            if digest:
                hash_index[digest] = fname
            result.added.append(fname)
        if result.added or result.restored:
            self.save()
        return result

    # --- 回收站 ---

    def _load_trash_index(self) -> None:
        self.trash = {}
        if os.path.isfile(self.trash_index_file):
            try:
                data, _ = load_json_recover(self.trash_index_file)
                items = data.get("items", {}) if isinstance(data, dict) else {}
                if isinstance(items, dict):
                    self.trash = {str(k): v for k, v in items.items() if isinstance(v, dict)}
            except DataError:
                self.trash = {}

    def _save_trash_index(self) -> None:
        atomic_write_json(self.trash_index_file, {"items": self.trash})

    def _sync_trash(self, save: bool = True) -> bool:
        changed = False
        try:
            files = {
                f for f in os.listdir(self.trash_dir)
                if f.lower().endswith(".json") and f != TRASH_INDEX_FILENAME
            }
        except OSError:
            files = set()
        for fname in sorted(files):
            if fname in self.trash:
                continue
            path = os.path.join(self.trash_dir, fname)
            meta = None
            title = os.path.splitext(fname)[0]
            count = 0
            try:
                data = load_json(path)
                if is_conversation(data):
                    title = conversation_title(data, title)
                    count = len(data.get("qa_pairs", []))
                    meta = {
                        "title": title,
                        "tags": [],
                        "starred": False,
                        "added_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                        "count": count,
                        "exported_at": str(data.get("exported_at") or ""),
                        "sha1": "",
                        "title_custom": False,
                    }
            except (ValueError, OSError):
                pass
            self.trash[fname] = {
                "original_name": fname,
                "meta": meta,
                "deleted_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "size": os.path.getsize(path) if os.path.isfile(path) else 0,
            }
            changed = True
        for fname in list(self.trash):
            if fname not in files:
                del self.trash[fname]
                changed = True
        if changed and save:
            self._save_trash_index()
        return changed

    def remove(self, fname: str) -> str:
        """移入回收站并记住元数据，可随时还原。"""
        if fname not in self.convs:
            raise KeyError(fname)
        src = self.path(fname)
        if not os.path.isfile(src):
            raise FileNotFoundError(src)
        dst = unique_path(self.trash_dir, fname)
        shutil.move(src, dst)
        trash_name = os.path.basename(dst)
        meta = self.convs.pop(fname, None)
        self.trash[trash_name] = {
            "original_name": fname,
            "meta": meta,
            "deleted_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "size": os.path.getsize(dst),
        }
        self._save_trash_index()
        self.save()
        return trash_name

    def trash_items(self) -> List[Dict[str, Any]]:
        items = []
        for trash_name, entry in self.trash.items():
            meta = entry.get("meta") or {}
            items.append({
                "trash_name": trash_name,
                "title": meta.get("title") or os.path.splitext(trash_name)[0],
                "original_name": entry.get("original_name") or trash_name,
                "count": int(meta.get("count", 0) or 0),
                "deleted_at": entry.get("deleted_at", ""),
                "size": int(entry.get("size", 0) or 0),
            })
        items.sort(key=lambda item: item["deleted_at"], reverse=True)
        return items

    def restore(self, trash_name: str) -> str:
        entry = self.trash.get(trash_name)
        if not entry:
            raise KeyError(trash_name)
        src = os.path.join(self.trash_dir, trash_name)
        if not os.path.isfile(src):
            self.trash.pop(trash_name, None)
            self._save_trash_index()
            raise FileNotFoundError(src)
        original = entry.get("original_name") or trash_name
        dst = unique_path(self.dir, original)
        shutil.move(src, dst)
        fname = os.path.basename(dst)
        meta = entry.get("meta")
        try:
            data = load_json(dst)
        except (ValueError, OSError):
            data = {"qa_pairs": []}
        if not isinstance(meta, dict):
            meta = self._make_meta(fname, data, dst)
        else:
            self._sanitize_meta(meta, fname)
            self._refresh_meta(meta, fname, data, dst)
        self.convs[fname] = meta
        self.missing.pop(fname, None)
        self.trash.pop(trash_name, None)
        self._save_trash_index()
        self.save()
        return fname

    def purge(self, trash_name: str) -> bool:
        path = os.path.join(self.trash_dir, trash_name)
        removed = False
        if os.path.isfile(path):
            try:
                os.remove(path)
                removed = True
            except OSError:
                raise
        if self.trash.pop(trash_name, None) is not None:
            removed = True
        if removed:
            self._save_trash_index()
        return removed

    def empty_trash(self) -> int:
        count = 0
        for trash_name in list(self.trash):
            try:
                if self.purge(trash_name):
                    count += 1
            except OSError:
                continue
        # 清理索引之外、手工丢进 trash/ 的文件
        try:
            for fname in os.listdir(self.trash_dir):
                if fname == TRASH_INDEX_FILENAME:
                    continue
                path = os.path.join(self.trash_dir, fname)
                if os.path.isfile(path):
                    try:
                        os.remove(path)
                        count += 1
                    except OSError:
                        pass
        except OSError:
            pass
        self.trash = {}
        self._save_trash_index()
        return count


# ---------------------------------------------------------------------------
# 应用状态
# ---------------------------------------------------------------------------

class Settings:
    """窗口位置、主题、上次阅读位置等轻量状态。"""

    def __init__(self, root: Optional[str] = None):
        self.root = os.path.abspath(root or APP_DIR)
        self.path = os.path.join(self.root, SETTINGS_FILENAME)
        self.data: Dict[str, Any] = {}

    def load(self) -> Dict[str, Any]:
        try:
            data = load_json(self.path)
            if isinstance(data, dict):
                self.data = data
        except (OSError, ValueError):
            self.data = {}
        return self.data

    def save(self) -> None:
        try:
            atomic_write_json(self.path, self.data)
        except OSError:
            pass

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value
