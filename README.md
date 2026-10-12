# AI 记忆储存和管理器

本地管理 AI 对话记录（JSON 格式）的图形界面工具。纯 Python 标准库实现，**零第三方依赖**。

## 功能

- **导入**：单个文件或整个文件夹批量导入，自动复制进 `conversations/` 库目录统一管理，原文件不动；首次启动自动扫描同目录下的对话 JSON
- **浏览**：对话列表 → 问答列表 → 详情三级浏览；用户 / 思考过程 / AI 回答三块独立卡片，思考过程可点击标题条折叠
- **全文搜索**：跨所有对话搜索用户提问、AI 回答、思考过程，双击结果直接跳转定位并高亮关键词
- **管理**：星标收藏、自定义标签（多标签 + 按标签筛选）、重命名、删除（移入 `trash/` 回收站，不销毁文件）
- **合并导出 JSON**：勾选多个对话合并成一个大文件，`qa_pairs` 拼接、index 重编号、每条带 `source_title` 标注来源，格式与原文件兼容
- **导出 Markdown**：单选或多选导出，思考过程转为 `<details>` 折叠块
- **统计**：对话数、问答总数、正文字数、思考总时长、单对话明细

## 使用

```bash
python memory_manager.py
```

要求 Python 3.8+（仅标准库，无需安装任何依赖）。

## 对话 JSON 格式

```json
{
  "conversation_title": "对话标题",
  "exported_at": "2026-10-03 19:44:54",
  "source_url": "https://...",
  "source_type": "history_messages",
  "qa_pairs": [
    {
      "index": 1,
      "question": "用户提问",
      "thinking_seconds": "12.45秒",
      "thinking": "AI 思考过程",
      "deepseek": "AI 回答",
      "references": []
    }
  ]
}
```

字段名做了兼容处理：回答识别 `deepseek / answer / ai / response`，思考识别 `thinking / think / reasoning`，适配不同导出脚本。

## 数据存放

| 路径 | 说明 |
|------|------|
| `conversations/` | 对话库（导入的文件都复制到这里） |
| `library.json` | 库元数据（星标、标签、显示标题） |
| `trash/` | 删除的对话移入此处，不会销毁 |

## License

MIT
