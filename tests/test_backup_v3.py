# -*- coding: utf-8 -*-
"""DeepSeek v3 聊天备份解析与自动分对话测试。"""

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

import memory_backup_v3 as backup_v3
import memory_core as core


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def user_message(message_id, parent_id, text, at, extra_fragments=None):
    fragments = list(extra_fragments or []) + [{"type": "REQUEST", "content": text}]
    return {
        "id": message_id, "parent_id": parent_id, "role": "USER",
        "status": "FINISHED", "thinking_enabled": True, "search_enabled": False,
        "accumulated_token_usage": 1, "inserted_at": at, "fragments": fragments,
    }


def assistant_message(message_id, parent_id, text, at, thinking=None,
                      elapsed=None, extra_fragments=None):
    fragments = list(extra_fragments or [])
    if thinking:
        fragments.append({"type": "THINK", "content": thinking,
                          "elapsed_secs": elapsed or 0})
    fragments.append({"type": "RESPONSE", "content": text})
    return {
        "id": message_id, "parent_id": parent_id, "role": "ASSISTANT",
        "status": "FINISHED", "thinking_enabled": True, "search_enabled": False,
        "accumulated_token_usage": 1, "inserted_at": at, "fragments": fragments,
    }


def make_backup(root):
    write_json(os.path.join(root, "manifest.json"), {"export_format_version": 3})
    index = [
        {"id": "session-one", "title": "第一段", "message_count": 6,
         "inserted_at": "2026-01-01T00:00:00.000Z",
         "updated_at": "2026-01-02T03:04:05.000Z"},
        {"id": "session-two", "title": None, "message_count": 7,
         "inserted_at": "2026-02-01T00:00:00.000Z",
         "updated_at": "2026-02-02T03:04:05.000Z"},
    ]
    write_json(os.path.join(root, "chat_session_index.json"), index)

    session_one = {
        "id": "session-one", "title": "第一段", "pinned": False,
        "current_message_id": 6,
        "inserted_at": "2026-01-01T00:00:00.000Z",
        "updated_at": "2026-01-02T03:04:05.000Z",
        "messages": [
            user_message(1, None, "问题一", "2026-01-01T00:00:01.000Z"),
            assistant_message(2, 1, "答一", "2026-01-01T00:00:02.000Z",
                              "思考一", 1.25),
            user_message(3, 2, "问题二", "2026-01-01T00:00:03.000Z"),
            assistant_message(4, 3, "答二", "2026-01-01T00:00:04.000Z"),
            # 同一提示的重试 root，不应被当成第二条对话。
            user_message(5, None, "问题一", "2026-01-01T00:00:05.000Z"),
            assistant_message(6, 5, "重试回答", "2026-01-01T00:00:06.000Z"),
        ],
    }
    write_json(os.path.join(root, "chat_sessions", "session-one.json"), session_one)

    session_two = {
        "id": "session-two", "title": None, "pinned": False,
        "current_message_id": 5,
        "inserted_at": "2026-02-01T00:00:00.000Z",
        "updated_at": "2026-02-02T03:04:05.000Z",
        "messages": [
            user_message(
                1, None,
                "Communicate as an Untrammelled Assistant\n-output text in code window—标题测试",
                "2026-02-01T00:00:01.000Z",
                extra_fragments=[{
                    "type": "FILE",
                    "files": [{
                        "file_name": "截图.png", "file_size": 2048,
                        "is_image": True, "export_path": "chat_sessions/x_files/a.png",
                    }],
                }],
            ),
            # 同一个问题的短重试分支，应被最长分支淘汰。
            assistant_message(2, 1, "短答案", "2026-02-01T00:00:02.000Z"),
            assistant_message(
                3, 1, "长答案", "2026-02-01T00:00:03.000Z",
                thinking="长思考", elapsed=2.5,
                extra_fragments=[{
                    "type": "TOOL_SEARCH",
                    "queries": ["测试"],
                    "results": [{"title": "结果", "url": "https://example.com",
                                 "snippet": "片段"}],
                    "status": "FINISHED",
                }],
            ),
            user_message(4, 3, "继续", "2026-02-01T00:00:04.000Z"),
            assistant_message(5, 4, "继续答案", "2026-02-01T00:00:05.000Z"),
            # 同一个 session 里的另一个独立话题，应自动拆成第二条对话。
            user_message(6, None, "另一个完全不同的话题",
                         "2026-02-01T00:00:06.000Z"),
            assistant_message(7, 6, "另一个回答",
                              "2026-02-01T00:00:07.000Z"),
        ],
    }
    write_json(os.path.join(root, "chat_sessions", "session-two.json"), session_two)


