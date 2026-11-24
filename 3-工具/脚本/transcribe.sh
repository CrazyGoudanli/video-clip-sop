#!/bin/zsh
# 本机转写(免费、不上传)。
# 用法: transcribe.sh <输入文件夹(含 mp4/mov/m4v,可以是链接)> <输出文件夹>
# 产物: <输出>/audio/*.m4a、<输出>/transcript/*.{json,srt,txt,...}
set -e
export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"
SRC="$1"; OUT="$2"
[ -d "$SRC" ] || { echo "输入文件夹不存在: $SRC"; exit 2; }
[ -n "$OUT" ] || { echo "缺少输出文件夹"; exit 2; }
mkdir -p "$OUT/audio" "$OUT/transcript"
MODEL="mlx-community/whisper-large-v3-turbo"
# 模型已下载过就离线运行:不再联网查模型,避开代理/网络问题。第一次(没缓存)才联网下载约 1.6 GB。
HF_CACHE="${HF_HUB_CACHE:-${HF_HOME:-$HOME/.cache/huggingface}/hub}"
if [ -d "$HF_CACHE/models--${MODEL//\//--}/snapshots" ]; then
  export HF_HUB_OFFLINE=1
  # 离线时不需要代理;去掉代理变量,避免缺少 SOCKS 支持时直接报错
  unset ALL_PROXY all_proxy HTTPS_PROXY https_proxy HTTP_PROXY http_proxy
fi
for f in "$SRC"/*.(mp4|MP4|mov|MOV|m4v|M4V)(N); do
  name="${f:t:r}"
  a="$OUT/audio/$name.m4a"
  [ -f "$a" ] || ffmpeg -nostdin -loglevel error -y -i "$f" -vn -ac 1 -ar 16000 -c:a aac -b:a 32k "$a"
  if [ ! -f "$OUT/transcript/$name.json" ]; then
    echo "[$(date +%T)] 转写 $name"
    mlx_whisper "$a" --model "$MODEL" --language zh \
      --initial-prompt "以下是普通话的讲解，使用简体中文和标点。" \
      --condition-on-previous-text False \
      --output-format all --output-dir "$OUT/transcript" --output-name "$name" --verbose False
    [ -s "$OUT/transcript/$name.json" ] || { echo "[$(date +%T)] 转写失败:$name 没有生成逐字稿(看上面的报错)"; exit 1; }
  fi
done
echo "[$(date +%T)] DONE"
