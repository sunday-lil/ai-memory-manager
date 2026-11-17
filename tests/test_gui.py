# -*- coding: utf-8 -*-
"""GUI 冒烟测试：不进入 mainloop，只验证布局与关键交互。"""

import json
import os
import re
import tempfile
import unittest

try:
    import tkinter as tk
except ImportError:  # pragma: no cover
    tk = None

import memory_core as core
try:
    from tests.test_core import make_conversation, write_json
except ImportError:  # 直接运行 tests/test_gui.py 时
    from test_core import make_conversation, write_json


@unittest.skipIf(tk is None, "没有 tkinter")
class GuiSmokeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="mm-gui-test-")
        self.root = self.tmp.name
        write_json(os.path.join(self.root, "对话.json"),
                   make_conversation("界面测试对话", 3))
        try:
            import memory_gui
            self.gui = memory_gui
            self.app = memory_gui.App(self.root)
        except Exception as exc:  # Tk 不可用（无显示）时跳过
            self.tmp.cleanup()
            if "display" in str(exc).lower() or "tcl" in str(exc).lower():
                self.skipTest(f"Tk 不可用：{exc}")
            raise
        self.app.update()
        self.app.withdraw()

    def tearDown(self):
        if hasattr(self, "app"):
            try:
                self.app.destroy()
            except tk.TclError:
                pass
        if hasattr(self, "tmp"):
            self.tmp.cleanup()

    def _scrollbar_for(self, tree):
        bars = [w for w in tree.master.winfo_children()
                if w.winfo_class() == "TScrollbar"]
        self.assertEqual(len(bars), 1)
        return bars[0]

    def test_layout_scrollbars_fill_height(self):
        """回归：滚动条曾被 pack 挤成 51px 高的小条。"""
        for tree in (self.app.conv_tree, self.app.qa_tree):
            bar = self._scrollbar_for(tree)
            self.assertGreater(bar.winfo_height(), 100)
            self.assertAlmostEqual(tree.winfo_height(), bar.winfo_height(), delta=3)

    def test_first_run_import_and_auto_select(self):
        self.assertEqual(len(self.app.lib.convs), 1)
        self.assertIsNotNone(self.app.cur_conv)
        self.assertEqual(self.app.qa_total(), 3)
        self.assertEqual(self.app.qa_pos(), 1)
        self.assertEqual(len(self.app.detail._texts), 3)
        self.assertIn("界面测试对话", self.app.detail.title_lbl.cget("text"))

    def test_qa_filter_and_step(self):
        self.app.qa_filter_var.set("问题2")
        self.app._populate_qa()
        self.assertEqual(self.app._qa_indices, [2])
        self.assertEqual(self.app.qa_pos(), 2)
        self.app.qa_filter_var.set("")
        self.app._populate_qa()
        self.app.step_qa(1)
        self.assertEqual(self.app.qa_pos(), 3)
        self.app.step_qa(-1)
        self.assertEqual(self.app.qa_pos(), 2)

    def test_per_conversation_position(self):
        self.app._show_qa(3)
        self.assertEqual(self.app._positions[self.app.cur_conv], 3)
        self.app.show_conv(self.app.cur_conv)
        self.assertEqual(self.app.qa_pos(), 3)

    def test_search_jump_highlight(self):
        window = self.gui.SearchWindow(self.app)
        try:
            window.kw_var.set("记忆")
            window.search()
            self.assertEqual(len(window.hits), 3)
            window._jump()
            self.assertEqual(self.app.detail.keyword, "记忆")
            self.assertEqual(self.app.qa_pos(), 1)
        finally:
            window.destroy()

    def test_safe_geometry_clamps_offscreen(self):
        geometry = self.app._safe_geometry("3000x2000-9000+9000")
        self.assertIsNotNone(geometry)
        match = re.match(r"^(\d+)x(\d+)([+-]\d+)([+-]\d+)$", geometry)
        self.assertIsNotNone(match)
        width, height, x, y = (int(g) for g in match.groups())
        vx, vy, vw, vh = self.app._virtual_screen()
        self.assertLessEqual(width, vw)
        self.assertLessEqual(height, vh)
        self.assertGreaterEqual(x, vx)
        self.assertGreaterEqual(y, vy)
        self.assertLessEqual(x + width, vx + vw)
        self.assertLessEqual(y + height, vy + vh)

    def test_theme_toggle_rerenders(self):
        self.app.toggle_theme()
        self.app.update()
        self.assertEqual(self.app.theme, "dark")
        self.assertEqual(self.app.detail.canvas.cget("bg"),
                         self.app.palette["bg"])
        self.assertEqual(len(self.app.detail._texts), 3)
        self.app.toggle_theme()
        self.app.update()
        self.assertEqual(self.app.theme, "light")

    def test_trash_window_restore(self):
        window = self.gui.TrashWindow(self.app)
        try:
            fname = self.app.cur_conv
            self.app.lib.remove(fname)
            window.refresh()
            self.assertEqual(len(window.tree.get_children()), 1)
            window.tree.selection_set(window.tree.get_children()[0])
            window.restore()
            self.assertIn(fname, self.app.lib.convs)
            self.assertEqual(window.tree.get_children(), ())
        finally:
            window.destroy()


if __name__ == "__main__":
    unittest.main()
