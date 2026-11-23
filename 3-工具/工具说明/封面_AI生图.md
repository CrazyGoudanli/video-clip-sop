# 封面:AI 生图(配置.封面风格 = 道具伸向镜头)

> 来源:旧项目 cover-designer 技能的实测做法。当前实现用 Codex CLI 调用 GPT Image(消耗用户的 ChatGPT 额度)。

## 前提
- 已安装 `codex` 并已登录(用户本人登录)。
- 生图要走代理:`127.0.0.1:7890`(端口不同就改这里)。

## 步骤
1. 填写提示词模板 `3-工具/模板/cover_prompt.md` 的占位符:{REF_NOTE}{SIZES}{LINE1}{LINE2}{KEY}{PROP}。
2. 把填好的提示词存成文件,然后调用(脚本已带代理,单条命令即可):
   `zsh 3-工具/脚本/gen_cover.sh <工作目录> <提示词文件> <参考图1> <参考图2>`
   工作目录建议用 `<成片文件夹>/封面/_工作/`。
   每张约 3–5 分钟,多条可并行。
3. 先出 3x4.png(1080×1440),再出 4x3.png(1440×1080),横版以竖版为依据。
4. 转 jpg(quality 92;用 `sips -s format jpeg -s formatOptions 92 <png> --out <jpg>`,每张一条命令),存为 `封面/抖音_竖3x4.jpg`、`封面/抖音_横4x3.jpg`。

## 后备
- `uv run --with pillow python3 3-工具/脚本/make_covers.py <copy.json>`(脚本拼图版;copy.json 格式见脚本开头注释)。

## 换成别的生图工具
只要能"给 2 张参考图 + 提示词 → 输出指定尺寸图片",就可以替换第 2 步,其余步骤和验收不变。
