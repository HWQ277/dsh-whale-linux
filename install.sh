#!/usr/bin/env bash
# Install the DeepSeek whale widget.
#
#   ./install.sh            # per-user install into ~/.local  (no sudo needed)
#   ./install.sh --system   # system-wide install into /usr   (needs sudo)
#   ./install.sh --uninstall
#
# For a real pacman-managed package use:  makepkg -si
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP=dsh-whale-widget
MODE=user
ACTION=install

for arg in "$@"; do
  case "$arg" in
    --system) MODE=system ;;
    --user) MODE=user ;;
    --uninstall) ACTION=uninstall ;;
    -h|--help)
      sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) echo "未知参数: $arg" >&2; exit 2 ;;
  esac
done

if [[ "$MODE" == system ]]; then
  PREFIX=/usr
  LIBDIR="$PREFIX/lib/$APP"
  SHAREDIR="$PREFIX/share"
  BINDIR="$PREFIX/bin"
  SUDO=(sudo)
else
  PREFIX="${HOME}/.local"
  LIBDIR="$PREFIX/lib/$APP"
  SHAREDIR="$PREFIX/share"
  BINDIR="$PREFIX/bin"
  SUDO=()
fi

say() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }

if [[ "$ACTION" == uninstall ]]; then
  say "卸载 $APP ($MODE)"
  "${SUDO[@]}" rm -rf "$LIBDIR" "$SHAREDIR/dsh-whale" \
      "$SHAREDIR/applications/dsh-whale.desktop" \
      "$SHAREDIR/applications/dsh-whale-settings.desktop" \
      "$SHAREDIR/icons/hicolor/256x256/apps/dsh-whale.png"
  for s in 16 24 32 48 64 128; do
    "${SUDO[@]}" rm -f "$SHAREDIR/icons/hicolor/${s}x${s}/apps/dsh-whale.png"
  done
  "${SUDO[@]}" rm -f "$BINDIR/dsh-whale"
  command -v update-desktop-database >/dev/null && \
    "${SUDO[@]}" update-desktop-database "$SHAREDIR/applications" 2>/dev/null || true
  command -v gtk-update-icon-cache >/dev/null && \
    "${SUDO[@]}" gtk-update-icon-cache -qtf "$SHAREDIR/icons/hicolor" 2>/dev/null || true
  say "完成。配置目录 ~/.config/dsh-whale 未删除。"
  exit 0
fi

say "安装 $APP → $PREFIX ($MODE)"

# --- dependencies -----------------------------------------------------------
missing=()
python3 -c 'import tkinter' 2>/dev/null || missing+=("tk")
python3 -c 'import urllib.request' 2>/dev/null || missing+=("python")
if ((${#missing[@]})); then
  say "缺少依赖: ${missing[*]}"
  echo "请先安装:  sudo pacman -S ${missing[*]}" >&2
  exit 1
fi

# --- files ------------------------------------------------------------------
"${SUDO[@]}" install -dm755 "$LIBDIR"
"${SUDO[@]}" cp -a "$HERE/src" "$LIBDIR/"
"${SUDO[@]}" install -dm755 "$SHAREDIR/dsh-whale"
"${SUDO[@]}" cp -a "$HERE/assets/." "$SHAREDIR/dsh-whale/assets/"
# user-writable sound drop-in directory
"${SUDO[@]}" install -dm755 "$SHAREDIR/dsh-whale/assets/sounds"

"${SUDO[@]}" install -Dm644 "$HERE/packaging/dsh-whale.desktop" \
    "$SHAREDIR/applications/dsh-whale.desktop"
"${SUDO[@]}" install -Dm644 "$HERE/packaging/dsh-whale-settings.desktop" \
    "$SHAREDIR/applications/dsh-whale-settings.desktop"
"${SUDO[@]}" install -Dm644 "$HERE/packaging/dsh-whale.png" \
    "$SHAREDIR/icons/hicolor/256x256/apps/dsh-whale.png"
for s in 16 24 32 48 64 128; do
  [[ -f "$HERE/packaging/icons/dsh-whale-${s}.png" ]] && \
    "${SUDO[@]}" install -Dm644 "$HERE/packaging/icons/dsh-whale-${s}.png" \
      "$SHAREDIR/icons/hicolor/${s}x${s}/apps/dsh-whale.png"
done

# --- launcher ---------------------------------------------------------------
tmp="$(mktemp)"
cat > "$tmp" <<SHIM
#!/bin/sh
# DeepSeek whale widget launcher ($MODE install)
export PYTHONPATH="$LIBDIR/src\${PYTHONPATH:+:\$PYTHONPATH}"
export DSH_WHALE_ASSETS="\${DSH_WHALE_ASSETS:-$SHAREDIR/dsh-whale/assets}"
exec python3 -m dshwhale "\$@"
SHIM
"${SUDO[@]}" install -Dm755 "$tmp" "$BINDIR/dsh-whale"
rm -f "$tmp"

command -v update-desktop-database >/dev/null && \
  "${SUDO[@]}" update-desktop-database "$SHAREDIR/applications" 2>/dev/null || true
command -v gtk-update-icon-cache >/dev/null && \
  "${SUDO[@]}" gtk-update-icon-cache -qtf "$SHAREDIR/icons/hicolor" 2>/dev/null || true

say "安装完成。"
echo
echo "  启动挂件：   dsh-whale run"
echo "  打开设置：   dsh-whale settings"
echo "  终端查余额： dsh-whale status"
echo

# --- make sure ~/.local/bin is on PATH --------------------------------------
if [[ "$MODE" == user ]]; then
  bin_dir="$HOME/.local/bin"
  if [[ ":$PATH:" == *":$bin_dir:"* ]]; then
    :
  else
    added=0
    for rc in "$HOME/.bash_profile" "$HOME/.profile"; do
      [[ -e "$rc" ]] || continue
      if grep -q 'local/bin' "$rc" 2>/dev/null; then
        say "~/.local/bin 已在 PATH 配置中（$rc）——重新登录或 source 后生效"
        added=1
        break
      fi
      {
        echo ''
        echo '# added by dsh-whale-widget installer'
        echo 'case ":$PATH:" in'
        echo '  *":$HOME/.local/bin:"*) ;;'
        echo '  *) export PATH="$HOME/.local/bin:$PATH" ;;'
        echo 'esac'
      } >> "$rc"
      say "已把 ~/.local/bin 加入 PATH（$rc）——重新登录或 source 后生效"
      added=1
      break
    done
    if [[ "$added" == 0 ]]; then
      echo "提示：$bin_dir 不在 PATH 中。"
      echo "      可手动加入，或直接用完整路径： $bin_dir/dsh-whale run"
    fi
  fi
fi
