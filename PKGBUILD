# Maintainer: dsh-whale-linux contributors
# Arch Linux PKGBUILD for the DeepSeek balance whale desktop widget.
#
# Build & install:
#   makepkg -si
#
# The widget is pure Python 3 + tkinter, so this package has no build step and
# only needs the interpreter's bundled tk module.

pkgname=dsh-whale-widget
pkgver=1.0.0
pkgrel=1
pkgdesc="DeepSeek 余额小鲸鱼桌面挂件（DSH 网页插件的 Linux/Arch 桌面移植版）"
arch=('any')
url="https://github.com/MeteorNOX/DeepSeek-Balance-Whale-Widget"
license=('MIT')
depends=('python' 'tk')
optdepends=(
  'libxext: X11 SHAPE 异形窗口（镂空鲸鱼与气泡外形）'
  'libx11: 窗口置顶 / 跳过任务栏（EWMH）'
  'python-pillow: 仅在需要重新生成图标时使用'
)
provides=('dsh-whale')
conflicts=('dsh-whale')
options=('!strip' '!emptydirs')

# Source is this directory (a local checkout). Build with:
#   makepkg -si
# from the repository root, or point source=() at a release tarball.
source=()
md5sums=()

_pkgroot="$srcdir/$pkgname-$pkgver"

prepare() {
  mkdir -p "$_pkgroot"
  # Copy from the PKGBUILD's own directory when building in-tree.
  local _here
  _here="$(dirname "$(realpath "${BASH_SOURCE[0]}")")"
  if [[ "$_here" != "$_pkgroot" ]]; then
    cp -a "$_here/src" "$_here/assets" "$_here/dsh-whale" \
          "$_here/packaging" "$_here/LICENSE" "$_here/README.md" "$_pkgroot/" 2>/dev/null || true
  fi
}

package() {
  local _src="$srcdir/$pkgname-$pkgver"
  # Fall back to the PKGBUILD directory when prepare() had nothing to copy.
  [[ -d "$_src/src" ]] || _src="$(dirname "$(realpath "${BASH_SOURCE[0]}")")"

  install -dm755 "$pkgdir/usr/lib/$pkgname"
  cp -a "$_src/src" "$pkgdir/usr/lib/$pkgname/"
  install -Dm644 "$_src/LICENSE" "$pkgdir/usr/share/licenses/$pkgname/LICENSE"
  install -Dm644 "$_src/README.md" "$pkgdir/usr/share/doc/$pkgname/README.md"

  # Image assets live in /usr/share (the CLI finds them there).
  install -dm755 "$pkgdir/usr/share/dsh-whale"
  cp -a "$_src/assets/." "$pkgdir/usr/share/dsh-whale/assets/" 2>/dev/null || true
  install -Dm644 "$_src/packaging/dsh-whale.png" \
    "$pkgdir/usr/share/icons/hicolor/256x256/apps/dsh-whale.png"
  for size in 16 24 32 48 64 128; do
    if [[ -f "$_src/packaging/icons/dsh-whale-$size.png" ]]; then
      install -Dm644 "$_src/packaging/icons/dsh-whale-$size.png" \
        "$pkgdir/usr/share/icons/hicolor/${size}x${size}/apps/dsh-whale.png"
    fi
  done

  install -Dm644 "$_src/packaging/dsh-whale.desktop" \
    "$pkgdir/usr/share/applications/dsh-whale.desktop"
  install -Dm644 "$_src/packaging/dsh-whale-settings.desktop" \
    "$pkgdir/usr/share/applications/dsh-whale-settings.desktop"

  # Launcher shim on PATH.
  install -dm755 "$pkgdir/usr/bin"
  cat > "$pkgdir/usr/bin/dsh-whale" <<'SHIM'
#!/bin/sh
# DeepSeek whale widget launcher (system install)
export PYTHONPATH="/usr/lib/dsh-whale-widget/src${PYTHONPATH:+:$PYTHONPATH}"
export DSH_WHALE_ASSETS="${DSH_WHALE_ASSETS:-/usr/share/dsh-whale/assets}"
exec python3 -m dshwhale "$@"
SHIM
  chmod 755 "$pkgdir/usr/bin/dsh-whale"
}
