# Tomato Vocast（Wordcast）

**把 Markdown 词表合成一条英音长 MP3** — 适合拖地、洗碗、通勤、散步时被动听词。

[English README](README.md)

![Wordcast 网页界面 — 粘贴 Markdown 词表、选择英式音色、生成一条 MP3](image.png)

## 这是什么

Tomato Vocast 从 Markdown 里读取列表项（词条或短语），用 [Microsoft Edge TTS](https://github.com/rany2/edge-tts) 的英式神经网络音色逐条朗读，再合并成一条 MP3，词条之间可设置静音间隔。

适合：拼写词表、GRE/托福词汇、课本短语、任何你想反复听、又不想一条条自己录的短列表。

## 功能

- **Markdown 进，MP3 出** — 粘贴或编写列表，得到一条连续音频
- **英式英语音色** — Sonia、Ryan 等 `en-GB` 神经网络声音
- **可调间隔** — 每条朗读后的静音（默认 700 ms），方便先在心里拼写再听下一条
- **命令行 + 网页** — 脚本可自动化，浏览器界面适合快速试效果
- **本地运行** — 在你自己的电脑上跑，无需账号或 API Key（Edge TTS 使用微软公开端点）

## 环境要求

- **Python 3.10+**
- **[ffmpeg](https://ffmpeg.org/)** 已加入 `PATH`（合并片段为一条 MP3 时需要）
  - macOS：`brew install ffmpeg`
  - Ubuntu/Debian：`sudo apt install ffmpeg`
  - Windows：从 [ffmpeg.org](https://ffmpeg.org/download.html) 安装并加入 PATH

## 安装

```bash
git clone https://github.com/uvoooooo/tomato-vocast.git
cd tomato-vocast

python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

## Markdown 格式

只会朗读**列表行**。标题、空行、HTML 注释会被跳过。

支持的写法：

```markdown
# 第三周 — 家务听词

- serendipity
- ephemeral
- ubiquitous
- **pragmatic**

1. juxtaposition
2. dichotomy

<!-- 注释不会念 -->
```

- 无序列表：`-`、`*` 或 `+`
- 有序列表：`1.` 或 `1)`
- 行内 Markdown（`**粗体**`、`*斜体*`、`` `代码` ``）会去掉标记，只读纯文本
- 重复行（不区分大小写）会自动去重

示例文件见 [`example-words.md`](example-words.md)。

## 使用方法

### 网页界面（推荐先试）

在仓库根目录执行：

```bash
uvicorn server:app --reload --host 127.0.0.1 --port 8765
```

浏览器打开 [http://127.0.0.1:8765/](http://127.0.0.1:8765/)。若端口被占用，可换端口，例如 `--port 8766`。

1. 在左侧编辑词表
2. 选择英式音色和词条后静音时长
3. 点击 **生成长音频**
4. 在页面试听或下载 `vocast.mp3`

### 命令行

```bash
python wordcast.py example-words.md -o listen.mp3
```

参数：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `-o`, `--output` | *(必填)* | 输出 `.mp3` 路径 |
| `--voice` | `en-GB-SoniaNeural` | Edge TTS 音色 ID |
| `--pause-ms` | `700` | 每条朗读后的静音毫秒数 |

示例：

```bash
python wordcast.py words.md -o out.mp3 --voice en-GB-RyanNeural --pause-ms 900
```

## 工作原理

1. **解析** — 从 Markdown 列表项提取词条
2. **合成** — 对每条调用 Edge TTS（请求间有短暂间隔）
3. **合并** — ffmpeg 为每段加静音并拼接成一条 MP3

网页服务（`server.py`）提供：

- `GET /api/voices` — 列出可用的英式神经网络音色
- `POST /api/render` — JSON `{ "markdown", "voice", "pause_ms" }` → 返回 MP3

## 目录结构

```
tomato-vocast/
├── wordcast.py       # 核心逻辑 + 命令行
├── server.py         # FastAPI 服务 + 静态网页
├── web/index.html    # 浏览器界面
├── example-words.md  # 示例词表
└── requirements.txt
```

## 常见问题

| 现象 | 处理 |
|------|------|
| `ffmpeg not found on PATH` | 安装 ffmpeg 并确认终端能执行 `ffmpeg` |
| `No list items found` | 使用 `- 词条` 或 `1. 词条`；仅有标题不会被朗读 |
| 网页音色列表加载失败 | 检查能否访问 Edge TTS；界面会回退到 `en-GB-SoniaNeural` |
| 端口被占用 | 换 `--port` 启动 uvicorn |
