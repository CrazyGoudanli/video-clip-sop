# 剪辑工具:Remotion(配置.剪辑工具 = Remotion,两段式动效包装)

> 适用:需要比纯 ffmpeg 静态叠字更高级的竖屏动效包装（流光动态标题栏、弹簧玻璃态金句卡、逐字高亮卡拉OK字幕、底部留存进度条），完全开源免费、本地无头渲染。
> 架构:第一段仍用 `ffmpeg` 完成极速口播精剪（去口水词/死停/音量归一），第二段交给 `3-工具/渲染引擎/remotion-studio/` 用 React 动画合成最终 1080×1920 30fps 成片。

## 环境前置
- Node.js 20+、`ffmpeg`、`ffprobe`、本机 Chrome（优先自动复用 `/Applications/Google Chrome.app`）。
- 首次安装依赖:`npm --prefix 3-工具/渲染引擎/remotion-studio install`

## 步骤
1. **口播精剪（ffmpeg）**:按转写结果确定保留句段区间 `[[s1,e1],[s2,e2],...]`（钩子句放第一段），用 `ffmpeg` 裁剪拼接并做音量归一（`loudnorm`），输出干净的 `cut.mp4`（保持原 16:9 画面，不要烧静态文字），同时生成校对后的 `.srt` 字幕。
2. **生成包装参数 `packaging.json`**（放在 `工作区/<素材ID>/剪辑/<序号>/packaging.json`）:
   ```json
   {
     "clipId": "课-20261127-01",
     "style": "obsidian-gold",
     "badgeText": "核心干货",
     "titleLine1": "写不出AI视频剧本？",
     "titleLine2": "先别想【宏大故事】",
     "subtitleEn": "START WITH A CORE VALUE",
     "quoteCards": [
       {"startSec": 0.0, "endSec": 3.6, "tag": "换个起点", "line1": "好故事可以先从", "line2": "【一个词】开始", "accent": "gold"},
       {"startSec": 61.5, "endSec": 66.8, "tag": "划重点", "line1": "好故事的起点", "line2": "先找【核心价值观】", "accent": "gold"}
     ],
     "subtitles": [
       {"startSec": 0.0, "endSec": 2.7, "text": "它甚至只需要从一个词开始", "highlight": "一个词"}
     ]
   }
   ```
   - `style` 支持 3 套内置主题:`obsidian-gold`（黑金流光，默认）、`cyber-cyan`（赛博科技蓝）、`editorial-warm`（暖橘杂志风）。
   - `titleLine1` / `titleLine2` / `quoteCards` 均支持用 `【】` 标出金色/主题高亮关键词，严禁出现期号与日期。
   - `quoteCards` 共 4–6 张（第 0 秒钩子卡 + 结尾固定「划重点」），每张 3–4.5 秒。
   - `subtitles` 单行 ≤15 字，可选填 `highlight` 词做重点色强调。
3. **一键渲染成片 + 自动抽 6 帧自检图**:
   ```zsh
   node 3-工具/脚本/render_remotion.mjs \
     --video 工作区/<素材ID>/剪辑/<序号>/cut.mp4 \
     --props 工作区/<素材ID>/剪辑/<序号>/packaging.json \
     --out 成片/<切片ID>_<短标题>/<切片ID>_<短标题>.mp4 \
     --clip-id <切片ID> \
     --frames-out 工作区/<素材ID>/剪辑/<序号>/六帧自检_remotion.png
   ```
4. **验收与登记**:
   - 查看生成的 `六帧自检_remotion.png`，核对标题栏、16:9 画面、金句卡、底部字幕无重叠、无越界、无黑帧；
   - `ffprobe` 核对规格（1080×1920、30fps、有音轨、时长 60–90s）；
   - 回到 `3-工具/环节/2-剪辑.md` 第 7 步用 `db.py` 登记 `剪辑工具=Remotion` 并提交看片。
