#!/bin/zsh
# 用本机 launchd 定时跑监测 / 常驻工作台。不改 配置.json。
# 用法(在项目根目录,或任意位置调用本脚本均可):
#   zsh 3-工具/脚本/autorun.sh install            # 每隔「监测间隔秒」跑一次 watch.py --once
#   zsh 3-工具/脚本/autorun.sh install-workbench  # KeepAlive 常驻工作台(端口 8765)
#   zsh 3-工具/脚本/autorun.sh uninstall          # 卸掉上面两个任务
#   zsh 3-工具/脚本/autorun.sh status             # 看是否已装、是否在跑、最近日志
set -euo pipefail

ROOT="${0:A:h}/../.."
ROOT="${ROOT:A}"
cd "$ROOT"

AGENTS_DIR="$HOME/Library/LaunchAgents"
LOGDIR="$ROOT/data/运行日志"
LOG="$LOGDIR/autorun.log"
UID_N="$(id -u)"
DOMAIN="gui/${UID_N}"

# 按项目绝对路径做短哈希,两个副本互不抢标签
HASH="$(print -n "$ROOT" | shasum -a 256 | cut -c1-10)"
LABEL_WATCH="com.videoclipsop.${HASH}.watch"
LABEL_WB="com.videoclipsop.${HASH}.workbench"
PLIST_WATCH="${AGENTS_DIR}/${LABEL_WATCH}.plist"
PLIST_WB="${AGENTS_DIR}/${LABEL_WB}.plist"

PATH_VAL="${HOME}/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
PYTHON3="$(command -v python3 || true)"
if [[ -z "$PYTHON3" ]]; then
  echo "找不到 python3,请先装好系统 Python。" >&2
  exit 2
fi

interval() {
  python3 -I -c '
import json, pathlib, sys
p = pathlib.Path(sys.argv[1]) / "配置.json"
try:
    n = int(json.load(p.open()).get("监测间隔秒") or 300)
except Exception:
    n = 300
print(n if n > 0 else 300)
' "$ROOT"
}

ensure_logdir() {
  mkdir -p "$LOGDIR"
}

write_plist_watch() {
  local sec="$1"
  cat > "$PLIST_WATCH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${LABEL_WATCH}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${PYTHON3}</string>
    <string>${ROOT}/3-工具/watch.py</string>
    <string>--once</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${ROOT}</string>
  <key>StartInterval</key>
  <integer>${sec}</integer>
  <key>RunAtLoad</key>
  <true/>
  <key>StandardOutPath</key>
  <string>${LOG}</string>
  <key>StandardErrorPath</key>
  <string>${LOG}</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>${PATH_VAL}</string>
  </dict>
</dict>
</plist>
EOF
}

write_plist_wb() {
  cat > "$PLIST_WB" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${LABEL_WB}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${PYTHON3}</string>
    <string>${ROOT}/3-工具/工作台/server.py</string>
    <string>--no-open</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${ROOT}</string>
  <key>KeepAlive</key>
  <true/>
  <key>RunAtLoad</key>
  <true/>
  <key>StandardOutPath</key>
  <string>${LOG}</string>
  <key>StandardErrorPath</key>
  <string>${LOG}</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>${PATH_VAL}</string>
  </dict>
</dict>
</plist>
EOF
}

loaded() {
  launchctl print "${DOMAIN}/$1" >/dev/null 2>&1
}

load_plist() {
  local label="$1" plist="$2"
  if loaded "$label"; then
    launchctl bootout "${DOMAIN}/${label}" 2>/dev/null || true
  fi
  launchctl bootstrap "$DOMAIN" "$plist"
}

unload_plist() {
  local label="$1" plist="$2"
  if loaded "$label"; then
    launchctl bootout "${DOMAIN}/${label}" 2>/dev/null || true
  fi
  # 兼容旧写法残留
  if [[ -f "$plist" ]]; then
    launchctl unload "$plist" 2>/dev/null || true
  fi
  rm -f "$plist"
}

cmd_install() {
  ensure_logdir
  mkdir -p "$AGENTS_DIR"
  local sec
  sec="$(interval)"
  write_plist_watch "$sec"
  load_plist "$LABEL_WATCH" "$PLIST_WATCH"
  echo "✅ 已安装监测任务 ${LABEL_WATCH}(每隔 ${sec} 秒,日志 ${LOG})"
}

cmd_install_workbench() {
  ensure_logdir
  mkdir -p "$AGENTS_DIR"
  write_plist_wb
  load_plist "$LABEL_WB" "$PLIST_WB"
  echo "✅ 已安装工作台任务 ${LABEL_WB}(KeepAlive,端口 8765,日志 ${LOG})"
}

cmd_uninstall() {
  unload_plist "$LABEL_WATCH" "$PLIST_WATCH"
  unload_plist "$LABEL_WB" "$PLIST_WB"
  echo "✅ 已卸载监测与工作台任务(仅删本项目这两个 plist)"
}

show_one() {
  local title="$1" label="$2" plist="$3"
  local inst="未装" run="未跑"
  [[ -f "$plist" ]] && inst="已装"
  if loaded "$label"; then
    run="在跑"
  fi
  echo "${title}: ${inst} / ${run}  (${label})"
  echo "  plist: ${plist}"
}

cmd_status() {
  echo "项目: ${ROOT}"
  echo "标签哈希: ${HASH}"
  show_one "监测" "$LABEL_WATCH" "$PLIST_WATCH"
  show_one "工作台" "$LABEL_WB" "$PLIST_WB"
  echo "最近日志(${LOG}):"
  if [[ -f "$LOG" ]]; then
    tail -n 10 "$LOG" || true
  else
    echo "(还没有日志文件)"
  fi
}

usage() {
  echo "用法: zsh 3-工具/脚本/autorun.sh {install|install-workbench|uninstall|status}" >&2
  exit 2
}

case "${1:-}" in
  install) cmd_install ;;
  install-workbench) cmd_install_workbench ;;
  uninstall) cmd_uninstall ;;
  status) cmd_status ;;
  *) usage ;;
esac
