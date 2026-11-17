#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DeepSeek 聊天备份 v3 解析与自动分对话。

新版备份目录通常长这样：
    聊天备份/
        manifest.json                 {"export_format_version": 3}
        chat_session_index.json       [{id, title, message_count, ...}, ...]
        chat_sessions/<session-id>.json
        chat_sessions/<session-id>_files/...

每个 session 文件是一段会话，但 messages 是树状结构：同一个提示的重试、
重新生成会产生多个 root 或分支。这里为每个 session 选择消息量最大的根线程，
再取其中最长的一条分支，转换成应用现有的 conversation JSON，保证不会把
所有对话揉成一条，也不会把重试分支误当成多个独立对话。
"""

from __future__ import annotations

import json
import os
import re
import difflib
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

EXPORT_VERSION = 3


class BackupFormatError(ValueError):
    """不是可识别的 DeepSeek v3 聊天备份。"""


@dataclass
class SplitConversation:
    filename: str
    data: Dict[str, Any]
    session_id: str
    title: str
    total_messages: int
    active_messages: int
    branches: int


# ---------------------------------------------------------------------------
# 格式识别
# ---------------------------------------------------------------------------

def _load_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _looks_like_backup(path: str) -> bool:
    if not os.path.isdir(path):
        return False
    sessions = os.path.join(path, "chat_sessions")
    if not os.path.isdir(sessions):
        return False
    manifest = os.path.join(path, "manifest.json")
    if os.path.isfile(manifest):
        try:
            version = int(_load_json(manifest).get("export_format_version", 0))
        except (ValueError, OSError, AttributeError, TypeError):
            version = 0
        if version >= EXPORT_VERSION:
            return True
    # manifest 偶尔缺失，但 index + chat_sessions 同时存在时也按 v3 处理。
    return os.path.isfile(os.path.join(path, "chat_session_index.json"))


def detect_v3_backup(path: str) -> Optional[str]:
    """返回真正的备份根目录；也支持用户选中包含备份的上一级目录。"""
    path = os.path.abspath(path)
    if _looks_like_backup(path):
        return path
    try:
        names = os.listdir(path)
    except OSError:
        return None
    for name in names:
        child = os.path.join(path, name)
        if os.path.isdir(child) and _looks_like_backup(child):
            return child
    return None


# ---------------------------------------------------------------------------
# 消息树 -> 线性对话
# ---------------------------------------------------------------------------

def _subtree_ids(root: Dict[str, Any],
                 children: Dict[Any, List[Dict[str, Any]]]) -> set:
    seen = set()
    stack = [root]
    while stack:
        message = stack.pop()
        message_id = message.get("id")
        if message_id in seen:
            continue
        seen.add(message_id)
        stack.extend(children.get(message_id, []))
    return seen


def _depth(message: Dict[str, Any], by_id: Dict[Any, Dict[str, Any]]) -> int:
    depth = 0
    seen = set()
    current = message
    while current is not None:
        message_id = current.get("id")
        if message_id in seen:
            break
        seen.add(message_id)
        depth += 1
        current = by_id.get(current.get("parent_id"))
    return depth


def _main_path(root: Dict[str, Any],
               by_id: Dict[Any, Dict[str, Any]],
               children: Dict[Any, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """在主 root 内选最长分支；长度相同取最后更新的叶子。"""
    subtree = _subtree_ids(root, children)
    leaves = [
        message for message in by_id.values()
        if message.get("id") in subtree and not children.get(message.get("id"))
    ]
    if not leaves:
        leaves = [root]
    leaf = max(
        leaves,
        key=lambda message: (
            _depth(message, by_id),
            str(message.get("inserted_at") or ""),
        ),
    )
    path: List[Dict[str, Any]] = []
    seen = set()
    current: Optional[Dict[str, Any]] = leaf
    while current is not None:
        message_id = current.get("id")
        if message_id in seen:
            break
        seen.add(message_id)
        path.append(current)
        current = by_id.get(current.get("parent_id"))
    path.reverse()
    return path


def _fragment_text(fragments: Sequence[Dict[str, Any]], kind: str) -> str:
    parts = [
        str(fragment.get("content") or "").strip()
        for fragment in fragments
        if fragment.get("type") == kind
    ]
    return "\n\n".join(part for part in parts if part)


def _format_size(size: Any) -> str:
    try:
        size = int(size)
    except (TypeError, ValueError):
        return ""
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / 1024 / 1024:.1f} MB"


def _file_attachments(fragment: Dict[str, Any]) -> List[Dict[str, Any]]:
    attachments = []
    for item in fragment.get("files", []) or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("file_name") or "附件").strip()
        attachments.append({
            "name": name,
            "size": item.get("file_size"),
            "is_image": bool(item.get("is_image")),
            "path": item.get("export_path") or "",
        })
    return attachments


def _attachment_note(attachments: Sequence[Dict[str, Any]]) -> str:
    lines = []
    for item in attachments:
        label = "图片" if item.get("is_image") else "文件"
        size = _format_size(item.get("size"))
        lines.append(f"[{label}] {item.get('name')}" + (f"（{size}）" if size else ""))
    return "\n".join(lines)


def _reference(item: Dict[str, Any]) -> Optional[Dict[str, str]]:
    if not isinstance(item, dict):
        return None
    title = str(item.get("title") or item.get("site_name") or "").strip()
    url = str(item.get("url") or "").strip()
    snippet = str(item.get("snippet") or "").strip()
    if not title and not url:
        return None
    return {"title": title, "url": url, "snippet": snippet}


def _tool_references(fragment: Dict[str, Any]) -> List[Dict[str, str]]:
    kind = fragment.get("type")
    items: List[Any] = []
    if kind in ("TOOL_SEARCH", "TOOL_IMAGE_SEARCH"):
        items = fragment.get("results", []) or []
    elif kind == "TOOL_OPEN":
        items = [fragment]
    refs = []
    for item in items:
        ref = _reference(item)
        if ref:
            refs.append(ref)
    return refs


def _new_turn(message: Dict[str, Any]) -> Dict[str, Any]:
    fragments = [f for f in message.get("fragments", []) if isinstance(f, dict)]
    question = _fragment_text(fragments, "REQUEST")
    attachments: List[Dict[str, Any]] = []
    for fragment in fragments:
        if fragment.get("type") == "FILE":
            attachments.extend(_file_attachments(fragment))
    note = _attachment_note(attachments)
    if note:
        question = (question + "\n\n" + note).strip() if question else note
    return {
        "question": question,
        "thinking": [],
        "thinking_seconds": 0.0,
        "answers": [],
        "references": [],
        "attachments": list(attachments),
        "statuses": [],
        "search_queries": [],
    }


def _add_assistant(turn: Dict[str, Any], message: Dict[str, Any]) -> None:
    fragments = [f for f in message.get("fragments", []) if isinstance(f, dict)]
    status = message.get("status")
    if status:
        turn["statuses"].append(str(status))
    for fragment in fragments:
        kind = fragment.get("type")
        if kind == "THINK":
            content = str(fragment.get("content") or "").strip()
            if content:
                turn["thinking"].append(content)
            try:
                turn["thinking_seconds"] += float(fragment.get("elapsed_secs") or 0)
            except (TypeError, ValueError):
                pass
        elif kind in ("RESPONSE", "TEMPLATE_RESPONSE"):
            content = str(fragment.get("content") or "").strip()
            if content:
                turn["answers"].append(content)
        elif kind == "FILE":
            attachments = _file_attachments(fragment)
            turn["attachments"].extend(attachments)
            note = _attachment_note(attachments)
            if note:
                turn["answers"].append(note)
        elif kind in ("TOOL_SEARCH", "TOOL_OPEN", "TOOL_IMAGE_SEARCH"):
            turn["references"].extend(_tool_references(fragment))
            queries = fragment.get("queries") or []
            if isinstance(queries, list):
                turn["search_queries"].extend(str(q) for q in queries if q)
            elif queries:
                turn["search_queries"].append(str(queries))
        elif kind == "CONTENT_RISK":
            # 这是“AI 生成，仅供参考”之类的界面提示，不属于回答正文。
            continue
        elif kind == "TIP":
            continue


def _finalize_turn(turn: Dict[str, Any], index: int) -> Optional[Dict[str, Any]]:
    question = str(turn.get("question") or "").strip()
    answer = "\n\n".join(part for part in turn["answers"] if part).strip()
    thinking = "\n\n".join(part for part in turn["thinking"] if part).strip()
    seconds = float(turn.get("thinking_seconds") or 0)
    if not question and not answer and not thinking:
        return None
    pair: Dict[str, Any] = {
        "index": index,
        "question": question,
        "thinking_seconds": f"{seconds:.2f}秒" if seconds > 0 else "",
        "thinking": thinking,
        "deepseek": answer,
        "references": turn["references"],
    }
    if turn.get("attachments"):
        pair["attachments"] = turn["attachments"]
    if turn.get("statuses"):
        pair["source_statuses"] = turn["statuses"]
    if turn.get("search_queries"):
        pair["search_queries"] = list(dict.fromkeys(turn["search_queries"]))
    return pair


def _build_pairs(path: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    pairs: List[Dict[str, Any]] = []
    turn: Optional[Dict[str, Any]] = None
    for message in path:
        role = str(message.get("role") or "").upper()
        if role == "USER":
            if turn is not None:
                pair = _finalize_turn(turn, len(pairs) + 1)
                if pair:
                    pairs.append(pair)
            turn = _new_turn(message)
        elif role == "ASSISTANT":
            if turn is None:
                continue
            _add_assistant(turn, message)
    if turn is not None:
        pair = _finalize_turn(turn, len(pairs) + 1)
        if pair:
            pairs.append(pair)
    # 同一回答里可能出现重复的搜索结果。
    for pair in pairs:
        seen = set()
        unique = []
        for ref in pair.get("references", []):
            key = (ref.get("url"), ref.get("title"))
            if key in seen:
                continue
            seen.add(key)
            unique.append(ref)
        pair["references"] = unique
    return pairs


# ---------------------------------------------------------------------------
# 标题与时间
# ---------------------------------------------------------------------------

def _strip_ui_preamble(text: str) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    marker = text.rfind("code window")
    if marker >= 0:
        tail = text[marker + len("code window"):].lstrip(" \t\r\n-—:：")
        if len(tail) >= 2:
            return tail.strip()
    return text


def _derive_title(text: str) -> str:
    cleaned = _strip_ui_preamble(text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -—:：")
    if not cleaned:
        return "未命名对话"
    if cleaned.startswith("Communicate as an") or "strictly executes user requests" in cleaned[:220]:
        # 这类消息常常是“越狱指令 + 真正请求”拼在一起；真正请求一般在最后一行。
        lines = [line.strip() for line in str(text).splitlines() if line.strip()]
        if lines:
            tail = lines[-1].lstrip("-*• ").strip()
            if len(tail) >= 8:
                cleaned = tail
            else:
                return "未命名对话"
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -—:：")
    if len(cleaned) > 30:
        cleaned = cleaned[:29].rstrip() + "…"
    return cleaned or "未命名对话"


def _local_time(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone()
        return parsed.strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return text


def _safe_filename(title: str, date_key: str, session_id: str,
                   split_index: int = 0) -> str:
    safe = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", str(title or ""))
    safe = re.sub(r"\s+", "_", safe).strip(" ._")[:32]
    parts = ["DeepSeek", date_key or "backup"]
    if safe:
        parts.append(safe)
    parts.append((session_id or "session")[:8])
    if split_index > 1:
        parts.append(str(split_index))
    return "_".join(parts) + ".json"


# ---------------------------------------------------------------------------
# 会话转换
# ---------------------------------------------------------------------------

def _request_signature(message: Dict[str, Any]) -> str:
    """提取用于判断“是不是同一段对话”的用户请求文本。"""
    fragments = [f for f in message.get("fragments", []) if isinstance(f, dict)]
    raw = _fragment_text(fragments, "REQUEST")
    text = re.sub(r"\s+", " ", raw).strip()
    marker = text.rfind("code window")
    if marker >= 0:
        tail = text[marker + len("code window"):].lstrip(" \t-—:：")
        if len(tail) >= 2:
            return tail
    if text.startswith("Communicate as an") or "strictly executes user requests" in text[:220]:
        lines = [line.strip() for line in str(raw).splitlines() if line.strip()]
        if lines:
            tail = lines[-1].lstrip("-*• ").strip()
            if len(tail) >= 8:
                return tail
    return text


def _prompts_similar(first: str, second: str) -> bool:
    first = (first or "").strip()
    second = (second or "").strip()
    if not first or not second:
        return first == second
    if first == second or first.startswith(second) or second.startswith(first):
        return True
    return difflib.SequenceMatcher(None, first, second).ratio() >= 0.62


def _cluster_roots(roots: Sequence[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    """把同一提示的重试 root 合并；不同请求则分成不同对话。"""
    signatures = {message.get("id"): _request_signature(message)
                  for message in roots}
    parent = {message.get("id"): message.get("id") for message in roots}

    def find(key: Any) -> Any:
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    def union(first: Any, second: Any) -> None:
        parent[find(first)] = find(second)

    for index, first in enumerate(roots):
        for second in roots[index + 1:]:
            if _prompts_similar(signatures.get(first.get("id"), ""),
                                signatures.get(second.get("id"), "")):
                union(first.get("id"), second.get("id"))

    grouped: Dict[Any, List[Dict[str, Any]]] = defaultdict(list)
    for message in roots:
        grouped[find(message.get("id"))].append(message)
    clusters = list(grouped.values())
    clusters.sort(key=lambda group: min(
        str(message.get("inserted_at") or "") for message in group))
    return clusters


def _convert_session(session: Dict[str, Any],
                     title_hint: Optional[str] = None,
                     session_id: str = "") -> List[SplitConversation]:
    messages = [m for m in session.get("messages", []) if isinstance(m, dict)]
    if not messages:
        return []
    by_id = {m.get("id"): m for m in messages if m.get("id") is not None}
    children: Dict[Any, List[Dict[str, Any]]] = defaultdict(list)
    for message in messages:
        children[message.get("parent_id")].append(message)

    roots = [
        message for message in messages
        if message.get("parent_id") is None and message.get("id") is not None
    ]
    if not roots:
        roots = [messages[0]]
    clusters = _cluster_roots(roots)
    main_root = max(
        roots,
        key=lambda message: (
            len(_subtree_ids(message, children)),
            str(message.get("inserted_at") or ""),
        ),
    )

    sid = str(session.get("id") or session_id or "")
    default_title = str(title_hint or session.get("title") or "").strip()
    exported_at = _local_time(
        session.get("updated_at")
        or (messages[-1].get("inserted_at") if messages else "")
    )
    date_key = re.sub(r"\D", "", exported_at)[:8] or re.sub(r"\W", "", sid)[:8]
    created_at = _local_time(session.get("inserted_at"))

    prepared: List[Dict[str, Any]] = []
    for group in clusters:
        # 同一提示的重试：选消息量最大的 root；再取其中最长分支。
        representative = max(
            group,
            key=lambda message: (
                len(_subtree_ids(message, children)),
                str(message.get("inserted_at") or ""),
            ),
        )
        path = _main_path(representative, by_id, children)
        pairs = _build_pairs(path)
        if not pairs:
            continue

        first_question = ""
        for message in path:
            if str(message.get("role") or "").upper() == "USER":
                fragments = [f for f in message.get("fragments", []) if isinstance(f, dict)]
                first_question = _fragment_text(fragments, "REQUEST")
                break
        if not first_question:
            first_question = pairs[0].get("question", "")

        hint = default_title if main_root in group else ""
        title = str(hint or "").strip() or _derive_title(first_question)
        data: Dict[str, Any] = {
            "conversation_title": title,
            "exported_at": exported_at,
            "source_url": f"https://chat.deepseek.com/a/chat/s/{sid}" if sid else "",
            "source_type": "deepseek_backup_v3",
            "source_session_id": sid,
            "source_created_at": created_at,
            "source_updated_at": _local_time(session.get("updated_at")),
            "source_message_count": len(messages),
            "source_active_message_count": len(path),
            "source_branch_roots": len(roots),
            "source_cluster_roots": len(group),
            "qa_pairs": pairs,
        }
        prepared.append({"title": title, "path": path, "data": data})

    output: List[SplitConversation] = []
    split_count = len(prepared)
    for index, item in enumerate(prepared, 1):
        data = item["data"]
        data["source_split_index"] = index
        data["source_split_count"] = split_count
        output.append(SplitConversation(
            filename=_safe_filename(item["title"], date_key, sid,
                                    index if split_count > 1 else 0),
            data=data,
            session_id=sid,
            title=item["title"],
            total_messages=len(messages),
            active_messages=len(item["path"]),
            branches=len(roots),
        ))
    return output


def _read_index(root: str) -> List[Dict[str, Any]]:
    path = os.path.join(root, "chat_session_index.json")
    if not os.path.isfile(path):
        return []
    try:
        raw = _load_json(path)
    except (ValueError, OSError):
        return []
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def convert_backup(path: str) -> List[SplitConversation]:
    """把一个 v3 备份目录转换成若干 conversation JSON（内存中）。"""
    root = detect_v3_backup(path)
    if not root:
        raise BackupFormatError(f"不是 DeepSeek v3 聊天备份目录：{path}")
    sessions_dir = os.path.join(root, "chat_sessions")
    index_entries = _read_index(root)
    output: List[SplitConversation] = []
    used = set()

    for entry in index_entries:
        sid = str(entry.get("id") or "").strip()
        if not sid or sid in used:
            continue
        used.add(sid)
        session_path = os.path.join(sessions_dir, sid + ".json")
        if not os.path.isfile(session_path):
            continue
        try:
            session = _load_json(session_path)
        except (ValueError, OSError):
            continue
        if not isinstance(session, dict):
            continue
        converted = _convert_session(
            session, title_hint=entry.get("title"), session_id=sid)
        output.extend(converted)

    # index 没覆盖到的 session 也尽量接住。
    try:
        names = sorted(os.listdir(sessions_dir))
    except OSError:
        names = []
    for name in names:
        if not name.lower().endswith(".json"):
            continue
        sid = os.path.splitext(name)[0]
        if sid in used:
            continue
        used.add(sid)
        session_path = os.path.join(sessions_dir, name)
        try:
            session = _load_json(session_path)
        except (ValueError, OSError):
            continue
        if not isinstance(session, dict):
            continue
        converted = _convert_session(
            session, title_hint=session.get("title"), session_id=sid)
        output.extend(converted)

    return output


def convert_session_file_all(path: str,
                             title: Optional[str] = None) -> List[SplitConversation]:
    """转换单个 chat_sessions/<id>.json，可能得到多条独立对话。"""
    try:
        session = _load_json(path)
    except (ValueError, OSError):
        return []
    if not isinstance(session, dict):
        return []
    sid = str(session.get("id") or os.path.splitext(os.path.basename(path))[0])
    return _convert_session(session, title_hint=title, session_id=sid)


def convert_session_file(path: str, title: Optional[str] = None) -> Optional[SplitConversation]:
    """转换单个会话文件并返回主对话（兼容单文件导入的旧调用）。"""
    items = convert_session_file_all(path, title=title)
    return items[0] if items else None
