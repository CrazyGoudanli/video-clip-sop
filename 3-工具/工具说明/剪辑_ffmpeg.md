# 剪辑工具:ffmpeg(配置.剪辑工具 = ffmpeg,默认/后备)

> 适用:没有 ChatCut,或 ChatCut 不可用时。任何能运行命令行的 AI 都能用。
> 功能差异:没有标题栏、金句卡的动效,改为静态文字叠加;精剪靠字幕时间轴手动拼接。

## 步骤
1. 用转写结果(环节 1 的 transcript json)确定要保留的句子区间,写成列表(秒):`[[s1,e1],[s2,e2],...]`,钩子句放第一段。
2. 按区间切片并拼接(重编码,保证切点准确):
   ```
   ffmpeg -i <excerpt.mp4> -filter_complex "[0:v]trim=s1:e1,setpts=PTS-STARTPTS[v0];[0:a]atrim=s1:e1,asetpts=PTS-STARTPTS[a0];...;[v0][a0][v1][a1]concat=n=K:v=1:a=1[v][a]" -map "[v]" -map "[a]" cut.mp4
   ```
3. 竖屏合成:黑底 1080×1920,视频缩放到 1188×668 放在 (−54, 600):
   `-vf "scale=1188:668,pad=1080:1920:-54:600:black"`(负偏移不支持时,先 crop 掉两侧各 54 像素再 pad 到 x=0)。
4. 标题栏、金句卡:用 `drawtext`(字体 `/System/Library/Fonts/Hiragino Sans GB.ttc`)在上方区域写两行标题;金句卡用 `enable='between(t,a,b)'` 控制显示时段。
5. 字幕:用拼接后的时间轴生成 srt(每行 ≤15 字),`subtitles=xxx.srt:force_style='Alignment=2,MarginV=160,FontSize=18'` 烧录;同时保留 .srt 文件。
6. 输出:`-c:v libx264 -crf 20 -r 30 -c:a aac -b:a 128k -movflags +faststart -metadata comment="<切片ID>"`。
7. 校验同 ChatCut 第 9 步。回到环节 2 第 7 步登记。
