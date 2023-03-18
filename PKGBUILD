# Maintainer: Mike Macpherson <mmacpherson@noreply.github.io>

pkgname=expirito
pkgver=1.0.0
pkgrel=1
epoch=
pkgdesc="A utility to clean up old files and empty directories"
arch=("any")
url="https://example.com"
license=("MIT")
depends=("python" "python-yaml")
makedepends=("git")
provides=("${pkgname}")
conflicts=()
replaces=()
backup=()
options=()
install=
changelog=

source=(
  "https://example.com/your-repo-url.git"
)
sha256sums=("SKIP")

build() {
  cd "${srcdir}/expirito"

  # Add any build steps if needed
}

package() {
  cd "${srcdir}/expirito"

  install -Dm755 expirito.py "${pkgdir}/usr/bin/expirito"
  install -Dm644 expirito.service "${pkgdir}/usr/lib/systemd/user/expirito.service"
  install -Dm644 expirito.timer "${pkgdir}/usr/lib/systemd/user/expirito.timer"
}
