#!/bin/zsh
# 本机转写(免费、不上传)。
# 用法: transcribe.sh <输入文件夹(含 mp4/mov/m4v,可以是链接)> <输出文件夹>
# 产物: <输出>/audio/*.m4a、<输出>/transcript/*.{json,srt,txt,...}
set -e
export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"
ROOT="${0:A:h}/../.."
SRC="$1"; OUT="$2"
[ -d "$SRC" ] || { echo "输入文件夹不存在: $SRC"; exit 2; }
[ -n "$OUT" ] || { echo "缺少输出文件夹"; exit 2; }
mkdir -p "$OUT/audio" "$OUT/transcript"
MODEL="mlx-community/whisper-large-v3-turbo"
# 禁用 hf-xet(XetHub CAS 客户端在弱网/代理下容易报 CAS Client Error 卡死),改走稳定 HTTPS 断点续传
export HF_HUB_DISABLE_XET=1
HF_CACHE="${HF_HUB_CACHE:-${HF_HOME:-$HOME/.cache/huggingface}/hub}"
SNAP_DIR="$HF_CACHE/models--${MODEL//\//--}/snapshots"
# 必须检测到真实权重文件(*.safetensors 或 *.npz)存在,才切离线模式,避免上次下载中断后误判离线
if [ -d "$SNAP_DIR" ] && find -L "$SNAP_DIR" -type f \( -name "*.safetensors" -o -name "*.npz" \) -size +10M 2>/dev/null | grep -q .; then
  export HF_HUB_OFFLINE=1
  unset ALL_PROXY all_proxy HTTPS_PROXY https_proxy HTTP_PROXY http_proxy
else
  PROXY="$(python3 -I -c "import json;print(json.load(open('$ROOT/配置.json')).get('代理',''))" 2>/dev/null || true)"
  if [ -n "$PROXY" ]; then
    export HTTPS_PROXY="$PROXY" HTTP_PROXY="$PROXY" ALL_PROXY="$PROXY"
  elif [ -z "${HF_ENDPOINT:-}" ]; then
    # 未配代理时默认走国内可直连的 HF 镜像加速首次 1.6GB 模型下载
    export HF_ENDPOINT="https://hf-mirror.com"
  fi
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
