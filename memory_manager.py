#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 记忆储存和管理器
管理 JSON 格式的 AI 对话记录：导入、浏览、全文搜索、星标、标签、合并导出、Markdown 导出、统计
纯标准库实现（tkinter），无需第三方依赖。
"""

import json
import os
import shutil
import tkinter as tk
from datetime import datetime
from tkinter import ttk, filedialog, messagebox, simpledialog

APP_DIR = os.path.dirname(os.path.abspath(__file__))
LIB_DIR = os.path.join(APP_DIR, "conversations")
TRASH_DIR = os.path.join(APP_DIR, "trash")
LIB_FILE = os.path.join(APP_DIR, "library.json")

# 兼容不同导出脚本的字段名
Q_KEYS = ("question", "user", "q")
A_KEYS = ("deepseek", "answer", "ai", "response")
T_KEYS = ("thinking", "think", "reasoning")

# 配色
C_BG = "#f5f6f8"        # 全局底色
C_CARD_BG = "#ffffff"   # 卡片正文底
C_BORDER = "#dfe3e8"    # 卡片描边
C_USER = "#1a5fb4"      # 用户色
C_USER_HEAD = "#eaf2fb"
C_THINK = "#8a8f98"     # 思考色
C_THINK_HEAD = "#f0f1f3"
C_THINK_BG = "#fafbfc"
C_AI = "#1f9d63"        # AI 色
C_AI_HEAD = "#e9f7f0"
C_HL = "#ffe98a"        # 搜索高亮

FONT = ("Microsoft YaHei UI", 10)
FONT_THINK = ("Microsoft YaHei UI", 9)
FONT_HEAD = ("Microsoft YaHei UI", 9, "bold")
FONT_TITLE = ("Microsoft YaHei UI", 13, "bold")


# ---------- 工具函数 ----------

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def first_key(d, keys):
    for k in keys:
        v = d.get(k)
        if v:
            return v
    return ""


def parse_seconds(s):
    try:
        return float(str(s).replace("秒", "").strip())
    except (ValueError, TypeError):
        return 0.0


def fmt_count(n):
    return f"{n:,}" if isinstance(n, int) else str(n)


def unique_path(directory, filename):
    """目录下同名文件时自动加序号"""
    path = os.path.join(directory, filename)
    if not os.path.exists(path):
        return path
    stem, ext = os.path.splitext(filename)
    i = 1
    while True:
        path = os.path.join(directory, f"{stem}_{i}{ext}")
        if not os.path.exists(path):
            return path
        i += 1


def is_conversation(data):
    return isinstance(data, dict) and isinstance(data.get("qa_pairs"), list)


# ---------- 对话库 ----------

class Library:
    """管理 conversations/ 目录与 library.json 元数据"""

    def __init__(self):
        self.convs = {}  # fname -> {title, tags, starred, added_at, count, exported_at}

    def load(self):
        os.makedirs(LIB_DIR, exist_ok=True)
        if os.path.exists(LIB_FILE):
            try:
                raw = load_json(LIB_FILE)
                self.convs = raw.get("conversations", {})
            except (json.JSONDecodeError, OSError):
                self.convs = {}
        self.sync()

    def save(self):
        save_json(LIB_FILE, {"conversations": self.convs})

    def sync(self):
        """扫描 conversations/ 目录，与元数据双向同步"""
        changed = False
        for fname in os.listdir(LIB_DIR):
            if not fname.lower().endswith(".json") or fname in self.convs:
                continue
            try:
                data = load_json(os.path.join(LIB_DIR, fname))
            except (json.JSONDecodeError, OSError):
                continue
            if not is_conversation(data):
                continue
            self.convs[fname] = self._make_meta(fname, data)
            changed = True
        for fname in list(self.convs):
            if not os.path.exists(os.path.join(LIB_DIR, fname)):
                del self.convs[fname]
                changed = True
        if changed:
            self.save()

    def _make_meta(self, fname, data):
        return {
            "title": data.get("conversation_title") or os.path.splitext(fname)[0],
            "tags": [],
            "starred": False,
            "added_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "count": len(data.get("qa_pairs", [])),
            "exported_at": data.get("exported_at", ""),
        }

    def import_paths(self, paths):
        added, skipped = [], []
        for src in paths:
            if not os.path.isfile(src) or not src.lower().endswith(".json"):
                continue
            try:
                data = load_json(src)
            except (json.JSONDecodeError, OSError):
                skipped.append(os.path.basename(src))
                continue
            if not is_conversation(data):
                skipped.append(os.path.basename(src))
                continue
            dst = unique_path(LIB_DIR, os.path.basename(src))
            shutil.copy2(src, dst)
            fname = os.path.basename(dst)
            self.convs[fname] = self._make_meta(fname, data)
            added.append(fname)
        if added:
            self.save()
        return added, skipped

    def remove(self, fname):
        """移入库回收站并删除记录"""
        os.makedirs(TRASH_DIR, exist_ok=True)
        src = os.path.join(LIB_DIR, fname)
        if os.path.exists(src):
            shutil.move(src, unique_path(TRASH_DIR, fname))
        self.convs.pop(fname, None)
        self.save()

    def path(self, fname):
        return os.path.join(LIB_DIR, fname)

    def all_tags(self):
        tags = set()
        for meta in self.convs.values():
            tags.update(meta.get("tags", []))
        return sorted(tags)


# ---------- 详情区：独立卡片（用户 / 思考 / AI） ----------

class DetailView(ttk.Frame):
    """右侧详情：标题区 + 导航区 + 独立卡片（用户/思考/AI），Canvas 统一滚动"""

    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.qa = None
        self.keyword = None
        self._texts = []            # 需要自适应高度的 Text
        self._think_body = None     # 思考卡片正文（折叠用）
        self._wheel_on = False

        # 标题区（当前对话）
        head = ttk.Frame(self, padding=(12, 8, 12, 2))
        head.pack(fill="x")
        self.title_lbl = ttk.Label(head, text="选择左侧对话开始浏览", font=FONT_TITLE)
        self.title_lbl.pack(side="left")
        self.star_btn = ttk.Button(head, text="☆", width=3,
                                   command=app._toggle_star_current)
        self.star_btn.pack(side="left", padx=6)
        self.meta_lbl = ttk.Label(head, text="", foreground="#888")
        self.meta_lbl.pack(side="right")

        # 导航区
        nav = ttk.Frame(self, padding=(12, 0, 12, 2))
        nav.pack(fill="x")
        self.pos_lbl = ttk.Label(nav, text="未选择", width=14, anchor="w")
        self.pos_lbl.pack(side="left")
        ttk.Button(nav, text="◀ 上一条", width=9,
                   command=lambda: app.step_qa(-1)).pack(side="left", padx=2)
        ttk.Button(nav, text="下一条 ▶", width=9,
                   command=lambda: app.step_qa(1)).pack(side="left")
        ttk.Label(nav, text="点击思考标题条可折叠", foreground="#aaa").pack(side="left", padx=10)
        ttk.Button(nav, text="复制本条", command=self._copy).pack(side="right")

        # 卡片滚动区
        self.canvas = tk.Canvas(self, bg=C_BG, highlightthickness=0)
        self.canvas.pack(side="left", fill="both", expand=True)
        ysb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        ysb.pack(side="right", fill="y")
        self.canvas.configure(yscrollcommand=ysb.set)

        self.inner = tk.Frame(self.canvas, bg=C_BG)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.bind("<Configure>", self._on_resize)

        # 滚轮：Windows 下事件按焦点投递，组件级绑定不可靠；
        # 进入本区域时接管全局滚轮，离开时释放
        self.bind("<Enter>", lambda e: self._set_wheel(True))
        self.bind("<Leave>", lambda e: self._set_wheel(False))

    # --- 对话标题 ---

    def set_conv(self, title, meta_text, starred):
        self.title_lbl.config(text=title)
        self.meta_lbl.config(text=meta_text)
        self.star_btn.config(text="★" if starred else "☆")

    def clear(self):
        self.set_conv("选择左侧对话开始浏览", "", False)
        self.show(None)

    # --- 滚轮 ---

    def _set_wheel(self, on):
        if on == self._wheel_on:
            return
        if on:
            self.bind_all("<MouseWheel>", self._on_wheel, add="+")
        else:
            self.unbind_all("<MouseWheel>")
        self._wheel_on = on

    def _on_wheel(self, event):
        units = abs(event.delta) // 120 or 1
        self.canvas.yview_scroll(-units if event.delta > 0 else units, "units")
        return "break"

    # --- 渲染 ---

    def show(self, qa, keyword=None):
        self.qa = qa
        self.keyword = keyword
        for w in self.inner.winfo_children():
            w.destroy()
        self._texts = []
        self._think_body = self._think_head = None
        if not qa:
            self.pos_lbl.config(text="未选择")
            self._update_scroll()
            return

        question = str(first_key(qa, Q_KEYS))
        thinking = str(first_key(qa, T_KEYS))
        answer = str(first_key(qa, A_KEYS))

        self._add_card("用户", question, C_USER, C_USER_HEAD, C_CARD_BG, font=FONT)
        if thinking:
            sec = parse_seconds(qa.get("thinking_seconds"))
            self._add_card(f"思考过程  ·  {sec:.1f} 秒", thinking,
                           C_THINK, C_THINK_HEAD, C_THINK_BG,
                           font=FONT_THINK, fg="#6b7280", collapsible=True)
        self._add_card("AI", answer, C_AI, C_AI_HEAD, C_CARD_BG, font=FONT)
        tk.Frame(self.inner, bg=C_BG, height=16).pack(fill="x")  # 底部留白

        self.pos_lbl.config(text=f"第 {self.app.qa_pos()} / {self.app.qa_total()} 条")
        self._update_scroll()
        self.canvas.yview_moveto(0)

    def _add_card(self, title, body, accent, head_bg, body_bg,
                  font=FONT, fg="#222", collapsible=False):
        card = tk.Frame(self.inner, bg=body_bg, highlightbackground=C_BORDER,
                        highlightthickness=1)
        card.pack(fill="x", padx=12, pady=(10, 0), ipadx=1, ipady=1)

        head = tk.Frame(card, bg=head_bg, cursor="hand2" if collapsible else "")
        head.pack(fill="x")
        bar = tk.Frame(head, bg=accent, width=4)
        bar.pack(side="left", fill="y")
        tk.Label(head, text=title, bg=head_bg, fg=accent, font=FONT_HEAD,
                 anchor="w", padx=8, pady=4).pack(side="left")

        body_frame = tk.Frame(card, bg=body_bg)
        body_frame.pack(fill="x")
        text = tk.Text(body_frame, wrap="word", bd=0, padx=12, pady=8,
                       bg=body_bg, fg=fg, font=font, width=10, height=2,
                       highlightthickness=0, cursor="arrow")
        text.pack(fill="x")
        text.insert("1.0", body.rstrip())
        if self.keyword:
            self._highlight(text, self.keyword)
        text.configure(state="disabled")
        self._texts.append(text)
        # widget 级绑定优先执行并 break，阻止 disabled Text 自带的滚轮处理
        text.bind("<MouseWheel>", self._on_wheel)

        if collapsible:
            self._think_body, self._think_head = body_frame, head
            head.bind("<Button-1>", lambda e: self.toggle_think())
            for child in head.winfo_children():
                child.bind("<Button-1>", lambda e: self.toggle_think())

    def toggle_think(self):
        if self._think_body is None:
            return
        if self._think_body.winfo_ismapped():
            self._think_body.pack_forget()
        else:
            self._think_body.pack(fill="x")
        self._update_scroll()

    def _highlight(self, text, keyword):
        start = "1.0"
        while True:
            pos = text.search(keyword, start, "end", nocase=True)
            if not pos:
                break
            text.tag_add("hl", pos, f"{pos}+{len(keyword)}c")
            start = f"{pos}+{len(keyword)}c"
        text.tag_configure("hl", background=C_HL)

    # --- 布局与滚动 ---

    def _on_resize(self, event):
        self.canvas.itemconfigure(self._win, width=event.width)
        self.after_idle(self._refit)

    def _refit(self):
        """宽度变化后重算各卡片正文高度（换行行数会变）"""
        self._update_scroll()

    def _update_scroll(self):
        self.inner.update_idletasks()            # Text 拿到实际宽度
        self._fit_heights()                      # 按实际宽度算显示行数
        self.inner.update_idletasks()            # 新高度布局生效
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _fit_heights(self):
        for text in self._texts:
            n = text.count("1.0", "end", "displaylines")
            if isinstance(n, tuple):
                n = n[0] if n else 0
            if n:
                text.configure(height=max(n, 1))

    def _copy(self):
        if not self.qa:
            return
        sec = parse_seconds(self.qa.get("thinking_seconds"))
        parts = [
            "【用户】\n" + str(first_key(self.qa, Q_KEYS)),
        ]
        thinking = first_key(self.qa, T_KEYS)
        if thinking:
            parts.append(f"【思考过程 {sec:.1f}秒】\n" + str(thinking))
        answer = first_key(self.qa, A_KEYS)
        if answer:
            parts.append("【AI】\n" + str(answer))
        self.clipboard_clear()
        self.clipboard_append("\n\n".join(parts))
        self.app.update_status("已复制本条问答到剪贴板")


# ---------- 全文搜索窗口 ----------

class SearchWindow(tk.Toplevel):
    """跨对话全文搜索：双击结果跳转定位并高亮"""

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("全文搜索")
        self.geometry("900x540")
        self.transient(app)

        top = ttk.Frame(self, padding=10)
        top.pack(fill="x")
        ttk.Label(top, text="关键词:").pack(side="left")
        self.kw_var = tk.StringVar()
        entry = ttk.Entry(top, textvariable=self.kw_var, width=30)
        entry.pack(side="left", padx=6)
        entry.bind("<Return>", lambda e: self.search())
        ttk.Button(top, text="搜索", command=self.search).pack(side="left")
        ttk.Button(top, text="含思考过程", command=lambda: self.search(True)).pack(side="left", padx=6)
        ttk.Label(top, text="双击结果跳转定位", foreground="#999").pack(side="left", padx=10)

        cols = ("conv", "idx", "role", "snippet")
        self.result = ttk.Treeview(self, columns=cols, show="headings")
        for col, text, width in (
            ("conv", "对话", 170),
            ("idx", "#", 44),
            ("role", "角色", 56),
            ("snippet", "内容片段", 500),
        ):
            self.result.heading(col, text=text)
            self.result.column(col, width=width, anchor="w")
        ysb = ttk.Scrollbar(self, orient="vertical", command=self.result.yview)
        self.result.configure(yscrollcommand=ysb.set)
        self.result.pack(fill="both", expand=True, padx=10, pady=(0, 4))
        ysb.pack(side="right", fill="y", pady=(0, 4))
        self.result.bind("<Double-1>", self._jump)

        self.status = ttk.Label(self, anchor="w", padding=(10, 4))
        self.status.pack(fill="x")
        entry.focus_set()

    def search(self, include_thinking=False):
        kw = self.kw_var.get().strip()
        if not kw:
            return
        fields = [("用户", Q_KEYS)]
        if include_thinking:
            fields.append(("思考", T_KEYS))
        fields.append(("AI", A_KEYS))

        self.result.delete(*self.result.get_children())
        hits = 0
        for fname, meta in self.app.lib.convs.items():
            data = self.app._load_conv(fname)
            for i, qa in enumerate(data["qa_pairs"], 1):
                for role, keys in fields:
                    text = str(first_key(qa, keys))
                    pos = text.lower().find(kw.lower())
                    if pos >= 0:
                        start = max(0, pos - 30)
                        snippet = ("…" if start else "") + \
                            text[start:pos + len(kw) + 50].replace("\n", " ") + "…"
                        self.result.insert("", "end", values=(fname, i, role, snippet))
                        hits += 1
                        break  # 每条 QA 只记一次命中
            if hits >= 500:
                break
        self.status.config(
            text=f"关键词「{kw}」命中 {hits} 条" + ("（已达 500 条上限）" if hits >= 500 else ""))

    def _jump(self, event):
        sel = self.result.selection()
        if not sel:
            return
        fname, idx, _, _ = self.result.item(sel[0], "values")
        self.app.jump_to_qa(fname, int(idx), self.kw_var.get().strip())


# ---------- 统计弹窗 ----------

class StatsWindow(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        self.title("统计")
        self.geometry("860x520")
        self.transient(app)

        total_qa = total_chars = total_think = 0
        rows = []
        for fname, meta in app.lib.convs.items():
            data = app._load_conv(fname)
            pairs = data["qa_pairs"]
            chars = sum(len(str(first_key(qa, Q_KEYS))) + len(str(first_key(qa, A_KEYS)))
                        for qa in pairs)
            think = sum(parse_seconds(qa.get("thinking_seconds")) for qa in pairs)
            answer_chars = sum(len(str(first_key(qa, A_KEYS))) for qa in pairs)
            avg = answer_chars // len(pairs) if pairs else 0
            total_qa += len(pairs)
            total_chars += chars
            total_think += think
            rows.append((meta["title"], len(pairs), chars, avg, think,
                         ",".join(meta.get("tags", []))))
        rows.sort(key=lambda r: r[2], reverse=True)

        ttk.Label(
            self, font=FONT_TITLE, padding=14,
            text=f"对话 {len(rows)} 个 · 问答 {fmt_count(total_qa)} 组 · "
                 f"正文 {fmt_count(total_chars)} 字 · 思考总时长 {total_think / 60:.1f} 分钟",
        ).pack(anchor="w")

        cols = ("title", "count", "chars", "avg", "think_sec", "tags")
        tree = ttk.Treeview(self, columns=cols, show="headings")
        for col, text, width in (
            ("title", "对话", 300),
            ("count", "问答数", 70),
            ("chars", "总字数", 90),
            ("avg", "平均回答字数", 100),
            ("think_sec", "思考总时长(秒)", 100),
            ("tags", "标签", 130),
        ):
            tree.heading(col, text=text)
            tree.column(col, width=width, anchor="w")
        ysb = ttk.Scrollbar(self, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=ysb.set)
        tree.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        ysb.pack(side="right", fill="y", pady=(0, 12))
        for row in rows:
            tree.insert("", "end", values=(
                row[0], row[1], fmt_count(row[2]), fmt_count(row[3]),
                f"{row[4]:.0f}", row[5],
            ))


# ---------- 主应用 ----------

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("AI 记忆储存和管理器")
        self.geometry("1360x840")
        self.minsize(1000, 640)
        self.configure(bg=C_BG)

        self.lib = Library()
        self.lib.load()
        self.conv_cache = {}
        self.cur_conv = None
        self._loading = False
        self._checked = set()

        self._first_run_import()
        self._build_toolbar()
        self._build_main()
        self._build_statusbar()
        self.refresh_list()
        self.update_status()

    # ----- 初始化 -----

    def _first_run_import(self):
        """首次运行时自动导入程序目录下的对话 JSON"""
        if self.lib.convs or os.path.exists(LIB_FILE):
            return
        paths = [
            os.path.join(APP_DIR, f)
            for f in os.listdir(APP_DIR)
            if f.lower().endswith(".json") and f != os.path.basename(LIB_FILE)
        ]
        added, _ = self.lib.import_paths(paths)
        if added:
            messagebox.showinfo(
                "自动导入", f"检测到 {len(added)} 个对话文件，已自动导入对话库。", parent=self)

    def _build_toolbar(self):
        bar = tk.Frame(self, bg="white", bd=0, highlightbackground=C_BORDER,
                       highlightthickness=1)
        bar.pack(fill="x", padx=8, pady=(8, 4))

        import_mb = ttk.Menubutton(bar, text="导入 ▾")
        menu = tk.Menu(import_mb, tearoff=0)
        menu.add_command(label="导入文件…", command=self.import_files)
        menu.add_command(label="导入文件夹…", command=self.import_folder)
        import_mb.configure(menu=menu)
        import_mb.pack(side="left", padx=(10, 4), pady=6)

        for text, cmd in (
            ("全文搜索", self.open_search),
            ("统计", self.show_stats),
        ):
            ttk.Button(bar, text=text, command=cmd).pack(side="left", padx=4, pady=6)

        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=8, pady=8)

        for text, cmd in (
            ("合并导出 JSON", self.merge_export),
            ("导出 Markdown", self.export_markdown),
        ):
            ttk.Button(bar, text=text, command=cmd).pack(side="left", padx=4, pady=6)

    def _build_main(self):
        main = ttk.PanedWindow(self, orient="horizontal")
        main.pack(fill="both", expand=True, padx=8, pady=4)

        # 左：对话库
        left = ttk.Frame(main, padding=(0, 0, 4, 0))
        main.add(left, weight=1)

        filter_bar = ttk.Frame(left)
        filter_bar.pack(fill="x", pady=(0, 4))
        self.filter_var = tk.StringVar()
        entry = ttk.Entry(filter_bar, textvariable=self.filter_var)
        entry.pack(side="left", fill="x", expand=True, ipady=1)
        self.filter_var.trace_add("write", lambda *_: self.refresh_list())

        self.tag_var = tk.StringVar(value="全部标签")
        self.tag_box = ttk.Combobox(filter_bar, textvariable=self.tag_var, width=9,
                                    state="readonly", values=["全部标签"],
                                    postcommand=self._update_tag_box)
        self.tag_box.bind("<<ComboboxSelected>>", lambda e: self.refresh_list())
        self.tag_box.pack(side="left", padx=(4, 0))

        self.star_only = tk.BooleanVar()
        ttk.Checkbutton(filter_bar, text="★", variable=self.star_only,
                        command=self.refresh_list).pack(side="left", padx=(4, 0))

        cols = ("check", "star", "title", "count", "time")
        self.conv_tree = ttk.Treeview(left, columns=cols, show="headings",
                                      selectmode="browse")
        for col, text, width, anchor in (
            ("check", "合并", 44, "center"),
            ("star", "★", 32, "center"),
            ("title", "标题", 200, "w"),
            ("count", "问答", 52, "e"),
            ("time", "日期", 78, "center"),
        ):
            self.conv_tree.heading(col, text=text)
            self.conv_tree.column(col, width=width, anchor=anchor,
                                  stretch=(col == "title"))
        ysb = ttk.Scrollbar(left, orient="vertical", command=self.conv_tree.yview)
        self.conv_tree.configure(yscrollcommand=ysb.set)
        self.conv_tree.pack(fill="both", expand=True)
        ysb.pack(side="right", fill="y")
        self.conv_tree.bind("<<TreeviewSelect>>", self._on_conv_selected)
        self.conv_tree.bind("<Button-1>", self._on_conv_click, add="+")
        self.conv_tree.bind("<Double-1>", self._on_conv_double)
        self.conv_tree.bind("<Button-3>", self._show_conv_menu)

        # 右：主区域
        right = ttk.Frame(main)
        main.add(right, weight=4)

        pane = ttk.PanedWindow(right, orient="horizontal")
        pane.pack(fill="both", expand=True)

        # QA 导航列表
        qa_left = ttk.Frame(pane)
        pane.add(qa_left, weight=2)
        cols = ("idx", "question")
        self.qa_tree = ttk.Treeview(qa_left, columns=cols, show="headings")
        self.qa_tree.heading("idx", text="#")
        self.qa_tree.heading("question", text="用户问题")
        self.qa_tree.column("idx", width=44, anchor="center", stretch=False)
        self.qa_tree.column("question", width=260, anchor="w")
        ysb = ttk.Scrollbar(qa_left, orient="vertical", command=self.qa_tree.yview)
        self.qa_tree.configure(yscrollcommand=ysb.set)
        self.qa_tree.pack(fill="both", expand=True)
        ysb.pack(side="right", fill="y")
        self.qa_tree.bind("<<TreeviewSelect>>", self._on_qa_selected)

        # 详情卡片
        self.detail = DetailView(pane, self)
        pane.add(self.detail, weight=3)

    def _build_statusbar(self):
        self.status = ttk.Label(self, relief="sunken", anchor="w", padding=(10, 3))
        self.status.pack(fill="x", side="bottom", padx=8, pady=(0, 6))

    # ----- 对话列表 -----

    def _update_tag_box(self):
        self.tag_box["values"] = ["全部标签"] + self.lib.all_tags()

    def refresh_list(self):
        self._loading = True
        try:
            self.conv_tree.delete(*self.conv_tree.get_children())
            kw = self.filter_var.get().strip().lower()
            tag = self.tag_var.get()
            for fname, meta in sorted(
                self.lib.convs.items(),
                key=lambda kv: kv[1].get("exported_at") or kv[1].get("added_at") or "",
                reverse=True,
            ):
                if kw and kw not in meta["title"].lower():
                    continue
                if tag != "全部标签" and tag not in meta.get("tags", []):
                    continue
                if self.star_only.get() and not meta.get("starred"):
                    continue
                check = "☑" if fname in self._checked else "☐"
                star = "★" if meta.get("starred") else "☆"
                self.conv_tree.insert("", "end", iid=fname, values=(
                    check, star, meta["title"], meta["count"],
                    (meta.get("exported_at") or "")[:10],
                ))
        finally:
            self._loading = False

    def update_status(self, extra=""):
        total_qa = sum(m["count"] for m in self.lib.convs.values())
        msg = (f"对话 {len(self.lib.convs)} 个 · 问答 {fmt_count(total_qa)} 组 · "
               f"已勾选 {len(self._checked)} 个")
        if extra:
            msg += " · " + extra
        self.status.config(text=msg)

    def _on_conv_click(self, event):
        """点击『合并/★』列时切换状态"""
        item = self.conv_tree.identify_row(event.y)
        col = self.conv_tree.identify_column(event.x)
        if not item:
            return
        if col == "#1":
            if item in self._checked:
                self._checked.discard(item)
                self.conv_tree.set(item, "check", "☐")
            else:
                self._checked.add(item)
                self.conv_tree.set(item, "check", "☑")
            self.update_status()
        elif col == "#2":
            self._toggle_star(item)

    def _on_conv_double(self, event):
        item = self.conv_tree.identify_row(event.y)
        col = self.conv_tree.identify_column(event.x)
        if item and col == "#3":
            self.rename_conv(item)

    def _show_conv_menu(self, event):
        item = self.conv_tree.identify_row(event.y)
        if not item:
            return
        self.conv_tree.selection_set(item)
        if item != self.cur_conv:
            self.show_conv(item)  # 程序化选中不触发事件，手动加载
        meta = self.lib.convs[item]
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(
            label="取消星标" if meta.get("starred") else "加星标",
            command=lambda: self._toggle_star(item))
        menu.add_command(label="编辑标签", command=lambda: self.edit_tags(item))
        menu.add_command(label="重命名", command=lambda: self.rename_conv(item))
        menu.add_separator()
        menu.add_command(label="导出为 Markdown",
                         command=lambda: self.export_markdown(force=item))
        menu.add_separator()
        menu.add_command(label="删除（移入回收站）",
                         command=lambda: self.delete_conv(item))
        menu.tk_popup(event.x_root, event.y_root)

    def _toggle_star(self, fname):
        meta = self.lib.convs[fname]
        meta["starred"] = not meta.get("starred")
        self.lib.save()
        self.refresh_list()
        if fname == self.cur_conv:
            self.detail.star_btn.config(text="★" if meta["starred"] else "☆")

    def _toggle_star_current(self):
        if self.cur_conv:
            self._toggle_star(self.cur_conv)

    def rename_conv(self, fname):
        meta = self.lib.convs[fname]
        title = simpledialog.askstring("重命名", "新的显示标题：",
                                       initialvalue=meta["title"], parent=self)
        if title and title.strip():
            meta["title"] = title.strip()
            self.lib.save()
            self.refresh_list()
            if fname == self.cur_conv:
                self.detail.title_lbl.config(text=meta["title"])

    def edit_tags(self, fname):
        meta = self.lib.convs[fname]
        current = ", ".join(meta.get("tags", []))
        text = simpledialog.askstring("编辑标签", "标签（逗号分隔）：",
                                      initialvalue=current, parent=self)
        if text is None:
            return
        meta["tags"] = [t.strip() for t in text.split(",") if t.strip()]
        self.lib.save()
        self.refresh_list()

    def delete_conv(self, fname):
        meta = self.lib.convs[fname]
        if not messagebox.askyesno(
            "删除对话",
            f"确定删除「{meta['title']}」吗？\n文件将移入 trash/ 回收站，不会销毁。",
            parent=self,
        ):
            return
        self.lib.remove(fname)
        self._checked.discard(fname)
        if self.cur_conv == fname:
            self.cur_conv = None
            self.qa_tree.delete(*self.qa_tree.get_children())
            self.detail.clear()
        self.refresh_list()
        self.update_status()

    # ----- 浏览 -----

    def _load_conv(self, fname):
        if fname not in self.conv_cache:
            if len(self.conv_cache) >= 10:
                self.conv_cache.clear()
            self.conv_cache[fname] = load_json(self.lib.path(fname))
        return self.conv_cache[fname]

    def _cur_pairs(self):
        if not self.cur_conv:
            return []
        return self._load_conv(self.cur_conv).get("qa_pairs", [])

    def qa_pos(self):
        sel = self.qa_tree.selection()
        return int(sel[0]) if sel else 0

    def qa_total(self):
        return len(self._cur_pairs())

    def _on_conv_selected(self, event):
        if self._loading:
            return
        sel = self.conv_tree.selection()
        if not sel:
            return
        fname = sel[0]
        if fname != self.cur_conv:
            self.show_conv(fname)

    def show_conv(self, fname):
        data = self._load_conv(fname)
        self.cur_conv = fname
        meta = self.lib.convs[fname]
        url = data.get("source_url", "")
        meta_text = f"{len(data['qa_pairs'])} 组问答 · 导出于 {data.get('exported_at', '?')}"
        if url:
            meta_text += f" · {url[:48]}"
        self.detail.set_conv(meta["title"], meta_text, meta.get("starred", False))

        self._loading = True
        try:
            self.qa_tree.delete(*self.qa_tree.get_children())
            for i, qa in enumerate(data["qa_pairs"], 1):
                q = str(first_key(qa, Q_KEYS)).replace("\n", " ")[:56]
                self.qa_tree.insert("", "end", iid=str(i), values=(i, q))
        finally:
            self._loading = False
        self.update_status(f"当前：{meta['title']}")
        return data

    def _on_qa_selected(self, event):
        if self._loading or not self.cur_conv:
            return
        pairs = self._cur_pairs()
        idx = self.qa_pos()
        if 1 <= idx <= len(pairs):
            self.detail.show(pairs[idx - 1])

    def step_qa(self, delta):
        total = self.qa_total()
        if not total:
            return
        idx = min(max(self.qa_pos() + delta, 1), total)
        self.qa_tree.selection_set(str(idx))
        self.qa_tree.see(str(idx))
        self._on_qa_selected(None)  # 程序化选中不触发事件，手动渲染

    def jump_to_qa(self, fname, idx, keyword):
        """供搜索窗口调用：定位到某个问答并高亮关键词"""
        if fname not in self.lib.convs:
            messagebox.showwarning("定位", "该对话已不在库中。", parent=self)
            return
        if fname not in self.conv_tree.get_children():
            self.filter_var.set("")
            self.tag_var.set("全部标签")
            self.star_only.set(False)
            self.refresh_list()
        self.conv_tree.selection_set(fname)
        self.conv_tree.see(fname)
        data = self.show_conv(fname)
        if 1 <= idx <= len(data["qa_pairs"]):
            self.qa_tree.selection_set(str(idx))
            self.qa_tree.see(str(idx))
            self.detail.show(data["qa_pairs"][idx - 1], keyword=keyword)

    # ----- 导入 / 导出 -----

    def import_files(self):
        paths = filedialog.askopenfilenames(
            title="选择对话 JSON 文件",
            filetypes=[("JSON 文件", "*.json"), ("所有文件", "*.*")])
        if not paths:
            return
        self._do_import(list(paths))

    def import_folder(self):
        folder = filedialog.askdirectory(title="选择包含对话 JSON 的文件夹")
        if not folder:
            return
        paths = [os.path.join(folder, f) for f in os.listdir(folder)
                 if f.lower().endswith(".json")]
        if not paths:
            messagebox.showinfo("导入", "该文件夹下没有 JSON 文件。", parent=self)
            return
        self._do_import(paths)

    def _do_import(self, paths):
        added, skipped = self.lib.import_paths(paths)
        self.refresh_list()
        self.update_status()
        msg = f"成功导入 {len(added)} 个对话。"
        if skipped:
            msg += ("\n\n跳过 " + str(len(skipped)) + " 个文件（不是有效的对话 JSON）：\n"
                    + "\n".join(skipped))
        messagebox.showinfo("导入完成", msg, parent=self)

    def _merge_data(self, fnames):
        """合并多个对话，保持原格式并标注每条来源"""
        pairs = []
        for fname in fnames:
            data = self._load_conv(fname)
            src = data.get("conversation_title") or fname
            for qa in data["qa_pairs"]:
                item = dict(qa)
                item["source_title"] = src
                pairs.append(item)
        for i, p in enumerate(pairs, 1):
            p["index"] = i
        titles = "+".join(self.lib.convs[f]["title"] for f in fnames)
        return {
            "conversation_title": f"合并: {titles}",
            "exported_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source_url": "",
            "source_type": "merged",
            "qa_pairs": pairs,
        }

    def merge_export(self):
        if not self._checked:
            messagebox.showwarning(
                "合并导出", "请先在列表中勾选要合并的对话（点击『合并』列）。", parent=self)
            return
        fnames = [f for f in self._checked if f in self.lib.convs]
        data = self._merge_data(fnames)
        default_name = f"合并导出_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
        path = filedialog.asksaveasfilename(
            title="合并导出 JSON", defaultextension=".json", initialfile=default_name,
            filetypes=[("JSON 文件", "*.json")])
        if not path:
            return
        save_json(path, data)
        messagebox.showinfo(
            "合并导出完成",
            f"已合并 {len(fnames)} 个对话，共 {len(data['qa_pairs'])} 组问答。\n保存至：{path}",
            parent=self)

    def export_markdown(self, force=None):
        fnames = [force] if force else [f for f in self._checked if f in self.lib.convs]
        if not fnames:
            sel = self.conv_tree.selection()
            if sel:
                fnames = [sel[0]]
        if not fnames:
            messagebox.showwarning("导出 Markdown", "请先勾选或选中一个对话。", parent=self)
            return
        default_name = f"记忆导出_{datetime.now().strftime('%Y%m%d_%H%M')}.md"
        path = filedialog.asksaveasfilename(
            title="导出 Markdown", defaultextension=".md", initialfile=default_name,
            filetypes=[("Markdown 文件", "*.md"), ("所有文件", "*.*")])
        if not path:
            return
        try:
            blocks = [self._conv_to_markdown(self._load_conv(f)) for f in fnames]
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n\n".join(blocks))
        except OSError as e:
            messagebox.showerror("导出失败", str(e), parent=self)
            return
        messagebox.showinfo(
            "导出完成",
            f"已导出 {len(fnames)} 个对话到 Markdown。\n保存至：{path}", parent=self)

    @staticmethod
    def _conv_to_markdown(data):
        lines = [f"# {data.get('conversation_title', '未命名对话')}", ""]
        if data.get("exported_at"):
            lines.append(f"> 导出时间: {data['exported_at']}  ")
        if data.get("source_url"):
            lines.append(f"> 来源: {data['source_url']}")
        lines.append(f"\n共 {len(data.get('qa_pairs', []))} 组问答\n")
        for qa in data.get("qa_pairs", []):
            src = f"（来自: {qa['source_title']}）" if qa.get("source_title") else ""
            lines.append("---\n")
            lines.append(f"## [{qa.get('index', '?')}] 用户 {src}\n")
            lines.append(str(first_key(qa, Q_KEYS)) + "\n")
            thinking = first_key(qa, T_KEYS)
            if thinking:
                sec = parse_seconds(qa.get("thinking_seconds"))
                lines.append(
                    f"<details>\n<summary>思考过程（{sec:.1f} 秒）</summary>\n\n"
                    f"{thinking}\n\n</details>\n")
            answer = first_key(qa, A_KEYS)
            if answer:
                lines.append(f"## AI\n\n{answer}\n")
        return "\n".join(lines)

    # ----- 弹窗 -----

    def open_search(self):
        SearchWindow(self)

    def show_stats(self):
        StatsWindow(self)


if __name__ == "__main__":
    App().mainloop()
