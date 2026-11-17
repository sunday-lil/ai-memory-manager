# AI 记忆储存和管理器

把 AI 对话导出文件（JSON）整理成一个可长期保存、可检索、可导出的**本地记忆库**。

纯 Python 标准库实现，零第三方依赖；所有数据都在自己的电脑上，不联网、不上传。

```bash
python memory_manager.py
```

![Python](https://img.shields.io/badge/Python-3.8%2B-blue)
![Dependencies](https://img.shields.io/badge/dependencies-0-brightgreen)
![License](https://img.shields.io/badge/license-MIT-green)

## 功能

### 浏览与阅读

- 对话 → 问答 → 详情三级浏览，打开对话自动定位到上次读到的位置
- 用户提问、思考过程、AI 回答三张独立卡片；点击思考标题条即可折叠
- 问答列表支持按问题内容过滤，长对话也能快速定位
- 上一条 / 下一条按钮，`J` / `K`、`Alt+←/→` 键盘切换
- 字号缩放（80%–160%）与夜间模式，窗口大小、分栏位置、主题都会记住
- 每条问答可一键复制，搜索结果可双击跳转并高亮关键词

### 搜索

- 跨全部对话搜索用户提问、思考过程、AI 回答
- 按角色筛选、限定某个对话、区分大小写、正则表达式
- 边输边搜（约 300ms 防抖），首次搜索 4MB 记忆库也在百毫秒级
- 结果按“对话 / 问答序号 / 角色 / 命中次数 / 片段”展示，可导出为 Markdown

### 管理与整理

- 星标收藏、自定义标签（多标签 + 标签筛选）、标题筛选、按日期/标题/问答数排序
- 批量勾选对话，用于合并导出
- 重命名只影响显示标题，不改原始文件
- 删除移入 `trash/` 回收站，**可还原**星标、标签和标题；也可彻底删除或清空
- 导入文件夹时递归扫描子目录；按内容 SHA-1 去重，不会重复产生 `_1` 副本
- 支持 DeepSeek 新版聊天备份 v3：按 session + 首个用户请求自动分对话，合并重试与重新生成分支，保真还原思考耗时、搜索引用和附件名

### 导出

| 格式 | 说明 |
|------|------|
| 合并 JSON | 勾选多个对话，`qa_pairs` 拼接、index 重编号、每条带 `source_title`，与原格式兼容 |
| Markdown | 思考过程转为 `<details>` 折叠块，适合放进笔记软件 |
| 单文件 HTML | 不需要服务器，双击离线阅读；响应式布局、夜间模式、折叠全部思考、可打印 |

### 数据安全

- **原子写入**：`library.json` 先写临时文件再 `os.replace`，断电不会留下半截 JSON
- **自动备份**：每次保存前生成 `library.json.bak`；主文件损坏时自动从备份恢复，并保留 `*.corrupt-*` 副本
- **回收站**：删除不是销毁，文件与元数据一起保存在 `trash/`
- **外部修改感知**：按文件 mtime + 大小刷新元数据；手动替换文件后按 `F5` 即可
- **缺失文件不丢元数据**：`conversations/` 中的文件被移走或误删时，标题、标签、星标会保留在 `library.json` 的 `missing` 段；把原文件放回后按 `F5`（或重新导入）即可接回，不会被当成新对话
- **去重导入**：内容哈希相同不会重复入库
- **库体检**：检查坏 JSON、缺文件、空问答、重复内容

## 使用

要求 Python 3.8+（Windows 自带的 Tk 即可，无需安装任何依赖）。

```bash
# 图形界面
python memory_manager.py

# 指定另一个数据目录（便携模式）
python memory_manager.py --root D:\我的记忆库

# 不弹控制台窗口（Windows）
pythonw memory_manager.py
```

首次启动时，如果当前目录有对话 JSON，会自动导入；之后导入的文件会复制到 `conversations/` 统一管理，原文件不动。

### DeepSeek 新版聊天备份（v3）

新版备份目录通常长这样：

```text
聊天备份/
├── manifest.json                 {"export_format_version": 3}
├── chat_session_index.json       每个 session 的 id / 标题 / 消息数
├── chat_sessions/<uuid>.json     每个 session 的完整消息树
└── chat_sessions/<uuid>_files/   图片、附件（本程序不复制，只保留文件名引用）
```

- 图形界面：`导入 → 导入文件夹`，直接选 `聊天备份/` 即可；程序会自动识别 v3 格式。
- 命令行：`python memory_manager.py --import .\聊天备份`
- 自动分对话：先按 session 分组，再比较首个用户请求；同一请求的重试 root 合并，不同请求拆成多条对话。每条对话选消息量最大的 root，再取其中最长的一条分支，还原成线性问答；index 标题优先给主对话，其余对话从首条请求提取标题。
- 保留内容：用户提问、AI 回答、思考过程与耗时、搜索引用、附件文件名；`CONTENT_RISK`、`TIP` 这类界面提示会被忽略。
- 标题优先使用备份里的 session 标题；标题为空时从首条用户请求自动提取。
- `user.json` 里的邮箱、手机号等账号信息**不会**被读取，也不会导入。
- 单个 `chat_sessions/<uuid>.json` 也可以直接在「导入文件」里多选导入。

## 命令行

不带参数启动图形界面；带参数则作为命令行工具使用，便于备份、检索和脚本化。

```bash
# 列出 / 统计 / 体检
python memory_manager.py --list
python memory_manager.py --stats
python memory_manager.py --check

# 搜索（默认搜索用户与 AI；--role all 包含思考过程）
python memory_manager.py --search "服务器"
python memory_manager.py --search "记忆" --role all --case
python memory_manager.py --search "记忆|存档" --regex
python memory_manager.py --search "服务器" --scope 赛博记忆存档
python memory_manager.py --search "服务器" --json

# 导出全部（可用 --only 反复筛选标题/文件名）
python memory_manager.py --export-md 记忆存档.md
python memory_manager.py --export-html 记忆存档.html
python memory_manager.py --export-html 精选.html --only 赛博 --only 危机

# 导入文件、普通文件夹，或 DeepSeek v3 聊天备份
python memory_manager.py --import .\导出文件
python memory_manager.py --import .\聊天备份
```

`--check` 发现错误时返回退出码 1，方便放进备份脚本；警告不影响退出码。

更多参数见 `python memory_manager.py --help`。

## 快捷键

| 快捷键 | 功能 |
|--------|------|
| `Ctrl+F` | 全文搜索 |
| `F5` | 刷新对话库（感知外部文件变化） |
| `Ctrl+O` | 导入文件 |
| `Alt+←` / `Alt+→` | 上一条 / 下一条问答 |
| `J` / `K` | 下一条 / 上一条（问答列表聚焦时） |
| `Ctrl+=` / `Ctrl+-` | 放大 / 缩小字号 |
| `Ctrl+0` | 重置字号 |
| `Ctrl+Shift+C` | 复制当前问答 |
| `Esc` | 关闭搜索窗口 |

## 数据目录

| 路径 | 说明 |
|------|------|
| `conversations/` | 对话库（导入的文件都复制到这里） |
| `library.json` | 库元数据（标题、星标、标签、内容哈希、修改时间；文件缺失时还包含 `missing` 段） |
| `library.json.bak` | 上一次保存的元数据备份，损坏时自动使用 |
| `trash/` | 回收站文件 |
| `trash/trash_index.json` | 回收站索引（还原时恢复星标/标签/标题） |
| `settings.json` | 窗口位置、分栏、主题、字号、上次阅读位置 |

这些文件都属于个人数据，已在 `.gitignore` 中排除，不会被提交。

### 文件缺失 / 误删

如果 `conversations/` 里的 JSON 被外部移走或误删：

1. 元数据（标题、标签、星标）仍保留在 `library.json` 的 `missing` 段，不会丢；上次阅读位置在 `settings.json` 中单独保留。
2. 把原文件放回 `conversations/`，按 `F5`；或通过「导入」重新导入同一个文件，程序会按 SHA-1 接回原元数据。
3. 界面状态栏和「库体检」会显示缺失数量，不会静默忽略。

系统级备份（Windows 卷影副本、文件历史、回收站）仍然值得开启；本程序只保证自己的元数据不被半截写入或误删。

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

字段名做了兼容处理：回答识别 `deepseek / answer / ai / response`，思考识别 `thinking / think / reasoning`，提问识别 `question / user / q`，因此不同导出脚本的文件都能导入。

## 项目结构

```text
memory_core.py         数据核心：库、回收站、同步、搜索、统计、Markdown/HTML 导出（无 GUI 依赖）
memory_backup_v3.py    DeepSeek v3 聊天备份解析：消息树 -> 自动分对话 -> 旧版 conversation
memory_gui.py          tkinter 界面：列表、详情、搜索窗口、回收站、统计、主题
memory_manager.py      入口：默认启动 GUI，也提供命令行
tests/                 单元测试与 GUI 冒烟测试
```

```bash
python -m unittest discover -s tests -v
```

## 版本

- **v1.2.0**：支持 DeepSeek 新版聊天备份 v3；按 session + 首个用户请求自动分对话，合并重试 root/重新生成分支，还原提问、回答、思考耗时、引用与附件名；文件夹导入自动识别，单个 session 文件也可导入
- **v1.1.1**：文件缺失时保留元数据（`library.json` 的 `missing` 段），放回文件或重新导入后自动接回；窗口位置自动限制在当前屏幕内，换显示器不会跑到屏幕外；统计/体检/命令行显示缺失数量
- **v1.1.0**：全文搜索重做（角色/范围/正则/实时）、回收站可视化还原、单文件 HTML 导出、命令行工具、原子写入与自动备份、导入去重、库体检、问答筛选、夜间模式、字号缩放、窗口状态记忆、修复列表滚动条被挤成小条的问题
- **v1.0.0**：导入、浏览、搜索、标签、星标、合并导出、Markdown 导出、统计

## License

MIT
