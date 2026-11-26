# 剪辑工具:ChatCut(配置.剪辑工具 = ChatCut)

> 来源:旧项目 chatcut-clipper 技能的实测做法(2026-11),整理为与本项目数据库配合的版本。
> 前提:ChatCut 桌面版已安装并登录;驱动 AI 能调用 ChatCut 的工具接口(Claude Code 里叫 `chatcut_desktop`)。
> 其他 AI:只要能调用同一套 ChatCut 工具接口即可;不能调用时改用 `剪辑_ffmpeg.md`。

## 接入驱动 AI(部署时做一次)
ChatCut 安装后自带工具接口程序:`~/Library/Application Support/ChatCut/chatcut-mcp`(先确认这个文件存在;不存在说明 ChatCut 没装好或没打开过,让用户打开一次 ChatCut 并登录)。
- Claude Code:`claude mcp add -s user chatcut_desktop -e CHATCUT_MCP_CLIENT=claude_code -- "$HOME/Library/Application Support/ChatCut/chatcut-mcp"`
- Codex:`codex mcp add chatcut_desktop --env CHATCUT_MCP_CLIENT=codex_app -- "$HOME/Library/Application Support/ChatCut/chatcut-mcp"`
- Cursor CLI:`python3 3-工具/脚本/connect_chatcut.py cursor`(写入 `~/.cursor/mcp.json`)
- Pi:`python3 3-工具/脚本/connect_chatcut.py pi`(写入 `~/.pi/agent/mcp.json`)
- 已接入的不要重复添加;`python3 3-工具/check_env.py` 会显示是否已接入。

## 费用红线(最重要)
- **只用剪辑、字幕、导出类工具。** 禁止:`submit_video`、`submit_image`、`submit_music`、`submit_sound`、`submit_voice`、`submit_avatar_video`、`submit_lipsync`、`submit_video_remake`、`submit_generation_batch`、`video_translation`,以及 ChatCut 内置 AI 对话。
- 禁止:`delete_project`、`restore_project`、`upload_project_diagnostics`。
- 每批开始前、结束后各调用一次 `read_billing`;余额变少 → 立即停止,该条标需人工。

## 步骤(每条切片)
1. 工程:每场素材一个 ChatCut 工程,名称固定为「SOP <素材ID>」(如「SOP 课-20261123」)。先 `list_projects` 找同名工程,有就复用,没有就 `create_project` 新建。
   **不要复用其他名字的工程**(那可能是用户自己的工程,或旧版本留下的)。记下项目 ID,登记 `update clip <ID> 剪辑工程=<项目ID>`。
2. `push_asset` 推入截好的片段(环节 2 第 3 步的 excerpts 文件)。推入后会自动转写;用 `track_progress` 等转写完成。
3. 把 `3-工具/模板/{packaging,quote,sub_caption}.jsx` 复制进项目工作区,按 `*.props.json` 的属性推入两个动效:标题栏、金句卡。
   复用工程时先 `inspect_asset includeCode=true` 看标题栏、金句卡能不能读到代码;报"找不到文件"(项目挪过位置)就用 `edit_asset` 把路径改到当前项目的 `3-工具/模板/<同名>.jsx`。
4. `manage_timelines` 新建时间线,名称 `<切片ID> <短标题>`。**必须先把画布设为 1080×1920、30fps**(默认"跟随第一个画面"会变横屏)。
5. 精剪:`read_script` → 在文稿里用 `~~删除~~` 标记删掉的内容,钩子句提到最前 → `apply_script`。可先用 `clean_script` 做口水词初筛。
6. 版式:
   - 视频窗口:left -54 / top 600 / 1188×668。
   - V2 标题栏铺满全片:title 两行,【】标重点词;english 全大写一句。不放期号、日期。
   - V3 金句卡 4–6 张,每张约 3–4 秒,属性 lead / main(两行,【】重点词);第 0 帧放一张当钩子,最后一张"划重点"。
   - 字幕:`edit_captions` 开启 → 套用 sub_caption 模板,单行 ≤15 字;轨道布局 {left 60, top 1660, width 960, height 100}。
7. 校字幕:`read_captions` 逐卡看,错字用 `edit_captions` 改(要带 revision)。
8. 自检:`preview_timeline` 取 6 帧,确认标题栏、视频、金句卡、字幕不遮挡、不出框。
9. 导出:
   - 视频:`export` format=video, resolution=1080p, fps=30, videoProfile=sdr_h264, timelineId=<id>,输出到临时文件 `raw.mp4`;`track_progress target=export action=wait` 等完成。
   - 字幕:`export` format=subtitles, subtitleFormat=srt,直接输出到成片文件夹,然后 `chmod 644`(导出权限是 600)。
   - 写编号(不重编码):`ffmpeg -i raw.mp4 -map 0 -c copy -movflags +faststart -metadata comment="<切片ID>" -metadata title="<短标题>" <成片路径>`
   - 校验:`ffprobe -v error -show_entries format=duration:format_tags=comment -show_entries stream=width,height,codec_name <成片>`,应为 1080×1920、h264+aac、comment=切片ID。
10. 回到环节 2 第 7 步登记。

## 已知坑
- 新时间线默认可能是横屏,第 4 步必须先改画布。
- 动效模板在工程里记的是绝对路径;项目文件夹挪了位置,复用旧工程时要按第 3 步修路径(2026-11-24 试跑出现)。
- 导出的字幕文件权限是 600,要改 644。
- **标题栏英文副标题不要超过约 28 个字符**,否则左右出框(2026-11-23 试跑出现)。自检抽帧时专门看这一行。
- 精剪后时长可能低于 60 秒,要回补句子再导出(试跑第一版 48 秒)。
- 结尾必须落在完整的金句上,不要留"第二个干嘛?"这类话说一半的句子。
- 无人值守时:Claude Code 用 `3-工具/脚本/run_claude.sh`、Codex 用 `3-工具/脚本/run_codex.sh`、Cursor CLI 用 `run_cursor.sh`、Pi 用 `run_pi.sh` 启动;都会开放 ChatCut 工作区目录。Claude Code 权限规则里的用户主目录绝对路径要写成 `//Users/<你的用户名>/...`(双斜杠前缀)。
