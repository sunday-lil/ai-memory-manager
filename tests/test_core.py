# -*- coding: utf-8 -*-
"""memory_core 的单元测试。运行：python -m unittest discover -s tests -v"""

import json
import os
import shutil
import tempfile
import time
import unittest

import memory_core as core


def make_conversation(title="测试对话", count=3, exported_at="2026-01-02 03:04:05",
                      answer="回答正文"):
    return {
        "conversation_title": title,
        "exported_at": exported_at,
        "source_url": "https://example.com/chat",
        "source_type": "test",
        "qa_pairs": [
            {
                "index": i,
                "question": f"{title} 问题{i}：记忆与服务器",
                "thinking_seconds": f"{i}.5秒",
                "thinking": f"关于{i}的思考过程",
                "deepseek": f"{answer}{i}",
                "references": [],
            }
            for i in range(1, count + 1)
        ],
    }


def write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


class TempLibraryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="mm-test-")
        self.root = self.tmp.name
        self.lib = core.Library(self.root).load()

    def tearDown(self):
        self.tmp.cleanup()

    def add_conversation(self, filename="conv.json", title="测试对话", count=3):
        path = os.path.join(self.root, filename)
        write_json(path, make_conversation(title, count))
        result = self.lib.import_paths([path])
        self.assertEqual(len(result.added), 1, result)
        return result.added[0]

    # --- 字段兼容 ---

    def test_field_compatibility_and_seconds(self):
        self.assertEqual(core.first_key({"answer": "A"}, core.A_KEYS), "A")
        self.assertEqual(core.first_key({"thinking": "T"}, core.A_KEYS), "")
        self.assertEqual(core.qa_field({"user": "问"}, "user"), "问")
        self.assertAlmostEqual(core.parse_seconds("12.45秒"), 12.45)
        self.assertAlmostEqual(core.parse_seconds("1分20秒"), 80.0)
        self.assertAlmostEqual(core.parse_seconds(3), 3.0)
        self.assertEqual(core.parse_seconds("未知"), 0.0)

    # --- 导入 / 去重 / 同步 ---

    def test_import_dedupe_and_metadata(self):
        fname = self.add_conversation()
        self.assertEqual(self.lib.convs[fname]["count"], 3)
        self.assertEqual(self.lib.convs[fname]["title"], "测试对话")
        self.assertTrue(self.lib.convs[fname]["sha1"])

        # 同一内容再次导入应被识别为重复，而不是产生 _1 副本
        source = os.path.join(self.root, "conv.json")
        again = self.lib.import_paths([source])
        self.assertEqual(again.added, [])
        self.assertEqual(len(again.duplicates), 1)
        self.assertEqual(len(self.lib.convs), 1)

        # 重新打开库，元数据仍然存在
        reloaded = core.Library(self.root).load()
        self.assertIn(fname, reloaded.convs)
        self.assertEqual(reloaded.convs[fname]["count"], 3)

    def test_invalid_files_are_skipped(self):
        bad = os.path.join(self.root, "bad.json")
        with open(bad, "w", encoding="utf-8") as f:
            f.write("{not json")
        plain = os.path.join(self.root, "plain.json")
        write_json(plain, {"hello": "world"})
        result = self.lib.import_paths([bad, plain, os.path.join(self.root, "nope.json")])
        self.assertEqual(result.added, [])
        self.assertEqual(len(result.skipped), 3)

    def test_sync_detects_external_change_and_preserves_user_state(self):
        fname = self.add_conversation(count=2)
        meta = self.lib.convs[fname]
        meta["tags"] = ["重要"]
        meta["starred"] = True
        meta["title"] = "我的自定义标题"
        meta["title_custom"] = True
        self.lib.save()

        path = self.lib.path(fname)
        time.sleep(0.02)
        write_json(path, make_conversation("外部新标题", count=5))

        self.assertTrue(self.lib.sync())
        meta = self.lib.convs[fname]
        self.assertEqual(meta["count"], 5)
        self.assertEqual(meta["title"], "我的自定义标题")
        self.assertEqual(meta["tags"], ["重要"])
        self.assertTrue(meta["starred"])
        self.assertEqual(self.lib.last_sync_changes, 1)

    def test_sync_updates_non_custom_title(self):
        fname = self.add_conversation(title="旧标题", count=1)
        time.sleep(0.02)
        write_json(self.lib.path(fname), make_conversation("新标题", count=2))
        self.lib.sync()
        self.assertEqual(self.lib.convs[fname]["title"], "新标题")
        self.assertEqual(self.lib.convs[fname]["count"], 2)

    def test_legacy_library_keeps_custom_title(self):
        os.makedirs(self.lib.dir, exist_ok=True)
        write_json(os.path.join(self.lib.dir, "old.json"),
                   make_conversation("文件里的标题", 1))
        write_json(self.lib.file, {"conversations": {
            "old.json": {
                "title": "用户改过的标题",
                "tags": ["旧标签"],
                "starred": True,
                "added_at": "2026-01-01 00:00",
                "count": 1,
                "exported_at": "2026-01-01 00:00:00",
            }
        }})
        legacy = core.Library(self.root).load()
        meta = legacy.convs["old.json"]
        self.assertEqual(meta["title"], "用户改过的标题")
        self.assertTrue(meta["title_custom"])
        self.assertNotIn("_legacy_meta", meta)
        saved = core.load_json(legacy.file)["conversations"]["old.json"]
        self.assertNotIn("_legacy_meta", saved)

    def test_missing_file_metadata_preserved_and_restored(self):
        fname = self.add_conversation(count=2)
        meta = self.lib.convs[fname]
        meta["tags"] = ["重要"]
        meta["starred"] = True
        meta["title"] = "自定义标题"
        meta["title_custom"] = True
        self.lib.save()

        path = self.lib.path(fname)
        keep = os.path.join(self.root, "keep.json")
        shutil.copy2(path, keep)
        os.remove(path)

        self.assertTrue(self.lib.sync())
        self.assertNotIn(fname, self.lib.convs)
        self.assertIn(fname, self.lib.missing)
        saved = core.load_json(self.lib.file)
        self.assertIn("missing", saved)
        self.assertIn(fname, saved["missing"])

        report = core.validate_library(self.lib)
        self.assertTrue(any("缺失" in issue["message"] for issue in report["issues"]))

        shutil.copy2(keep, path)
        os.remove(keep)
        self.assertTrue(self.lib.sync())
        self.assertIn(fname, self.lib.convs)
        self.assertNotIn(fname, self.lib.missing)
        restored = self.lib.convs[fname]
        self.assertEqual(restored["tags"], ["重要"])
        self.assertTrue(restored["starred"])
        self.assertEqual(restored["title"], "自定义标题")

    def test_import_restores_missing_metadata(self):
        fname = self.add_conversation(count=1)
        self.lib.convs[fname]["tags"] = ["保留"]
        self.lib.convs[fname]["starred"] = True
        self.lib.save()

        path = self.lib.path(fname)
        keep = os.path.join(self.root, "missing-source.json")
        shutil.copy2(path, keep)
        os.remove(path)
        self.lib.sync()
        self.assertIn(fname, self.lib.missing)

        result = self.lib.import_paths([keep])
        self.assertEqual(result.added, [])
        self.assertEqual(len(result.restored), 1)
        new_name = result.restored[0]
        self.assertIn(new_name, self.lib.convs)
        self.assertEqual(self.lib.convs[new_name]["tags"], ["保留"])
        self.assertTrue(self.lib.convs[new_name]["starred"])
        self.assertEqual(self.lib.missing, {})

    def test_atomic_backup_recovery(self):
        fname = self.add_conversation()
        self.lib.save()  # 生成一份有效备份
        self.assertTrue(os.path.isfile(self.lib.file + ".bak"))

        with open(self.lib.file, "w", encoding="utf-8") as f:
            f.write("{ 坏掉的 library ")

        recovered = core.Library(self.root).load()
        self.assertTrue(recovered.recovered_from_backup)
        self.assertIn(fname, recovered.convs)
        self.assertEqual(recovered.convs[fname]["count"], 3)
        # 损坏副本被保留下来
        corrupt = [n for n in os.listdir(self.root) if ".corrupt-" in n]
        self.assertTrue(corrupt)
        # 主文件被修复，备份仍是有效 JSON
        self.assertEqual(core.load_json(recovered.file)["conversations"][fname]["count"], 3)
        core.load_json(recovered.file + ".bak")

    # --- 回收站 ---

    def test_trash_restore_and_purge(self):
        fname = self.add_conversation()
        self.lib.convs[fname]["tags"] = ["保留"]
        self.lib.convs[fname]["starred"] = True
        self.lib.save()

        trash_name = self.lib.remove(fname)
        self.assertFalse(os.path.exists(self.lib.path(fname)))
        self.assertTrue(os.path.exists(os.path.join(self.lib.trash_dir, trash_name)))
        self.assertEqual(len(self.lib.trash_items()), 1)
        self.assertNotIn(fname, self.lib.convs)

        restored = self.lib.restore(trash_name)
        self.assertTrue(os.path.exists(self.lib.path(restored)))
        self.assertEqual(self.lib.convs[restored]["tags"], ["保留"])
        self.assertTrue(self.lib.convs[restored]["starred"])
        self.assertEqual(self.lib.trash_items(), [])

        trash_name = self.lib.remove(restored)
        self.assertTrue(self.lib.purge(trash_name))
        self.assertFalse(os.path.exists(os.path.join(self.lib.trash_dir, trash_name)))
        self.assertEqual(self.lib.trash_items(), [])

    def test_empty_trash(self):
        a = self.add_conversation("a.json", "A", 1)
        b = self.add_conversation("b.json", "B", 1)
        self.lib.remove(a)
        self.lib.remove(b)
        self.assertEqual(len(self.lib.trash_items()), 2)
        self.assertEqual(self.lib.empty_trash(), 2)
        self.assertEqual(self.lib.trash_items(), [])
        self.assertFalse(os.path.exists(os.path.join(self.lib.trash_dir, a)))

    # --- 搜索 ---

    def test_search_roles_case_and_scope(self):
        a = self.add_conversation("a.json", "Alpha 记忆", 3)
        b = self.add_conversation("b.json", "Beta 记忆", 2)

        default = core.search_library(self.lib, "记忆")
        self.assertEqual(len(default.rows), 5)  # 5 条问答，用户角色
        self.assertTrue(all(hit.role == "user" for hit in default.rows))

        all_roles = core.search_library(self.lib, "思考", roles=("thinking",))
        self.assertEqual(len(all_roles.rows), 5)

        scoped = core.search_library(self.lib, "记忆", fname=b)
        self.assertEqual(len(scoped.rows), 2)
        self.assertTrue(all(hit.fname == b for hit in scoped.rows))

        self.assertEqual(core.search_library(self.lib, "alpha").total_rows, 3)
        self.assertEqual(
            core.search_library(self.lib, "alpha", case_sensitive=True).total_rows, 0)
        self.assertEqual(
            core.search_library(self.lib, "Alpha", case_sensitive=True).total_rows, 3)
        self.assertEqual(
            core.search_library(self.lib, "记忆", roles="user").total_rows, 5)

    def test_search_regex_snippet_and_truncation(self):
        self.add_conversation(count=4)
        result = core.search_library(self.lib, r"问题\d", roles=("user",),
                                     use_regex=True, max_rows=2)
        self.assertEqual(len(result.rows), 2)
        self.assertTrue(result.truncated)
        self.assertIn("问题", result.rows[0].match_text)
        self.assertIn("记忆", result.rows[0].snippet)

        with self.assertRaises(ValueError):
            core.search_library(self.lib, "([", use_regex=True)
        with self.assertRaises(ValueError):
            core.search_library(self.lib, "")

    # --- 合并与导出 ---

    def test_merge_markdown_and_html(self):
        a = self.add_conversation("a.json", "第一段 <script>alert(1)</script>", 2)
        b = self.add_conversation("b.json", "第二段", 1)
        merged = core.merge_conversations(self.lib, [b, a])
        self.assertEqual(len(merged["qa_pairs"]), 3)
        self.assertEqual([p["index"] for p in merged["qa_pairs"]], [1, 2, 3])
        self.assertEqual(merged["qa_pairs"][0]["source_title"], "第二段")
        self.assertEqual(merged["qa_pairs"][1]["source_title"],
                         "第一段 <script>alert(1)</script>")

        md = core.to_markdown(self.lib.read_conversation(a))
        self.assertIn("# 第一段", md)
        self.assertIn("<details>", md)

        page = core.to_html([self.lib.read_conversation(a)], title="标题 <x>")
        self.assertIn("&lt;x&gt;", page)
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", page)
        self.assertIn("夜间模式", page)
        self.assertIn("toggle-think", page)
        self.assertNotIn("<h2>", page)  # 单对话不再重复大标题

        multi = core.to_html([self.lib.read_conversation(a),
                              self.lib.read_conversation(b)])
        self.assertEqual(multi.count("<h2>"), 2)
        self.assertIn('class="toc"', multi)

    # --- 体检 ---

    def test_validate_library(self):
        a = self.add_conversation("a.json", "A", 2)
        self.assertTrue(core.validate_library(self.lib)["ok"])

        # 手工复制一份，制造重复内容
        shutil.copy2(self.lib.path(a), self.lib.path("copy.json"))
        self.lib.sync()
        report = core.validate_library(self.lib)
        self.assertTrue(report["ok"])
        self.assertTrue(any("相同" in i["message"] for i in report["issues"]))

        # 删除文件但保留元数据，制造错误
        self.lib.convs["missing.json"] = dict(self.lib.convs[a], title="缺失")
        report = core.validate_library(self.lib)
        self.assertFalse(report["ok"])
        self.assertGreaterEqual(report["errors"], 1)

    # --- 设置 ---

    def test_settings_roundtrip(self):
        settings = core.Settings(self.root)
        settings.set("theme", "dark")
        settings.set("last_qa", 7)
        settings.save()
        loaded = core.Settings(self.root).load()
        self.assertEqual(loaded["theme"], "dark")
        self.assertEqual(loaded["last_qa"], 7)


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="mm-cli-")
        self.root = self.tmp.name
        lib = core.Library(self.root).load()
        source = os.path.join(self.root, "conv.json")
        write_json(source, make_conversation("命令行测试", 2))
        lib.import_paths([source])
        self.source = source

    def tearDown(self):
        self.tmp.cleanup()

    def _main(self, argv):
        import io
        from contextlib import redirect_stdout, redirect_stderr
        import memory_manager

        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = memory_manager.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_list_stats_search_json(self):
        code, out, _ = self._main(["--root", self.root, "--list", "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["conversations"][0]["title"], "命令行测试")

        code, out, _ = self._main(["--root", self.root, "--stats"])
        self.assertEqual(code, 0)
        self.assertIn("命令行测试", out)

        code, out, _ = self._main([
            "--root", self.root, "--search", "记忆", "--role", "all", "--json"])
        self.assertEqual(code, 0)
        result = json.loads(out)
        self.assertEqual(result["total_rows"], 2)

    def test_check_exit_code(self):
        code, out, _ = self._main(["--root", self.root, "--check"])
        self.assertEqual(code, 0, out)
        self.assertIn("未发现问题", out)

    def test_export_markdown_and_html(self):
        md = os.path.join(self.root, "out.md")
        html = os.path.join(self.root, "out.html")
        code, _, err = self._main(["--root", self.root, "--export-md", md])
        self.assertEqual(code, 0, err)
        self.assertTrue(os.path.isfile(md))
        with open(md, encoding="utf-8") as handle:
            self.assertIn("命令行测试", handle.read())

        code, _, err = self._main(["--root", self.root, "--export-html", html])
        self.assertEqual(code, 0, err)
        with open(html, encoding="utf-8") as handle:
            content = handle.read()
        self.assertIn("<!DOCTYPE html>", content)
        self.assertIn("命令行测试", content)

    def test_import_command_reports_duplicates(self):
        code, out, err = self._main([
            "--root", self.root, "--import", self.source, "--json"])
        self.assertEqual(code, 0, err)
        report = json.loads(out)
        self.assertEqual(report["added"], [])
        self.assertEqual(len(report["duplicates"]), 1)

        fresh = os.path.join(self.root, "fresh-import.json")
        try:
            write_json(fresh, make_conversation("新导入", 1))
            code, out, err = self._main([
                "--root", self.root, "--import", fresh, "--json"])
            self.assertEqual(code, 0, err)
            self.assertEqual(len(json.loads(out)["added"]), 1)
        finally:
            if os.path.exists(fresh):
                os.remove(fresh)


if __name__ == "__main__":
    unittest.main()
