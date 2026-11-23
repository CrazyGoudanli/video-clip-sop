#!/bin/zsh
# 本机转写(免费、不上传)。
# 用法: transcribe.sh <输入文件夹(含 mp4)> <输出文件夹>
# 产物: <输出>/audio/*.m4a、<输出>/transcript/*.{json,srt,txt,...}
set -e
export PATH="$HOME/.local/bin:$PATH"
SRC="$1"; OUT="$2"
[ -d "$SRC" ] || { echo "输入文件夹不存在: $SRC"; exit 2; }
[ -n "$OUT" ] || { echo "缺少输出文件夹"; exit 2; }
mkdir -p "$OUT/audio" "$OUT/transcript"
for f in "$SRC"/*.mp4(N) "$SRC"/*.MP4(N); do
  name="${f:t:r}"
  a="$OUT/audio/$name.m4a"
  [ -f "$a" ] || ffmpeg -nostdin -loglevel error -y -i "$f" -vn -ac 1 -ar 16000 -c:a aac -b:a 32k "$a"
  if [ ! -f "$OUT/transcript/$name.json" ]; then
    echo "[$(date +%T)] 转写 $name"
    mlx_whisper "$a" --model mlx-community/whisper-large-v3-turbo --language zh \
      --initial-prompt "以下是普通话的讲解，使用简体中文和标点。" \
      --condition-on-previous-text False \
      --output-format all --output-dir "$OUT/transcript" --output-name "$name" --verbose False
  fi
done
echo "[$(date +%T)] DONE"
