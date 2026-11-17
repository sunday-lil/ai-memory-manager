#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 记忆储存和管理器 · 图形界面

纯标准库 tkinter。所有数据逻辑在 memory_core.py，本文件只负责交互与呈现。
"""

from __future__ import annotations

import ctypes
import os
import re
import subprocess
import sys
import tkinter as tk
import webbrowser
from datetime import datetime
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Any, Dict, List, Optional, Sequence, Tuple

import memory_core as core

APP_TITLE = "AI 记忆储存和管理器"

LIGHT = {
    "bg": "#f5f6f8",
    "card_bg": "#ffffff",
    "border": "#dfe3e8",
    "text": "#1f2328",
    "muted": "#6b7280",
    "user": "#1a5fb4",
    "user_head": "#eaf2fb",
    "think": "#6b7280",
    "think_head": "#f0f1f3",
    "think_bg": "#fafbfc",
    "ai": "#1f9d63",
    "ai_head": "#e9f7f0",
    "hl": "#ffe98a",
    "hl_fg": "#1f2328",
    "toolbar_bg": "#ffffff",
    "status_bg": "#f0f2f5",
    "select_bg": "#dbe9fb",
    "select_fg": "#1f2328",
    "tree_bg": "#ffffff",
    "entry_bg": "#ffffff",
    "button_bg": "#ffffff",
    "danger": "#b42318",
}

DARK = {
    "bg": "#14171c",
    "card_bg": "#1c2027",
    "border": "#30363f",
    "text": "#e6e9ef",
    "muted": "#9aa4b2",
    "user": "#7aa7e8",
    "user_head": "#1b2a3d",
    "think": "#9aa4b2",
    "think_head": "#23272f",
    "think_bg": "#191d24",
    "ai": "#5cc99a",
    "ai_head": "#17342a",
    "hl": "#6b5b1f",
    "hl_fg": "#f5e6a8",
    "toolbar_bg": "#1c2027",
    "status_bg": "#1c2027",
    "select_bg": "#2b3b52",
    "select_fg": "#e6e9ef",
    "tree_bg": "#1c2027",
    "entry_bg": "#23272f",
    "button_bg": "#23272f",
    "danger": "#ff8a7a",
}

FONT_FAMILY = "Microsoft YaHei UI"


def make_fonts(scale: float = 1.0) -> Dict[str, Tuple]:
    def size(n: int) -> int:
        return max(7, int(round(n * scale)))
    return {
        "body": (FONT_FAMILY, size(10)),
        "think": (FONT_FAMILY, size(9)),
        "head": (FONT_FAMILY, size(9), "bold"),
        "title": (FONT_FAMILY, size(13), "bold"),
        "small": (FONT_FAMILY, size(8)),
        "mono": ("Consolas", size(9)),
    }


def open_folder(path: str) -> None:
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except OSError:
        pass


def bring_to_front(window: tk.Toplevel) -> None:
    window.deiconify()
    window.lift()
    try:
        window.focus_force()
    except tk.TclError:
        pass


# ---------------------------------------------------------------------------
# 详情区：用户 / 思考 / AI 三张独立卡片
# ---------------------------------------------------------------------------

class DetailView(ttk.Frame):
    def __init__(self, master: tk.Misc, app: "App"):
        super().__init__(master)
        self.app = app
        self.palette = app.palette
        self.fonts = app.fonts
        self.qa: Optional[Dict[str, Any]] = None
        self.keyword: Optional[str] = None
        self._texts: List[tk.Text] = []
        self._think_body: Optional[tk.Frame] = None
        self._think_head: Optional[tk.Frame] = None
        self._think_arrow: Optional[tk.Label] = None
        self._wheel_on = False

        head = ttk.Frame(self, padding=(12, 8, 12, 2))
        head.pack(fill="x")
        head.columnconfigure(0, weight=1)
        title_row = ttk.Frame(head)
        title_row.grid(row=0, column=0, sticky="ew")
        self.title_lbl = ttk.Label(title_row, text="选择左侧对话开始浏览",
                                   font=self.fonts["title"], style="Title.TLabel")
        self.title_lbl.pack(side="left")
        self.star_btn = ttk.Button(title_row, text="☆", width=3,
                                   command=app._toggle_star_current)
        self.star_btn.pack(side="left", padx=6)
        self.source_btn = ttk.Button(title_row, text="打开来源", width=9,
                                     command=self._open_source)
        self.source_url = ""
        self.meta_lbl = ttk.Label(head, text="", style="Muted.TLabel", anchor="w")
        self.meta_lbl.grid(row=1, column=0, sticky="ew", pady=(2, 0))

        nav = ttk.Frame(self, padding=(12, 0, 12, 2))
        nav.pack(fill="x")
        self.pos_lbl = ttk.Label(nav, text="未选择", width=16, anchor="w")
        self.pos_lbl.pack(side="left")
        ttk.Button(nav, text="◀ 上一条", width=9,
                   command=lambda: app.step_qa(-1)).pack(side="left", padx=2)
        ttk.Button(nav, text="下一条 ▶", width=9,
                   command=lambda: app.step_qa(1)).pack(side="left")
        ttk.Label(nav, text="点击思考标题条可折叠", style="Muted.TLabel").pack(
            side="left", padx=10)
        ttk.Button(nav, text="复制本条", command=self._copy).pack(side="right")

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(body, bg=self.palette["bg"], highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        ysb = ttk.Scrollbar(body, orient="vertical", command=self.canvas.yview)
        ysb.grid(row=0, column=1, sticky="ns")
        self.canvas.configure(yscrollcommand=ysb.set)

        self.inner = tk.Frame(self.canvas, bg=self.palette["bg"])
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.bind("<Configure>", self._on_resize)
        self.bind("<Enter>", lambda e: self._set_wheel(True))
        self.bind("<Leave>", lambda e: self._set_wheel(False))
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self._resize_after: Optional[str] = None

    # --- 标题 ---

    def set_conv(self, title: str, meta_text: str, starred: bool,
                 source_url: str = "") -> None:
        self.title_lbl.config(text=title)
        self.meta_lbl.config(text=meta_text)
        self.star_btn.config(text="★" if starred else "☆")
        self.source_url = source_url or ""
        if self.source_url:
            if not self.source_btn.winfo_ismapped():
                self.source_btn.pack(side="right", padx=(6, 0))
        else:
            self.source_btn.pack_forget()

    def _open_source(self) -> None:
        if self.source_url:
            webbrowser.open(self.source_url)

    def clear(self) -> None:
        self.set_conv("选择左侧对话开始浏览", "", False)
        self.show(None)

    # --- 滚轮 ---

    def _set_wheel(self, on: bool) -> None:
        if on == self._wheel_on:
            return
        if on:
            self.bind_all("<MouseWheel>", self._on_wheel, add="+")
        else:
            self.unbind_all("<MouseWheel>")
        self._wheel_on = on

    def _on_wheel(self, event) -> str:
        units = max(abs(int(event.delta)) // 120, 1)
        self.canvas.yview_scroll(-units if event.delta > 0 else units, "units")
        return "break"

    # --- 渲染 ---

    def show(self, qa: Optional[Dict[str, Any]], keyword: Optional[str] = None) -> None:
        self.qa = qa
        self.keyword = keyword
        for widget in self.inner.winfo_children():
            widget.destroy()
        self._texts = []
        self._think_body = self._think_head = self._think_arrow = None
        if not qa:
            self.pos_lbl.config(text="未选择")
            tk.Label(
                self.inner,
                text="在左侧选择一条对话，再选择一条问答",
                bg=self.palette["bg"], fg=self.palette["muted"],
                font=self.fonts["body"],
            ).pack(pady=70)
            self._update_scroll()
            return

        question = core.qa_field(qa, "user")
        thinking = core.qa_field(qa, "thinking")
        answer = core.qa_field(qa, "ai")

        self._add_card("用户", question, self.palette["user"],
                       self.palette["user_head"], self.palette["card_bg"],
                       font=self.fonts["body"])
        if thinking:
            seconds = core.parse_seconds(qa.get("thinking_seconds"))
            self._add_card(f"思考过程  ·  {seconds:.1f} 秒", thinking,
                           self.palette["think"], self.palette["think_head"],
                           self.palette["think_bg"], font=self.fonts["think"],
                           fg=self.palette["think"], collapsible=True)
        self._add_card("AI", answer, self.palette["ai"],
                       self.palette["ai_head"], self.palette["card_bg"],
                       font=self.fonts["body"])
        tk.Frame(self.inner, bg=self.palette["bg"], height=16).pack(fill="x")

        self.pos_lbl.config(text=f"第 {self.app.qa_pos()} / {self.app.qa_total()} 条")
        self._update_scroll()
        self.canvas.yview_moveto(0)

    def _add_card(self, title: str, body: str, accent: str, head_bg: str,
                  body_bg: str, font: Tuple, fg: str = "",
                  collapsible: bool = False) -> None:
        fg = fg or self.palette["text"]
        card = tk.Frame(self.inner, bg=body_bg,
                        highlightbackground=self.palette["border"],
                        highlightthickness=1)
        card.pack(fill="x", padx=12, pady=(10, 0), ipadx=1, ipady=1)

        head = tk.Frame(card, bg=head_bg, cursor="hand2" if collapsible else "")
        head.pack(fill="x")
        tk.Frame(head, bg=accent, width=4).pack(side="left", fill="y")
        tk.Label(head, text=title, bg=head_bg, fg=accent, font=self.fonts["head"],
                 anchor="w", padx=8, pady=5).pack(side="left")
        tk.Label(head, text=f"{len(body):,} 字", bg=head_bg,
                 fg=self.palette["muted"], font=self.fonts["small"],
                 padx=8).pack(side="right")
        if collapsible:
            self._think_arrow = tk.Label(head, text="▾", bg=head_bg,
                                         fg=self.palette["muted"],
                                         font=self.fonts["head"], padx=6)
            self._think_arrow.pack(side="right")

        body_frame = tk.Frame(card, bg=body_bg)
        body_frame.pack(fill="x")
        text = tk.Text(
            body_frame, wrap="word", bd=0, padx=14, pady=9,
            bg=body_bg, fg=fg, font=font, width=10, height=2,
            highlightthickness=0, cursor="arrow", spacing1=2, spacing3=2,
            selectbackground=self.palette["select_bg"],
            selectforeground=self.palette["select_fg"],
            takefocus=0,
        )
        text.pack(fill="x")
        text.insert("1.0", body.rstrip())
        if self.keyword:
            self._highlight(text, self.keyword)
        text.configure(state="disabled")
        self._texts.append(text)
        text.bind("<MouseWheel>", self._on_wheel)

        if collapsible:
            self._think_body, self._think_head = body_frame, head
            for child in head.winfo_children():
                child.bind("<Button-1>", lambda e: self.toggle_think())

    def toggle_think(self) -> None:
        if self._think_body is None:
            return
        fraction = self.canvas.yview()[0]
        if self._think_body.winfo_ismapped():
            self._think_body.pack_forget()
            if self._think_arrow is not None:
                self._think_arrow.config(text="▸")
        else:
            self._think_body.pack(fill="x")
            if self._think_arrow is not None:
                self._think_arrow.config(text="▾")
        self._update_scroll()
        try:
            self.canvas.yview_moveto(fraction)
        except tk.TclError:
            pass

    def _highlight(self, text: tk.Text, keyword: str) -> None:
        if not keyword:
            return
        text.tag_configure("hl", background=self.palette["hl"],
                           foreground=self.palette["hl_fg"])
        start = "1.0"
        limit = 5000
        for _ in range(limit):
            pos = text.search(keyword, start, "end", nocase=True)
            if not pos:
                break
            end = f"{pos}+{len(keyword)}c"
            text.tag_add("hl", pos, end)
            start = end

    # --- 布局 ---

    def _on_resize(self, event) -> None:
        self.canvas.itemconfigure(self._win, width=event.width)
        if self._resize_after is not None:
            try:
                self.after_cancel(self._resize_after)
            except tk.TclError:
                pass
        self._resize_after = self.after_idle(self._after_resize)

    def _after_resize(self) -> None:
        self._resize_after = None
        self._update_scroll()

    def _update_scroll(self) -> None:
        if not self.winfo_exists():
            return
        self.inner.update_idletasks()
        self._fit_heights()
        self.inner.update_idletasks()
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _fit_heights(self) -> None:
        for text in self._texts:
            if text.winfo_width() <= 20:
                continue
            count = text.count("1.0", "end", "displaylines")
            if isinstance(count, tuple):
                count = count[0] if count else 0
            if count:
                text.configure(height=max(int(count), 1))

    def _copy(self) -> None:
        if not self.qa:
            return
        seconds = core.parse_seconds(self.qa.get("thinking_seconds"))
        parts = ["【用户】\n" + core.qa_field(self.qa, "user")]
        thinking = core.qa_field(self.qa, "thinking")
        if thinking:
            parts.append(f"【思考过程 {seconds:.1f}秒】\n{thinking}")
        answer = core.qa_field(self.qa, "ai")
        if answer:
            parts.append("【AI】\n" + answer)
        self.clipboard_clear()
        self.clipboard_append("\n\n".join(parts))
        self.app.update_status("已复制本条问答到剪贴板")

    def destroy(self) -> None:
        if self._resize_after is not None:
            try:
                self.after_cancel(self._resize_after)
            except tk.TclError:
                pass
            self._resize_after = None
        if self._wheel_on:
            try:
                self.unbind_all("<MouseWheel>")
            except tk.TclError:
                pass
            self._wheel_on = False
        super().destroy()

    # --- 主题 / 字号 ---

    def apply_look(self) -> None:
        self.palette = self.app.palette
        self.fonts = self.app.fonts
        self.canvas.configure(bg=self.palette["bg"])
        self.inner.configure(bg=self.palette["bg"])
        self.title_lbl.configure(font=self.fonts["title"])
        if self.qa:
            self.show(self.qa, self.keyword)
        else:
            self.show(None)


# ---------------------------------------------------------------------------
# 全文搜索
# ---------------------------------------------------------------------------

class SearchWindow(tk.Toplevel):
    def __init__(self, app: "App"):
        super().__init__(app)
        self.app = app
        self.palette = app.palette
        self.fonts = app.fonts
        self.title("全文搜索")
        self.geometry("1040x620")
        self.minsize(760, 420)
        self.transient(app)
        self.hits: List[core.SearchHit] = []
        self.last_result: Optional[core.SearchResult] = None
        self._after_id: Optional[str] = None
        self._scope_fnames: List[Optional[str]] = [None]

        outer = ttk.Frame(self, padding=12)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(3, weight=1)

        row1 = ttk.Frame(outer)
        row1.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ttk.Label(row1, text="关键词").pack(side="left")
        self.kw_var = tk.StringVar(value=str(app.settings.get("last_search", "")))
        self.entry = ttk.Entry(row1, textvariable=self.kw_var, width=34)
        self.entry.pack(side="left", padx=6, ipady=1)
        self.entry.bind("<Return>", lambda e: self.search())
        ttk.Button(row1, text="搜索", command=self.search).pack(side="left")
        ttk.Label(row1, text="范围").pack(side="left", padx=(16, 4))
        self.scope_var = tk.StringVar(value="全部对话")
        self.scope_box = ttk.Combobox(row1, textvariable=self.scope_var,
                                      width=26, state="readonly")
        self.scope_box.pack(side="left")
        self.scope_box.bind("<<ComboboxSelected>>", lambda e: self.search())
        self.live_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(row1, text="边输边搜", variable=self.live_var).pack(
            side="left", padx=(14, 0))

        row2 = ttk.Frame(outer)
        row2.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        ttk.Label(row2, text="角色").pack(side="left")
        self.role_vars: Dict[str, tk.BooleanVar] = {}
        for role, label in (("user", "用户"), ("thinking", "思考"), ("ai", "AI")):
            var = tk.BooleanVar(value=role != "thinking")
            self.role_vars[role] = var
            ttk.Checkbutton(row2, text=label, variable=var).pack(side="left", padx=(6, 0))
        self.case_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(row2, text="区分大小写", variable=self.case_var).pack(
            side="left", padx=(18, 0))
        self.regex_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(row2, text="正则表达式", variable=self.regex_var).pack(
            side="left", padx=(8, 0))
        ttk.Label(row2, text="双击结果跳转并高亮", style="Muted.TLabel").pack(
            side="right")

        self.status = ttk.Label(outer, text="输入关键词后回车，或直接边输边搜",
                                style="Muted.TLabel")
        self.status.grid(row=2, column=0, sticky="ew", pady=(0, 4))

        table = ttk.Frame(outer)
        table.grid(row=3, column=0, sticky="nsew")
        table.columnconfigure(0, weight=1)
        table.rowconfigure(0, weight=1)
        cols = ("conv", "idx", "role", "count", "snippet")
        self.result = ttk.Treeview(table, columns=cols, show="headings",
                                   selectmode="browse")
        for col, text, width, stretch in (
            ("conv", "对话", 190, False),
            ("idx", "#", 52, False),
            ("role", "角色", 66, False),
            ("count", "命中", 52, False),
            ("snippet", "内容片段", 600, True),
        ):
            self.result.heading(col, text=text)
            self.result.column(col, width=width, stretch=stretch,
                               anchor="center" if col in ("idx", "role", "count") else "w")
        ysb = ttk.Scrollbar(table, orient="vertical", command=self.result.yview)
        self.result.configure(yscrollcommand=ysb.set)
        self.result.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")
        self.result.bind("<Double-1>", self._jump)
        self.result.bind("<Return>", self._jump)
        for role, color_key in (("user", "user"), ("thinking", "think"), ("ai", "ai")):
            self.result.tag_configure(role, foreground=self.palette[color_key])

        bottom = ttk.Frame(outer)
        bottom.grid(row=4, column=0, sticky="ew", pady=(6, 0))
        ttk.Button(bottom, text="导出结果 Markdown",
                   command=self.export_results).pack(side="right")
        ttk.Button(bottom, text="关闭", command=self.destroy).pack(side="right", padx=6)

        self._refresh_scope()
        self.kw_var.trace_add("write", self._on_typing)
        self.bind("<Escape>", lambda e: self.destroy())
        self.entry.focus_set()
        if self.kw_var.get().strip():
            self._after_id = self.after(120, self.search)

    def destroy(self) -> None:
        if self._after_id is not None:
            try:
                self.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None
        if getattr(self.app, "_search_win", None) is self:
            self.app._search_win = None
        super().destroy()

    def _refresh_scope(self) -> None:
        names = ["全部对话"]
        self._scope_fnames = [None]
        for fname in self.app.lib.sorted_fnames():
            meta = self.app.lib.convs[fname]
            names.append(f"{meta.get('title', fname)}（{meta.get('count', 0)}）")
            self._scope_fnames.append(fname)
        self.scope_box["values"] = names
        if self.scope_var.get() not in names:
            self.scope_var.set("全部对话")

    def apply_look(self) -> None:
        self.palette = self.app.palette
        for role, color_key in (("user", "user"), ("thinking", "think"), ("ai", "ai")):
            self.result.tag_configure(role, foreground=self.palette[color_key])

    def _on_typing(self, *_args) -> None:
        if not self.live_var.get():
            if self._after_id is not None:
                try:
                    self.after_cancel(self._after_id)
                except tk.TclError:
                    pass
                self._after_id = None
            return
        if self._after_id is not None:
            try:
                self.after_cancel(self._after_id)
            except tk.TclError:
                pass
        self._after_id = self.after(320, self.search)

    def _selected_roles(self) -> List[str]:
        return [role for role in core.ROLE_ORDER
                if self.role_vars[role].get()]

    def search(self) -> None:
        if self._after_id is not None:
            try:
                self.after_cancel(self._after_id)
            except tk.TclError:
                pass
        self._after_id = None
        keyword = self.kw_var.get().strip()
        if not keyword:
            self.result.delete(*self.result.get_children())
            self.hits = []
            self.status.config(text="输入关键词后回车，或直接边输边搜")
            return
        roles = self._selected_roles()
        if not roles:
            self.status.config(text="至少选择一种角色（用户 / 思考 / AI）")
            return
        try:
            index = self.scope_box.current()
        except tk.TclError:
            index = 0
        fname = self._scope_fnames[index] if 0 <= index < len(self._scope_fnames) else None
        try:
            result = core.search_library(
                self.app.lib, keyword, roles=roles,
                case_sensitive=self.case_var.get(),
                use_regex=self.regex_var.get(),
                fname=fname, max_rows=1000,
                data_loader=self.app._load_conv,
            )
        except (ValueError, OSError) as exc:
            self.status.config(text=str(exc))
            return

        self.app.settings.set("last_search", keyword)
        self.last_result = result
        self.hits = result.rows
        self.result.delete(*self.result.get_children())
        for i, hit in enumerate(result.rows):
            self.result.insert("", "end", iid=str(i), tags=(hit.role,), values=(
                hit.title, hit.index, hit.role_label, hit.count, hit.snippet))
        if result.rows:
            self.result.selection_set("0")
            self.result.focus("0")
        extra = "（已截断，缩小关键词试试）" if result.truncated else ""
        self.status.config(
            text=(f"命中 {len(result.rows)} 条问答/角色，共 {result.total_matches} 处匹配 · "
                  f"{result.elapsed * 1000:.0f} ms{extra}"))
        self.app.update_status(f"搜索「{keyword}」：{len(result.rows)} 条结果")

    def _jump(self, event=None) -> None:
        selection = self.result.selection()
        if not selection:
            return
        try:
            hit = self.hits[int(selection[0])]
        except (ValueError, IndexError):
            return
        keyword = hit.match_text if self.regex_var.get() else self.kw_var.get().strip()
        self.app.jump_to_qa(hit.fname, hit.index, keyword)
        self.app.update_status(
            f"已定位到「{hit.title}」第 {hit.index} 条（{hit.role_label}）")

    def export_results(self) -> None:
        if not self.hits or self.last_result is None:
            messagebox.showinfo("导出结果", "当前没有搜索结果。", parent=self)
            return
        default = f"搜索结果_{datetime.now().strftime('%Y%m%d_%H%M')}.md"
        path = filedialog.asksaveasfilename(
            parent=self, title="导出搜索结果", defaultextension=".md",
            initialfile=default,
            initialdir=self.app.settings.get("last_export_dir") or self.app.root_dir,
            filetypes=[("Markdown 文件", "*.md"), ("所有文件", "*.*")],
        )
        if not path:
            return
        result = self.last_result
        lines = [
            f"# 搜索结果：{result.keyword}", "",
            f"> 命中 {len(result.rows)} 条问答/角色，共 {result.total_matches} 处匹配",
            f"> 搜索范围：{self.scope_var.get()}", "",
        ]
        for hit in result.rows:
            lines.append(f"## {hit.title} · 第 {hit.index} 条 · {hit.role_label}"
                         f"（{hit.count} 处）")
            lines.append("")
            lines.append(hit.snippet)
            lines.append("")
        try:
            core.atomic_write_text(path, "\n".join(lines))
        except OSError as exc:
            messagebox.showerror("导出失败", str(exc), parent=self)
            return
        self.app.settings.set("last_export_dir", os.path.dirname(path))
        messagebox.showinfo("导出完成", f"已保存到：\n{path}", parent=self)


# ---------------------------------------------------------------------------
# 回收站
# ---------------------------------------------------------------------------

class TrashWindow(tk.Toplevel):
    def __init__(self, app: "App"):
        super().__init__(app)
        self.app = app
        self.title("回收站")
        self.geometry("880x500")
        self.minsize(640, 340)
        self.transient(app)

        outer = ttk.Frame(self, padding=12)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(1, weight=1)

        self.summary = ttk.Label(outer, text="", style="Muted.TLabel")
        self.summary.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))

        table = ttk.Frame(outer)
        table.grid(row=1, column=0, columnspan=2, sticky="nsew")
        table.columnconfigure(0, weight=1)
        table.rowconfigure(0, weight=1)
        cols = ("title", "original", "count", "size", "deleted")
        self.tree = ttk.Treeview(table, columns=cols, show="headings",
                                 selectmode="browse")
        for col, text, width, stretch in (
            ("title", "标题", 220, True),
            ("original", "原文件", 250, True),
            ("count", "问答", 60, False),
            ("size", "大小", 80, False),
            ("deleted", "删除时间", 130, False),
        ):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=width, stretch=stretch,
                             anchor="w" if col in ("title", "original") else "center")
        ysb = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=ysb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")

        buttons = ttk.Frame(outer)
        buttons.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Button(buttons, text="还原", command=self.restore).pack(side="left")
        ttk.Button(buttons, text="彻底删除", command=self.purge).pack(
            side="left", padx=6)
        ttk.Button(buttons, text="清空回收站", command=self.empty).pack(side="left")
        ttk.Button(buttons, text="打开 trash 文件夹",
                   command=lambda: open_folder(self.app.lib.trash_dir)).pack(
            side="left", padx=(16, 0))
        ttk.Button(buttons, text="关闭", command=self.destroy).pack(side="right")

        self.refresh()

    def refresh(self) -> None:
        self.tree.delete(*self.tree.get_children())
        items = self.app.lib.trash_items()
        for item in items:
            self.tree.insert("", "end", iid=item["trash_name"], values=(
                item["title"], item["original_name"], item["count"],
                core.format_size(item["size"]), item["deleted_at"]))
        total_size = sum(i["size"] for i in items)
        self.summary.config(
            text=f"回收站中有 {len(items)} 个对话 · 共 {core.format_size(total_size)} · "
                 f"还原后会恢复星标与标签")

    def _selected(self) -> Optional[str]:
        selection = self.tree.selection()
        return selection[0] if selection else None

    def restore(self) -> None:
        trash_name = self._selected()
        if not trash_name:
            messagebox.showinfo("还原", "请先选择一个对话。", parent=self)
            return
        try:
            fname = self.app.lib.restore(trash_name)
        except (OSError, KeyError) as exc:
            messagebox.showerror("还原失败", str(exc), parent=self)
            self.refresh()
            return
        self.app.conv_cache.clear()
        self.app.refresh_list()
        self.app.show_conv(fname)
        self.refresh()
        self.app.update_status(f"已从回收站还原：{self.app.lib.convs[fname]['title']}")

    def purge(self) -> None:
        trash_name = self._selected()
        if not trash_name:
            messagebox.showinfo("彻底删除", "请先选择一个对话。", parent=self)
            return
        title = next((i["title"] for i in self.app.lib.trash_items()
                      if i["trash_name"] == trash_name), trash_name)
        if not messagebox.askyesno(
                "彻底删除", f"彻底删除「{title}」？\n此操作不可恢复。",
                parent=self, icon="warning"):
            return
        try:
            self.app.lib.purge(trash_name)
        except OSError as exc:
            messagebox.showerror("删除失败", str(exc), parent=self)
            return
        self.refresh()

    def empty(self) -> None:
        count = len(self.app.lib.trash_items())
        if not count:
            self.refresh()
            return
        if not messagebox.askyesno(
                "清空回收站", f"彻底删除回收站中的 {count} 个对话？\n此操作不可恢复。",
                parent=self, icon="warning"):
            return
        removed = self.app.lib.empty_trash()
        self.refresh()
        self.app.update_status(f"已清空回收站（{removed} 项）")


# ---------------------------------------------------------------------------
# 统计
# ---------------------------------------------------------------------------

class StatsWindow(tk.Toplevel):
    def __init__(self, app: "App"):
        super().__init__(app)
        self.app = app
        self.title("统计")
        self.geometry("980x580")
        self.minsize(760, 420)
        self.transient(app)

        outer = ttk.Frame(self, padding=12)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(1, weight=1)

        stats = core.library_stats(app.lib, data_loader=app._load_conv)
        totals = stats["totals"]
        minutes = totals["thinking_seconds"] / 60
        summary_text = (
            f"对话 {totals['conversations']} 个 · 问答 {core.fmt_count(totals['qa'])} 组 · "
            f"正文 {core.fmt_count(totals['question_chars'] + totals['answer_chars'])} 字 · "
            f"思考 {minutes:.1f} 分钟"
        )
        if totals.get("missing"):
            summary_text += f" · 缺失 {totals['missing']} 个（元数据已保留）"
        self.summary = ttk.Label(
            outer, font=app.fonts["title"], text=summary_text,
        )
        self.summary.grid(row=0, column=0, sticky="w", pady=(0, 8))

        table = ttk.Frame(outer)
        table.grid(row=1, column=0, sticky="nsew")
        table.columnconfigure(0, weight=1)
        table.rowconfigure(0, weight=1)
        cols = ("title", "count", "qchars", "achars", "avg", "think", "tags")
        self.tree = ttk.Treeview(table, columns=cols, show="headings")
        for col, text, width, stretch, anchor in (
            ("title", "对话", 240, True, "w"),
            ("count", "问答数", 70, False, "e"),
            ("qchars", "提问字数", 90, False, "e"),
            ("achars", "回答字数", 100, False, "e"),
            ("avg", "平均回答", 90, False, "e"),
            ("think", "思考(分钟)", 90, False, "e"),
            ("tags", "标签", 150, True, "w"),
        ):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=width, stretch=stretch, anchor=anchor)
        ysb = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=ysb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")

        rows = sorted(stats["rows"], key=lambda r: r["answer_chars"], reverse=True)
        for row in rows:
            self.tree.insert("", "end", values=(
                row["title"], core.fmt_count(row["count"]),
                core.fmt_count(row["question_chars"]),
                core.fmt_count(row["answer_chars"]),
                core.fmt_count(row["avg_answer_chars"]),
                f"{row['thinking_seconds'] / 60:.1f}",
                "、".join(row["tags"]) if row["tags"] else "",
            ))

        bottom = ttk.Frame(outer)
        bottom.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        ttk.Label(bottom, text="按回答字数从多到少排序", style="Muted.TLabel").pack(
            side="left")
        ttk.Button(bottom, text="关闭", command=self.destroy).pack(side="right")
        ttk.Button(bottom, text="打开数据目录",
                   command=lambda: open_folder(self.app.root_dir)).pack(
            side="right", padx=6)


# ---------------------------------------------------------------------------
# 主应用
# ---------------------------------------------------------------------------

class App(tk.Tk):
    def __init__(self, root_dir: Optional[str] = None):
        super().__init__()
        self.root_dir = os.path.abspath(root_dir or core.APP_DIR)
        self._library_existed = os.path.exists(os.path.join(self.root_dir, core.LIB_FILENAME))

        self.lib = core.Library(self.root_dir).load()
        self.settings = core.Settings(self.root_dir)
        self.settings.load()

        theme = str(self.settings.get("theme", "light"))
        if theme not in ("light", "dark"):
            theme = "light"
        self.theme = theme
        self.palette = DARK if theme == "dark" else LIGHT
        try:
            self.font_scale = min(1.6, max(0.8, float(self.settings.get("font_scale", 1.0))))
        except (TypeError, ValueError):
            self.font_scale = 1.0
        self.fonts = make_fonts(self.font_scale)

        self.title(APP_TITLE)
        self.geometry("1360x840")
        self.minsize(1000, 640)
        self.configure(bg=self.palette["bg"])

        self.conv_cache: Dict[str, Dict[str, Any]] = {}
        self.cur_conv: Optional[str] = None
        self.cur_index = 0
        self._loading = False
        self._checked: set = set(self.settings.get("checked", []) or [])
        positions = self.settings.get("positions", {})
        self._positions: Dict[str, int] = {}
        if isinstance(positions, dict):
            for key, value in positions.items():
                try:
                    self._positions[str(key)] = int(value)
                except (TypeError, ValueError):
                    continue
        self._qa_indices: List[int] = []
        self._qa_data: List[Dict[str, Any]] = []
        self._sort_key = str(self.settings.get("sort_key", "date"))
        self._sort_rev = bool(self.settings.get("sort_rev", True))
        self._search_win: Optional[SearchWindow] = None
        self._stats_win: Optional[StatsWindow] = None
        self._trash_win: Optional[TrashWindow] = None
        self._menus: List[tk.Menu] = []
        self._filter_after: Optional[str] = None
        self._qa_filter_after: Optional[str] = None

        self._setup_style()
        self._build_menu()
        self._build_toolbar()
        self._build_statusbar()
        self._build_main()
        self._bind_shortcuts()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self.refresh_list()
        self._maybe_first_run()
        self._restore_view()

        self._restore_after = self.after(80, self._restore_sashes)
        self._notice_after: Optional[str] = None
        if self.lib.recovered_from_backup:
            self._notice_after = self.after(250, lambda: messagebox.showwarning(
                "数据已恢复",
                "library.json 损坏，已自动从 library.json.bak 恢复。\n"
                "损坏副本保留在数据目录中（*.corrupt-*）。", parent=self))
        elif self.lib.load_error:
            self._notice_after = self.after(250, lambda: messagebox.showwarning(
                "元数据重建",
                "library.json 无法读取，已根据 conversations/ 中的文件重建索引。\n\n"
                + self.lib.load_error, parent=self))
        elif self.lib.missing:
            self._notice_after = self.after(300, self._warn_missing)

    def _warn_missing(self) -> None:
        items = self.lib.missing_items()
        if not items:
            return
        preview = "\n".join("· " + item["title"] for item in items[:10])
        if len(items) > 10:
            preview += f"\n……另有 {len(items) - 10} 个"
        messagebox.showwarning(
            "对话文件缺失",
            f"有 {len(items)} 个对话的 JSON 文件不在 conversations/ 中。\n"
            "标题、标签、星标等元数据已经保留。把原文件放回 conversations/ 后\n"
            "按 F5 即可自动接回，不会重新生成一份没有标签的条目。\n\n"
            + preview,
            parent=self)

    # ----- 样式 -----

    def _setup_style(self) -> None:
        self.style = ttk.Style(self)
        try:
            self.style.theme_use("clam" if self.theme == "dark" else "vista")
        except tk.TclError:
            try:
                self.style.theme_use("clam")
            except tk.TclError:
                pass
        self._apply_style()

    def _apply_style(self) -> None:
        p = self.palette
        f = self.fonts
        try:
            self.style.configure(
                ".", background=p["bg"], foreground=p["text"],
                fieldbackground=p["entry_bg"], font=f["body"],
            )
            self.style.configure("TFrame", background=p["bg"])
            self.style.configure("TLabel", background=p["bg"], foreground=p["text"])
            self.style.configure("Muted.TLabel", background=p["bg"], foreground=p["muted"])
            self.style.configure("Title.TLabel", background=p["bg"],
                                 foreground=p["text"], font=f["title"])
            self.style.configure("Status.TLabel", background=p["status_bg"],
                                 foreground=p["muted"], padding=(10, 4))
            self.style.configure("TButton", padding=(8, 3))
            self.style.configure("TMenubutton", padding=(8, 3))

            self.style.configure("TEntry", fieldbackground=p["entry_bg"],
                                 foreground=p["text"], padding=(4, 2))
            self.style.configure("TCombobox", fieldbackground=p["entry_bg"],
                                 foreground=p["text"], padding=(3, 2))
            self.style.map("TCombobox",
                           fieldbackground=[("readonly", p["entry_bg"])],
                           foreground=[("readonly", p["text"])])
            self.style.configure("TCheckbutton", background=p["bg"],
                                 foreground=p["text"])
            self.style.map("TCheckbutton",
                           background=[("active", p["bg"])])
            self.style.configure("Treeview", background=p["tree_bg"],
                                 fieldbackground=p["tree_bg"], foreground=p["text"],
                                 borderwidth=0, rowheight=int(24 * self.font_scale))
            self.style.configure("Treeview.Heading", background=p["toolbar_bg"],
                                 foreground=p["muted"], relief="flat",
                                 font=f["small"], padding=(4, 3))
            self.style.map("Treeview",
                           background=[("selected", p["select_bg"])],
                           foreground=[("selected", p["select_fg"])])
            self.style.map("Treeview.Heading",
                           background=[("active", p["bg"])])
            self.style.configure("TPanedwindow", background=p["bg"])
            self.style.configure("Sash", sashthickness=7)
            self.style.configure("Vertical.TScrollbar",
                                 background=p["button_bg"], troughcolor=p["bg"],
                                 arrowcolor=p["text"], borderwidth=0)
            self.style.configure("TSeparator", background=p["border"])
            self.style.configure("Toolbar.TFrame", background=p["toolbar_bg"])
        except tk.TclError:
            pass

    def _apply_look(self) -> None:
        p = self.palette
        self.configure(bg=p["bg"])
        try:
            self.style.theme_use("clam" if self.theme == "dark" else "vista")
        except tk.TclError:
            pass
        self._apply_style()
        self.toolbar.configure(bg=p["toolbar_bg"], highlightbackground=p["border"])
        if hasattr(self, "version_lbl"):
            self.version_lbl.configure(bg=p["toolbar_bg"], fg=p["muted"],
                                       font=self.fonts["small"])
        for menu in self._menus:
            try:
                menu.configure(bg=p["toolbar_bg"], fg=p["text"],
                               activebackground=p["select_bg"],
                               activeforeground=p["select_fg"],
                               font=self.fonts["body"])
            except tk.TclError:
                pass
        self.dark_var.set(self.theme == "dark")
        if hasattr(self, "detail"):
            self.detail.apply_look()
        if self._search_win is not None:
            try:
                if self._search_win.winfo_exists():
                    self._search_win.apply_look()
            except tk.TclError:
                pass
        if hasattr(self, "conv_tree"):
            self.refresh_list()

    def toggle_theme(self) -> None:
        self.theme = "dark" if self.theme == "light" else "light"
        self.palette = DARK if self.theme == "dark" else LIGHT
        self.settings.set("theme", self.theme)
        self._apply_look()

    def set_font_scale(self, scale: float) -> None:
        self.font_scale = min(1.6, max(0.8, round(scale, 2)))
        self.fonts = make_fonts(self.font_scale)
        self.settings.set("font_scale", self.font_scale)
        self._apply_style()
        if hasattr(self, "version_lbl"):
            self.version_lbl.configure(font=self.fonts["small"])
        for menu in self._menus:
            try:
                menu.configure(font=self.fonts["body"])
            except tk.TclError:
                pass
        if hasattr(self, "detail"):
            self.detail.apply_look()
        self.update_status(f"字号 {int(self.font_scale * 100)}%")

    def zoom(self, delta: float) -> None:
        self.set_font_scale(self.font_scale + delta)

    # ----- 菜单与工具栏 -----

    def _make_menu(self, parent: tk.Misc) -> tk.Menu:
        menu = tk.Menu(parent, tearoff=0, bg=self.palette["toolbar_bg"],
                       fg=self.palette["text"], font=self.fonts["body"],
                       activebackground=self.palette["select_bg"],
                       activeforeground=self.palette["select_fg"])
        self._menus.append(menu)
        return menu

    def _build_menu(self) -> None:
        menubar = tk.Menu(self)

        file_menu = self._make_menu(menubar)
        file_menu.add_command(label="导入文件…", accelerator="Ctrl+O",
                              command=self.import_files)
        file_menu.add_command(label="导入文件夹（含子目录）…",
                              command=self.import_folder)
        file_menu.add_separator()
        file_menu.add_command(label="合并导出 JSON…", command=self.merge_export)
        file_menu.add_command(label="导出 Markdown…", command=self.export_markdown)
        file_menu.add_command(label="导出单文件 HTML…", command=self.export_html)
        file_menu.add_separator()
        file_menu.add_command(label="打开数据目录",
                              command=lambda: open_folder(self.root_dir))
        file_menu.add_separator()
        file_menu.add_command(label="退出", command=self._on_close)
        menubar.add_cascade(label="文件", menu=file_menu)

        edit_menu = self._make_menu(menubar)
        edit_menu.add_command(label="全文搜索", accelerator="Ctrl+F",
                              command=self.open_search)
        edit_menu.add_command(label="刷新对话库", accelerator="F5",
                              command=self.refresh_library)
        edit_menu.add_separator()
        edit_menu.add_command(label="重命名当前对话", command=self._rename_current)
        edit_menu.add_command(label="编辑当前对话标签", command=self._tags_current)
        edit_menu.add_command(label="复制当前问答", accelerator="Ctrl+Shift+C",
                              command=self._copy_current)
        edit_menu.add_separator()
        edit_menu.add_command(label="勾选全部可见对话", command=self._check_all)
        edit_menu.add_command(label="清空勾选", command=self._clear_checked)
        menubar.add_cascade(label="编辑", menu=edit_menu)

        view_menu = self._make_menu(menubar)
        view_menu.add_command(label="统计", command=self.show_stats)
        view_menu.add_command(label="回收站", command=self.open_trash)
        view_menu.add_separator()
        view_menu.add_command(label="放大字号", accelerator="Ctrl+=",
                              command=lambda: self.zoom(0.1))
        view_menu.add_command(label="缩小字号", accelerator="Ctrl+-",
                              command=lambda: self.zoom(-0.1))
        view_menu.add_command(label="重置字号", accelerator="Ctrl+0",
                              command=lambda: self.set_font_scale(1.0))
        self.dark_var = tk.BooleanVar(value=self.theme == "dark")
        view_menu.add_checkbutton(label="夜间模式", variable=self.dark_var,
                                  command=self.toggle_theme)
        view_menu.add_separator()
        view_menu.add_command(label="重置窗口布局", command=self._reset_layout)
        menubar.add_cascade(label="视图", menu=view_menu)

        help_menu = self._make_menu(menubar)
        help_menu.add_command(label="库体检", command=self._health_check)
        help_menu.add_command(label="快捷键", command=self._show_shortcuts)
        help_menu.add_command(label="关于", command=self._about)
        menubar.add_cascade(label="帮助", menu=help_menu)

        self.config(menu=menubar)
        self._menus.append(menubar)

    def _build_toolbar(self) -> None:
        self.toolbar = tk.Frame(self, bg=self.palette["toolbar_bg"],
                                highlightbackground=self.palette["border"],
                                highlightthickness=1)
        self.toolbar.pack(fill="x", padx=8, pady=(8, 4))

        import_mb = ttk.Menubutton(self.toolbar, text="导入 ▾")
        menu = tk.Menu(import_mb, tearoff=0, bg=self.palette["toolbar_bg"],
                       fg=self.palette["text"], font=self.fonts["body"],
                       activebackground=self.palette["select_bg"],
                       activeforeground=self.palette["select_fg"])
        self._menus.append(menu)
        menu.add_command(label="导入文件…", command=self.import_files)
        menu.add_command(label="导入文件夹…", command=self.import_folder)
        import_mb.configure(menu=menu)
        import_mb.pack(side="left", padx=(10, 4), pady=6)

        for text, command in (
            ("全文搜索", self.open_search),
            ("统计", self.show_stats),
            ("回收站", self.open_trash),
            ("刷新库", self.refresh_library),
        ):
            ttk.Button(self.toolbar, text=text, command=command).pack(
                side="left", padx=4, pady=6)

        ttk.Separator(self.toolbar, orient="vertical").pack(
            side="left", fill="y", padx=8, pady=8)

        for text, command in (
            ("合并导出 JSON", self.merge_export),
            ("导出 Markdown", self.export_markdown),
            ("导出 HTML", self.export_html),
        ):
            ttk.Button(self.toolbar, text=text, command=command).pack(
                side="left", padx=4, pady=6)

        self.version_lbl = tk.Label(
            self.toolbar, text=f"v{core.VERSION}", bg=self.palette["toolbar_bg"],
            fg=self.palette["muted"], font=self.fonts["small"])
        self.version_lbl.pack(side="right", padx=12)
    def _build_statusbar(self) -> None:
        self.status = ttk.Label(self, style="Status.TLabel", anchor="w")
        self.status.pack(fill="x", side="bottom", padx=8, pady=(0, 6))

    def _build_main(self) -> None:
        self.main_pane = ttk.PanedWindow(self, orient="horizontal")
        self.main_pane.pack(fill="both", expand=True, padx=8, pady=4)

        left = ttk.Frame(self.main_pane, padding=(0, 0, 4, 0))
        self.main_pane.add(left, weight=1)
        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=1)

        filter_bar = ttk.Frame(left)
        filter_bar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        filter_bar.columnconfigure(1, weight=1)
        ttk.Label(filter_bar, text="筛选").grid(row=0, column=0, padx=(0, 4))
        self.filter_var = tk.StringVar()
        self.filter_entry = ttk.Entry(filter_bar, textvariable=self.filter_var)
        self.filter_entry.grid(row=0, column=1, sticky="ew", ipady=1)
        self.filter_var.trace_add("write", self._on_filter_typing)
        self.tag_var = tk.StringVar(value="全部标签")
        self.tag_box = ttk.Combobox(filter_bar, textvariable=self.tag_var, width=8,
                                    state="readonly", values=["全部标签"],
                                    postcommand=self._update_tag_box)
        self.tag_box.grid(row=0, column=2, padx=(4, 0))
        self.tag_box.bind("<<ComboboxSelected>>", lambda e: self.refresh_list())
        self.star_only = tk.BooleanVar()
        ttk.Checkbutton(filter_bar, text="★", variable=self.star_only,
                        command=self.refresh_list).grid(row=0, column=3, padx=(4, 0))

        cols = ("check", "star", "title", "count", "time")
        self.conv_tree = ttk.Treeview(left, columns=cols, show="headings",
                                      selectmode="browse")
        for col, text, width, anchor, stretch in (
            ("check", "合并", 42, "center", False),
            ("star", "★", 30, "center", False),
            ("title", "标题", 180, "w", True),
            ("count", "问答", 52, "e", False),
            ("time", "日期", 82, "center", False),
        ):
            self.conv_tree.heading(col, text=text)
            self.conv_tree.column(col, width=width, anchor=anchor, stretch=stretch,
                                  minwidth=30)
        self.conv_tree.heading("title", command=lambda: self._sort_by("title"))
        self.conv_tree.heading("count", command=lambda: self._sort_by("count"))
        self.conv_tree.heading("time", command=lambda: self._sort_by("date"))
        conv_ysb = ttk.Scrollbar(left, orient="vertical",
                                 command=self.conv_tree.yview)
        self.conv_tree.configure(yscrollcommand=conv_ysb.set)
        self.conv_tree.grid(row=1, column=0, sticky="nsew")
        conv_ysb.grid(row=1, column=1, sticky="ns")
        self.conv_tree.bind("<<TreeviewSelect>>", self._on_conv_selected)
        self.conv_tree.bind("<Button-1>", self._on_conv_click, add="+")
        self.conv_tree.bind("<Double-1>", self._on_conv_double)
        self.conv_tree.bind("<Button-3>", self._show_conv_menu)

        right = ttk.Frame(self.main_pane)
        self.main_pane.add(right, weight=4)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)

        self.right_pane = ttk.PanedWindow(right, orient="horizontal")
        self.right_pane.grid(row=0, column=0, sticky="nsew")

        qa_frame = ttk.Frame(self.right_pane, padding=(0, 0, 4, 0))
        self.right_pane.add(qa_frame, weight=2)
        qa_frame.columnconfigure(0, weight=1)
        qa_frame.rowconfigure(1, weight=1)

        qa_bar = ttk.Frame(qa_frame)
        qa_bar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        qa_bar.columnconfigure(1, weight=1)
        ttk.Label(qa_bar, text="问题").grid(row=0, column=0, padx=(0, 4))
        self.qa_filter_var = tk.StringVar()
        self.qa_filter_entry = ttk.Entry(qa_bar, textvariable=self.qa_filter_var)
        self.qa_filter_entry.grid(row=0, column=1, sticky="ew", ipady=1)
        self.qa_filter_var.trace_add("write", self._on_qa_filter_typing)
        self.qa_count_lbl = ttk.Label(qa_bar, text="0", style="Muted.TLabel", width=8,
                                      anchor="e")
        self.qa_count_lbl.grid(row=0, column=2, padx=(4, 0))

        self.qa_tree = ttk.Treeview(qa_frame, columns=("idx", "question"),
                                    show="headings", selectmode="browse")
        self.qa_tree.heading("idx", text="#")
        self.qa_tree.heading("question", text="用户问题")
        self.qa_tree.column("idx", width=48, anchor="center", stretch=False,
                            minwidth=36)
        self.qa_tree.column("question", width=260, anchor="w", stretch=True,
                            minwidth=100)
        qa_ysb = ttk.Scrollbar(qa_frame, orient="vertical", command=self.qa_tree.yview)
        self.qa_tree.configure(yscrollcommand=qa_ysb.set)
        self.qa_tree.grid(row=1, column=0, sticky="nsew")
        qa_ysb.grid(row=1, column=1, sticky="ns")
        self.qa_tree.bind("<<TreeviewSelect>>", self._on_qa_selected)
        for key, delta in (("j", 1), ("J", 1), ("k", -1), ("K", -1)):
            self.qa_tree.bind(f"<KeyPress-{key}>",
                              lambda e, d=delta: self.step_qa(d))

        self.detail = DetailView(self.right_pane, self)
        self.right_pane.add(self.detail, weight=3)

    def _bind_shortcuts(self) -> None:
        self.bind("<Control-o>", lambda e: (self.import_files(), "break")[1])
        self.bind("<Control-f>", lambda e: (self.open_search(), "break")[1])
        self.bind("<F5>", lambda e: (self.refresh_library(), "break")[1])
        self.bind("<Control-equal>", lambda e: (self.zoom(0.1), "break")[1])
        self.bind("<Control-plus>", lambda e: (self.zoom(0.1), "break")[1])
        self.bind("<Control-minus>", lambda e: (self.zoom(-0.1), "break")[1])
        self.bind("<Control-Key-0>", lambda e: (self.set_font_scale(1.0), "break")[1])
        self.bind("<Alt-Left>", lambda e: (self.step_qa(-1), "break")[1])
        self.bind("<Alt-Right>", lambda e: (self.step_qa(1), "break")[1])
        self.bind("<Control-Shift-C>", lambda e: (self._copy_current(), "break")[1])

    # ----- 首启 / 恢复状态 -----

    def _maybe_first_run(self) -> None:
        if self.lib.convs or self._library_existed:
            return
        try:
            paths = [
                os.path.join(self.root_dir, name)
                for name in os.listdir(self.root_dir)
                if name.lower().endswith(".json")
                and name not in (core.LIB_FILENAME, core.SETTINGS_FILENAME)
            ]
        except OSError:
            return
        result = self.lib.import_paths(paths)
        if result.added:
            self.conv_cache.clear()
            self.refresh_list()
            self.update_status(f"首次启动：已自动导入 {len(result.added)} 个对话文件")

    def _virtual_screen(self) -> Tuple[int, int, int, int]:
        if sys.platform.startswith("win"):
            try:
                user32 = ctypes.windll.user32
                return (
                    int(user32.GetSystemMetrics(76)),   # SM_XVIRTUALSCREEN
                    int(user32.GetSystemMetrics(77)),   # SM_YVIRTUALSCREEN
                    int(user32.GetSystemMetrics(78)),   # SM_CXVIRTUALSCREEN
                    int(user32.GetSystemMetrics(79)),   # SM_CYVIRTUALSCREEN
                )
            except (AttributeError, OSError):
                pass
        return (0, 0, self.winfo_screenwidth(), self.winfo_screenheight())

    def _safe_geometry(self, geometry: Optional[str]) -> Optional[str]:
        """把保存的窗口位置限制在当前虚拟屏幕内，避免换显示器后窗口跑到屏幕外。"""
        if not isinstance(geometry, str):
            return None
        match = re.match(r"^(\d+)x(\d+)([+-]\d+)([+-]\d+)$", geometry)
        if not match:
            return None
        width, height, x, y = (int(group) for group in match.groups())
        vx, vy, vw, vh = self._virtual_screen()
        if vw <= 100 or vh <= 100:
            return None
        width = min(width, vw)
        height = min(height, vh)
        x = max(vx, min(x, vx + vw - width))
        y = max(vy, min(y, vy + vh - height))
        return f"{width}x{height}{x:+d}{y:+d}"

    def _restore_view(self) -> None:
        geometry = self._safe_geometry(self.settings.get("geometry"))
        if geometry:
            try:
                self.geometry(geometry)
            except tk.TclError:
                pass
        last = self.settings.get("last_conv")
        visible = list(self.conv_tree.get_children())
        if last not in self.lib.convs or last not in visible:
            last = visible[0] if visible else None
        if last:
            self.conv_tree.selection_set(last)
            self.conv_tree.see(last)
            index = self.settings.get("last_qa", 1) if last == self.settings.get("last_conv") else 1
            try:
                index = int(index)
            except (TypeError, ValueError):
                index = 1
            self.show_conv(last, select_index=index)
        else:
            self.detail.clear()
        self.update_status()

    def _restore_sashes(self) -> None:
        try:
            main_pos = int(self.settings.get("sash_main", 440))
            right_pos = int(self.settings.get("sash_right", 330))
            if main_pos > 100:
                self.main_pane.sashpos(0, main_pos)
            if right_pos > 80:
                self.right_pane.sashpos(0, right_pos)
        except (tk.TclError, TypeError, ValueError):
            pass

    def _reset_layout(self) -> None:
        self.geometry("1360x840")
        try:
            self.main_pane.sashpos(0, 430)
            self.right_pane.sashpos(0, 340)
        except tk.TclError:
            pass
        self.settings.data.pop("sash_main", None)
        self.settings.data.pop("sash_right", None)
        self.settings.data.pop("geometry", None)

    # ----- 列表 -----

    def _on_filter_typing(self, *_args) -> None:
        if self._filter_after is not None:
            try:
                self.after_cancel(self._filter_after)
            except tk.TclError:
                pass
        self._filter_after = self.after(160, self.refresh_list)

    def _update_tag_box(self) -> None:
        self.tag_box["values"] = ["全部标签"] + self.lib.all_tags()

    def _sort_by(self, key: str) -> None:
        if self._sort_key == key:
            self._sort_rev = not self._sort_rev
        else:
            self._sort_key = key
            self._sort_rev = key == "date"
        self.settings.set("sort_key", self._sort_key)
        self.settings.set("sort_rev", self._sort_rev)
        self.refresh_list()

    def _sort_keyfunc(self, fname: str):
        meta = self.lib.convs[fname]
        if self._sort_key == "title":
            return str(meta.get("title", "")).lower()
        if self._sort_key == "count":
            return int(meta.get("count", 0) or 0)
        return str(meta.get("exported_at") or meta.get("added_at") or "")

    def refresh_list(self) -> None:
        if self._filter_after is not None:
            try:
                self.after_cancel(self._filter_after)
            except tk.TclError:
                pass
        self._filter_after = None
        selected = self.conv_tree.selection()
        current = selected[0] if selected else None
        self._checked &= set(self.lib.convs)
        self._loading = True
        try:
            self.conv_tree.delete(*self.conv_tree.get_children())
            keyword = self.filter_var.get().strip().lower()
            tag = self.tag_var.get()
            if tag != "全部标签" and tag not in self.lib.all_tags():
                tag = "全部标签"
                self.tag_var.set(tag)
            self._update_tag_box()

            fnames = [f for f in self.lib.convs
                      if (not keyword or keyword in str(self.lib.convs[f].get("title", "")).lower())
                      and (tag == "全部标签" or tag in self.lib.convs[f].get("tags", []))
                      and (not self.star_only.get() or self.lib.convs[f].get("starred"))]
            fnames.sort(key=self._sort_keyfunc, reverse=self._sort_rev)
            for fname in fnames:
                meta = self.lib.convs[fname]
                self.conv_tree.insert("", "end", iid=fname, values=(
                    "☑" if fname in self._checked else "☐",
                    "★" if meta.get("starred") else "☆",
                    meta.get("title", fname),
                    meta.get("count", 0),
                    (meta.get("exported_at") or meta.get("added_at") or "")[:10],
                ))
            arrow = " ▼" if self._sort_rev else " ▲"
            for col, label in (("title", "标题"), ("count", "问答"), ("time", "日期")):
                suffix = arrow if self._sort_key == col else ""
                self.conv_tree.heading(col, text=label + suffix)
            if current in self.conv_tree.get_children():
                self.conv_tree.selection_set(current)
        finally:
            self._loading = False
        self.update_status()

    def update_status(self, extra: str = "") -> None:
        total_qa = sum(int(m.get("count", 0) or 0) for m in self.lib.convs.values())
        visible = len(self.conv_tree.get_children()) if hasattr(self, "conv_tree") else 0
        parts = [
            f"对话 {len(self.lib.convs)} 个",
            f"问答 {core.fmt_count(total_qa)} 组",
            f"已勾选 {len(self._checked)} 个",
        ]
        if visible != len(self.lib.convs):
            parts.append(f"筛选中 {visible} 个")
        if self.lib.missing:
            parts.append(f"缺失 {len(self.lib.missing)} 个（元数据已保留）")
        if extra:
            parts.append(extra)
        self.status.config(text=" · ".join(parts))

    def _on_conv_click(self, event) -> None:
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

    def _on_conv_double(self, event) -> None:
        item = self.conv_tree.identify_row(event.y)
        col = self.conv_tree.identify_column(event.x)
        if item and col == "#3":
            self.rename_conv(item)

    def _show_conv_menu(self, event) -> None:
        item = self.conv_tree.identify_row(event.y)
        if not item:
            return
        self.conv_tree.selection_set(item)
        if item != self.cur_conv:
            self.show_conv(item)
        meta = self.lib.convs[item]
        p = self.palette
        menu = tk.Menu(self, tearoff=0, bg=p["toolbar_bg"], fg=p["text"],
                       font=self.fonts["body"], activebackground=p["select_bg"],
                       activeforeground=p["select_fg"])
        menu.add_command(label="打开", command=lambda: self.show_conv(item))
        menu.add_command(
            label="取消星标" if meta.get("starred") else "加星标",
            command=lambda: self._toggle_star(item))
        menu.add_command(label="编辑标签", command=lambda: self.edit_tags(item))
        menu.add_command(label="重命名", command=lambda: self.rename_conv(item))
        menu.add_separator()
        menu.add_command(
            label="取消勾选" if item in self._checked else "勾选（用于合并导出）",
            command=lambda: self._toggle_check(item))
        menu.add_separator()
        menu.add_command(label="导出为 Markdown",
                         command=lambda: self.export_markdown(force=item))
        menu.add_command(label="导出为 HTML",
                         command=lambda: self.export_html(force=item))
        menu.add_command(label="在资源管理器中显示",
                         command=lambda: open_folder(self.lib.dir))
        menu.add_separator()
        menu.add_command(label="删除（移入回收站）",
                         command=lambda: self.delete_conv(item))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
            menu.destroy()

    def _toggle_check(self, fname: str) -> None:
        if fname in self._checked:
            self._checked.discard(fname)
        else:
            self._checked.add(fname)
        if self.conv_tree.exists(fname):
            self.conv_tree.set(fname, "check",
                               "☑" if fname in self._checked else "☐")
        self.update_status()

    def _check_all(self) -> None:
        for fname in self.conv_tree.get_children():
            self._checked.add(fname)
            self.conv_tree.set(fname, "check", "☑")
        self.update_status()

    def _clear_checked(self) -> None:
        self._checked.clear()
        for fname in self.conv_tree.get_children():
            self.conv_tree.set(fname, "check", "☐")
        self.update_status()

    def _toggle_star(self, fname: str) -> None:
        meta = self.lib.convs.get(fname)
        if not meta:
            return
        meta["starred"] = not meta.get("starred")
        self.lib.save()
        self.refresh_list()
        if fname == self.cur_conv:
            self.detail.star_btn.config(text="★" if meta["starred"] else "☆")
        self.update_status(("已加星标" if meta["starred"] else "已取消星标")
                           + f"：{meta.get('title', fname)}")

    def _toggle_star_current(self) -> None:
        if self.cur_conv:
            self._toggle_star(self.cur_conv)

    def rename_conv(self, fname: str) -> None:
        meta = self.lib.convs.get(fname)
        if not meta:
            return
        title = simpledialog.askstring(
            "重命名", "新的显示标题：", initialvalue=meta.get("title", ""),
            parent=self)
        if title and title.strip():
            meta["title"] = title.strip()
            meta["title_custom"] = True
            self.lib.save()
            self.refresh_list()
            if fname == self.cur_conv:
                self.detail.title_lbl.config(text=meta["title"])
            self.update_status(f"已重命名为：{meta['title']}")

    def edit_tags(self, fname: str) -> None:
        meta = self.lib.convs.get(fname)
        if not meta:
            return
        current = ", ".join(meta.get("tags", []))
        text = simpledialog.askstring(
            "编辑标签", "标签（用逗号分隔，可留空）：", initialvalue=current,
            parent=self)
        if text is None:
            return
        meta["tags"] = [t.strip() for t in text.replace("，", ",").split(",") if t.strip()]
        self.lib.save()
        self.refresh_list()
        if fname == self.cur_conv:
            self._refresh_header()
        self.update_status(f"标签已更新：{meta.get('title', fname)}")

    def delete_conv(self, fname: str) -> None:
        meta = self.lib.convs.get(fname)
        if not meta:
            return
        if not messagebox.askyesno(
                "删除对话",
                f"确定删除「{meta.get('title', fname)}」吗？\n"
                "文件会移入回收站，可随时还原。",
                parent=self):
            return
        try:
            self.lib.remove(fname)
        except (OSError, KeyError) as exc:
            messagebox.showerror("删除失败", str(exc), parent=self)
            return
        self._checked.discard(fname)
        self._positions.pop(fname, None)
        self.conv_cache.pop(fname, None)
        if self.cur_conv == fname:
            self.cur_conv = None
            self.qa_tree.delete(*self.qa_tree.get_children())
            self._qa_indices = []
            self._qa_data = []
            self.detail.clear()
        self.refresh_list()
        self.update_status(f"已移入回收站：{meta.get('title', fname)}")

    def _rename_current(self) -> None:
        if self.cur_conv:
            self.rename_conv(self.cur_conv)

    def _tags_current(self) -> None:
        if self.cur_conv:
            self.edit_tags(self.cur_conv)

    # ----- 浏览 -----

    def _load_conv(self, fname: str) -> Dict[str, Any]:
        if fname not in self.conv_cache:
            if len(self.conv_cache) >= 8:
                self.conv_cache.clear()
            self.conv_cache[fname] = self.lib.read_conversation(fname)
        return self.conv_cache[fname]

    def _cur_pairs(self) -> List[Dict[str, Any]]:
        return self._qa_data

    def qa_pos(self) -> int:
        selection = self.qa_tree.selection()
        if not selection:
            return 0
        try:
            return int(selection[0])
        except (TypeError, ValueError):
            return 0

    def qa_total(self) -> int:
        return len(self._qa_data)

    def _refresh_header(self) -> None:
        if not self.cur_conv or self.cur_conv not in self.lib.convs:
            return
        meta = self.lib.convs[self.cur_conv]
        data = self._load_conv(self.cur_conv)
        parts = [f"{len(data.get('qa_pairs', []))} 组问答"]
        if data.get("exported_at"):
            parts.append(f"导出于 {data['exported_at']}")
        if meta.get("tags"):
            tags = "、".join(meta["tags"])
            if len(tags) > 36:
                tags = tags[:35] + "…"
            parts.append("标签：" + tags)
        self.detail.set_conv(meta.get("title", self.cur_conv), " · ".join(parts),
                             meta.get("starred", False),
                             source_url=str(data.get("source_url") or ""))

    def show_conv(self, fname: str, select_index: Optional[int] = None) -> Optional[Dict[str, Any]]:
        if fname not in self.lib.convs:
            return None
        try:
            data = self._load_conv(fname)
        except (OSError, ValueError, core.DataError) as exc:
            messagebox.showerror("打开失败", str(exc), parent=self)
            return None
        self.cur_conv = fname
        self._qa_data = [qa for qa in data.get("qa_pairs", []) if isinstance(qa, dict)]
        self._refresh_header()
        if select_index is None:
            select_index = self._positions.get(fname, 1)
        self._populate_qa(select_index=select_index, preserve_current=False)
        self.settings.set("last_conv", fname)
        self.update_status(f"当前：{self.lib.convs[fname].get('title', fname)}")
        return data

    def _on_qa_filter_typing(self, *_args) -> None:
        if self._qa_filter_after is not None:
            try:
                self.after_cancel(self._qa_filter_after)
            except tk.TclError:
                pass
        self._qa_filter_after = self.after(140, lambda: self._populate_qa())

    def _populate_qa(self, select_index: Optional[int] = None,
                     preserve_current: bool = True) -> None:
        if self._qa_filter_after is not None:
            try:
                self.after_cancel(self._qa_filter_after)
            except tk.TclError:
                pass
        self._qa_filter_after = None
        if self.cur_conv is None:
            return
        keyword = self.qa_filter_var.get().strip().lower()
        current = self.qa_pos() if preserve_current else 0
        self._loading = True
        try:
            self.qa_tree.delete(*self.qa_tree.get_children())
            visible: List[int] = []
            for index, qa in enumerate(self._qa_data, 1):
                question = core.qa_field(qa, "user")
                if keyword and keyword not in question.lower():
                    continue
                visible.append(index)
                short = question.replace("\n", " ")[:64]
                self.qa_tree.insert("", "end", iid=str(index), values=(index, short))
            self._qa_indices = visible
            self.qa_count_lbl.config(
                text=f"{len(visible)}/{len(self._qa_data)}" if keyword
                else str(len(self._qa_data)))
            target = select_index if select_index in visible else None
            if target is None and current in visible:
                target = current
            if target is None and visible:
                target = visible[0]
            if target is not None:
                self.qa_tree.selection_set(str(target))
                self.qa_tree.see(str(target))
                self.cur_index = target
                self._show_qa(target)
            else:
                self.detail.show(None)
        finally:
            self._loading = False

    def _show_qa(self, index: int, keyword: Optional[str] = None) -> None:
        if not (1 <= index <= len(self._qa_data)):
            self.detail.show(None)
            return
        self.cur_index = index
        self.detail.show(self._qa_data[index - 1], keyword=keyword)
        self.settings.set("last_conv", self.cur_conv)
        self.settings.set("last_qa", index)
        if self.cur_conv:
            self._positions[self.cur_conv] = index

    def _on_conv_selected(self, event=None) -> None:
        if self._loading:
            return
        selection = self.conv_tree.selection()
        if not selection:
            return
        fname = selection[0]
        if fname != self.cur_conv:
            self.show_conv(fname)

    def _on_qa_selected(self, event=None) -> None:
        if self._loading or not self.cur_conv:
            return
        index = self.qa_pos()
        if 1 <= index <= len(self._qa_data):
            self._show_qa(index)

    def step_qa(self, delta: int) -> None:
        visible = self._qa_indices or list(range(1, len(self._qa_data) + 1))
        if not visible:
            return
        current = self.qa_pos()
        if current in visible:
            position = visible.index(current) + delta
        else:
            position = 0 if delta > 0 else len(visible) - 1
        position = min(max(position, 0), len(visible) - 1)
        target = visible[position]
        self.qa_tree.selection_set(str(target))
        self.qa_tree.see(str(target))
        self.qa_tree.focus(str(target))
        self._show_qa(target)

    def jump_to_qa(self, fname: str, index: int, keyword: Optional[str] = None) -> None:
        if fname not in self.lib.convs:
            messagebox.showwarning("定位", "该对话已不在库中。", parent=self)
            return
        if fname not in self.conv_tree.get_children():
            self.filter_var.set("")
            self.tag_var.set("全部标签")
            self.star_only.set(False)
            self.refresh_list()
        self.qa_filter_var.set("")
        self._loading = True
        try:
            self.conv_tree.selection_set(fname)
            self.conv_tree.see(fname)
        finally:
            self._loading = False
        self.show_conv(fname, select_index=index)
        self._show_qa(index, keyword=keyword)
        self.deiconify()
        self.lift()
        self.detail.focus_set()

    def _copy_current(self) -> None:
        self.detail._copy()

    # ----- 刷新 / 体检 -----

    def refresh_library(self) -> None:
        changed = self.lib.sync()
        self.conv_cache.clear()
        self.refresh_list()
        if self.cur_conv and self.cur_conv in self.lib.convs:
            self.show_conv(self.cur_conv, select_index=self.cur_index)
        elif self.cur_conv:
            self.cur_conv = None
            self.qa_tree.delete(*self.qa_tree.get_children())
            self._qa_data = []
            self._qa_indices = []
            self.detail.clear()
        self.update_status("对话库已刷新" + ("（有文件发生变化）" if changed else ""))

    def _health_check(self) -> None:
        result = core.validate_library(self.lib)
        if not result["issues"]:
            messagebox.showinfo(
                "库体检",
                f"检查了 {result['conversations']} 个对话，未发现问题。", parent=self)
            return
        lines = []
        for issue in result["issues"][:14]:
            mark = "错误" if issue["severity"] == "error" else "警告"
            lines.append(f"[{mark}] {issue['file']}\n    {issue['message']}")
        if len(result["issues"]) > 14:
            lines.append(f"……另有 {len(result['issues']) - 14} 条")
        messagebox.showwarning(
            "库体检",
            f"发现 {result['errors']} 个错误、{result['warnings']} 个警告：\n\n"
            + "\n".join(lines), parent=self)

    def _show_shortcuts(self) -> None:
        messagebox.showinfo(
            "快捷键",
            "Ctrl+F      全文搜索\n"
            "F5          刷新对话库\n"
            "Ctrl+O      导入文件\n"
            "Alt+← / →   上一条 / 下一条问答\n"
            "J / K       下一条 / 上一条（问答列表聚焦时）\n"
            "Ctrl+= / -  放大 / 缩小字号\n"
            "Ctrl+0      重置字号\n"
            "Ctrl+Shift+C 复制当前问答\n"
            "Esc         关闭搜索窗口\n\n"
            "提示：点击列表『合并』列勾选对话，再合并导出。",
            parent=self)

    def _about(self) -> None:
        messagebox.showinfo(
            "关于",
            f"{APP_TITLE} v{core.VERSION}\n\n"
            "本地管理 AI 对话 JSON 记忆库：导入、浏览、全文搜索、\n"
            "标签、回收站、统计、Markdown / HTML 导出。\n\n"
            "纯 Python 标准库实现，零第三方依赖。\n"
            f"数据目录：{self.root_dir}", parent=self)

    # ----- 导入 -----

    def import_files(self) -> None:
        paths = filedialog.askopenfilenames(
            parent=self, title="选择对话 JSON 文件",
            filetypes=[("JSON 文件", "*.json"), ("所有文件", "*.*")])
        if paths:
            self._do_import(list(paths))

    def import_folder(self) -> None:
        folder = filedialog.askdirectory(
            parent=self, title="选择包含对话 JSON 的文件夹（会扫描子目录）")
        if not folder:
            return
        paths = []
        for dirpath, dirnames, filenames in os.walk(folder):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for name in filenames:
                if name.lower().endswith(".json"):
                    paths.append(os.path.join(dirpath, name))
        if not paths:
            messagebox.showinfo("导入", "该文件夹及其子目录下没有 JSON 文件。", parent=self)
            return
        self._do_import(paths)

    def _do_import(self, paths: Sequence[str]) -> None:
        result = self.lib.import_paths(paths)
        self.conv_cache.clear()
        self.refresh_list()
        opening = result.added or result.restored
        if opening:
            self.show_conv(opening[0])
        lines = [f"新增 {len(result.added)} 个对话。"]
        if result.restored:
            lines.append(f"接回 {len(result.restored)} 个此前文件缺失的对话"
                         "（标题/标签/星标已恢复）。")
        if result.duplicates:
            lines.append(f"\n跳过重复 {len(result.duplicates)} 个（内容已在库中）：")
            for name, existing in result.duplicates[:8]:
                lines.append(f"  · {name} → {existing}")
            if len(result.duplicates) > 8:
                lines.append(f"  ……另有 {len(result.duplicates) - 8} 个")
        if result.skipped:
            lines.append(f"\n跳过 {len(result.skipped)} 个文件：")
            for name, reason in result.skipped[:8]:
                lines.append(f"  · {name}：{reason}")
            if len(result.skipped) > 8:
                lines.append(f"  ……另有 {len(result.skipped) - 8} 个")
        messagebox.showinfo("导入完成", "\n".join(lines), parent=self)
        self.update_status(
            f"导入完成：新增 {len(result.added)} 个"
            + (f"，接回 {len(result.restored)} 个" if result.restored else ""))

    # ----- 勾选与导出 -----

    def _checked_in_view(self) -> List[str]:
        visible = [f for f in self.conv_tree.get_children() if f in self._checked]
        rest = [f for f in self.lib.sorted_fnames()
                if f in self._checked and f not in visible]
        return visible + rest

    def _export_targets(self, force: Optional[str] = None) -> List[str]:
        if force:
            return [force] if force in self.lib.convs else []
        checked = self._checked_in_view()
        if checked:
            return checked
        selection = self.conv_tree.selection()
        return [selection[0]] if selection else []

    def _save_path(self, title: str, default_name: str, ext: str, types) -> str:
        initial_dir = self.settings.get("last_export_dir") or self.root_dir
        path = filedialog.asksaveasfilename(
            parent=self, title=title, defaultextension=ext,
            initialfile=default_name, initialdir=initial_dir, filetypes=types)
        return path or ""

    def _remember_export(self, path: str) -> None:
        self.settings.set("last_export_dir", os.path.dirname(path))

    def merge_export(self) -> None:
        fnames = self._checked_in_view()
        if not fnames:
            messagebox.showwarning(
                "合并导出", "请先点击列表『合并』列勾选要合并的对话。", parent=self)
            return
        try:
            data = core.merge_conversations(self.lib, fnames,
                                            data_loader=self._load_conv)
        except (OSError, ValueError, core.DataError) as exc:
            messagebox.showerror("合并失败", str(exc), parent=self)
            return
        default = f"合并导出_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
        path = self._save_path("合并导出 JSON", default, ".json",
                               [("JSON 文件", "*.json")])
        if not path:
            return
        try:
            core.atomic_write_json(path, data)
        except OSError as exc:
            messagebox.showerror("导出失败", str(exc), parent=self)
            return
        self._remember_export(path)
        messagebox.showinfo(
            "合并导出完成",
            f"已合并 {len(fnames)} 个对话，共 {len(data['qa_pairs'])} 组问答。\n"
            f"保存至：\n{path}", parent=self)

    def export_markdown(self, force: Optional[str] = None) -> None:
        fnames = self._export_targets(force)
        if not fnames:
            messagebox.showwarning("导出 Markdown", "请先勾选或选中一个对话。", parent=self)
            return
        default = f"记忆导出_{datetime.now().strftime('%Y%m%d_%H%M')}.md"
        path = self._save_path("导出 Markdown", default, ".md",
                               [("Markdown 文件", "*.md"), ("所有文件", "*.*")])
        if not path:
            return
        try:
            blocks = [core.to_markdown(self._load_conv(fname)) for fname in fnames]
            core.atomic_write_text(path, "\n\n".join(blocks))
        except (OSError, ValueError, core.DataError) as exc:
            messagebox.showerror("导出失败", str(exc), parent=self)
            return
        self._remember_export(path)
        messagebox.showinfo(
            "导出完成",
            f"已导出 {len(fnames)} 个对话到 Markdown。\n保存至：\n{path}", parent=self)

    def export_html(self, force: Optional[str] = None) -> None:
        fnames = self._export_targets(force)
        if not fnames:
            messagebox.showwarning("导出 HTML", "请先勾选或选中一个对话。", parent=self)
            return
        default = f"记忆存档_{datetime.now().strftime('%Y%m%d_%H%M')}.html"
        path = self._save_path("导出单文件 HTML", default, ".html",
                               [("HTML 文件", "*.html"), ("所有文件", "*.*")])
        if not path:
            return
        try:
            docs = [self._load_conv(fname) for fname in fnames]
            page_title = (core.conversation_title(docs[0]) if len(docs) == 1
                          else f"AI 记忆导出 · {len(docs)} 个对话")
            core.atomic_write_text(path, core.to_html(docs, title=page_title))
        except (OSError, ValueError, core.DataError) as exc:
            messagebox.showerror("导出失败", str(exc), parent=self)
            return
        self._remember_export(path)
        messagebox.showinfo(
            "导出完成",
            f"已导出 {len(fnames)} 个对话为单文件 HTML（可离线打开、支持夜间模式）。\n"
            f"保存至：\n{path}", parent=self)

    # ----- 窗口 -----

    def _reuse_window(self, attr: str) -> Optional[tk.Toplevel]:
        window = getattr(self, attr, None)
        if window is not None:
            try:
                if window.winfo_exists():
                    bring_to_front(window)
                    return window
            except tk.TclError:
                pass
        return None

    def open_search(self) -> None:
        if self._reuse_window("_search_win"):
            return
        self._search_win = SearchWindow(self)

    def show_stats(self) -> None:
        if self._stats_win is not None:
            try:
                if self._stats_win.winfo_exists():
                    self._stats_win.destroy()
            except tk.TclError:
                pass
        self._stats_win = StatsWindow(self)

    def open_trash(self) -> None:
        if self._reuse_window("_trash_win"):
            return
        self._trash_win = TrashWindow(self)

    # ----- 退出 -----

    def destroy(self) -> None:
        for attr in ("_filter_after", "_qa_filter_after",
                     "_restore_after", "_notice_after"):
            after_id = getattr(self, attr, None)
            if after_id is not None:
                try:
                    self.after_cancel(after_id)
                except tk.TclError:
                    pass
                setattr(self, attr, None)
        for attr in ("_search_win", "_stats_win", "_trash_win"):
            window = getattr(self, attr, None)
            if window is not None:
                try:
                    if window.winfo_exists():
                        window.destroy()
                except tk.TclError:
                    pass
                setattr(self, attr, None)
        super().destroy()

    def _on_close(self) -> None:
        try:
            if self.state() != "iconic":
                self.settings.set("geometry", self.geometry())
            self.settings.set("sash_main", self.main_pane.sashpos(0))
            self.settings.set("sash_right", self.right_pane.sashpos(0))
            self.settings.set("checked", sorted(self._checked))
            self.settings.set("positions",
                              {k: v for k, v in self._positions.items()
                               if k in self.lib.convs})
            self.settings.save()
        except (tk.TclError, ValueError):
            pass
        self.destroy()


def run(root_dir: Optional[str] = None) -> None:
    app = App(root_dir)
    app.mainloop()


if __name__ == "__main__":
    run()