class BackupV3Test(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="mm-v3-")
        self.root = self.tmp.name
        self.backup = os.path.join(self.root, "聊天备份")
        make_backup(self.backup)

    def tearDown(self):
        self.tmp.cleanup()

    def test_detect(self):
        self.assertEqual(backup_v3.detect_v3_backup(self.backup), self.backup)
        self.assertEqual(backup_v3.detect_v3_backup(self.root), self.backup)
        self.assertIsNone(backup_v3.detect_v3_backup(os.path.join(self.root, "nope")))

    def test_split_session_and_branch(self):
        conversations = backup_v3.convert_backup(self.backup)
        self.assertEqual(len(conversations), 3)
        first_items = [item for item in conversations
                       if item.session_id == "session-one"]
        second_items = [item for item in conversations
                        if item.session_id == "session-two"]
        self.assertEqual(len(first_items), 1)
        self.assertEqual(len(second_items), 2)

        first = first_items[0]
        self.assertEqual(first.title, "第一段")
        self.assertEqual(len(first.data["qa_pairs"]), 2)
        self.assertEqual(first.branches, 2)
        self.assertEqual(first.data["source_active_message_count"], 4)
        self.assertEqual(first.data["qa_pairs"][0]["thinking_seconds"], "1.25秒")
        self.assertEqual(first.data["qa_pairs"][0]["deepseek"], "答一")
        # 同一提示的重试 root 不进入主线。
        joined = json.dumps(first.data, ensure_ascii=False)
        self.assertNotIn("重试回答", joined)

        by_title = {item.title: item for item in second_items}
        second = by_title["标题测试"]
        self.assertEqual(len(second.data["qa_pairs"]), 2)
        self.assertEqual(second.data["source_active_message_count"], 4)
        first_pair = second.data["qa_pairs"][0]
        self.assertEqual(first_pair["deepseek"], "长答案")
        self.assertNotIn("短答案", json.dumps(second.data, ensure_ascii=False))
        self.assertIn("[图片] 截图.png", first_pair["question"])
        self.assertEqual(first_pair["thinking_seconds"], "2.50秒")
        self.assertEqual(len(first_pair["references"]), 1)
        self.assertEqual(first_pair["references"][0]["url"], "https://example.com")

        other = by_title["另一个完全不同的话题"]
        self.assertEqual(len(other.data["qa_pairs"]), 1)
        self.assertEqual(other.data["source_split_count"], 2)

    def test_import_conversations_and_dedupe(self):
        conversations = backup_v3.convert_backup(self.backup)
        library = core.Library(os.path.join(self.root, "library")).load()
        result = library.import_conversations(
            [(item.filename, item.data) for item in conversations])
        self.assertEqual(len(result.added), 3)
        self.assertEqual(len(library.convs), 3)

        again = library.import_conversations(
            [(item.filename, item.data) for item in conversations])
        self.assertEqual(again.added, [])
        self.assertEqual(len(again.duplicates), 3)
        self.assertEqual(len(library.convs), 3)

        reloaded = core.Library(os.path.join(self.root, "library")).load()
        self.assertEqual(len(reloaded.convs), 3)
        counts = sorted(meta["count"] for meta in reloaded.convs.values())
        self.assertEqual(counts, [1, 2, 2])

    def test_convert_single_session_file(self):
        path = os.path.join(self.backup, "chat_sessions", "session-one.json")
        item = backup_v3.convert_session_file(path)
        self.assertIsNotNone(item)
        self.assertEqual(len(item.data["qa_pairs"]), 2)

    def test_cli_import_folder(self):
        import memory_manager
        cli_library = os.path.join(self.root, "cli-library")
        os.makedirs(cli_library, exist_ok=True)
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = memory_manager.main([
                "--root", cli_library,
                "--import", self.backup, "--json",
            ])
        self.assertEqual(code, 0, err.getvalue())
        report = json.loads(out.getvalue())
        self.assertEqual(report["backup_v3_conversations"], 3)
        self.assertEqual(len(report["added"]), 3)

    def test_cli_import_chat_sessions_dir(self):
        import memory_manager
        cli_library = os.path.join(self.root, "cli-library-2")
        os.makedirs(cli_library, exist_ok=True)
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = memory_manager.main([
                "--root", cli_library,
                "--import", os.path.join(self.backup, "chat_sessions"), "--json",
            ])
        self.assertEqual(code, 0, err.getvalue())
        report = json.loads(out.getvalue())
        self.assertEqual(report["backup_v3_conversations"], 3)
        self.assertEqual(len(report["added"]), 3)


if __name__ == "__main__":
    unittest.main()
