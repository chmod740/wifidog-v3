#!/bin/bash
# Build OpenWrt 25.x APK package using the official x86/64 SDK.
set -euo pipefail

OPENWRT_VERSION="${OPENWRT_VERSION:-25.12.3}"
TARGET="${TARGET:-x86/64}"
SDK_HOST="${SDK_HOST:-x86_64}"
SDK_GCC="${SDK_GCC:-14.3.0}"
SDK_LIBC="${SDK_LIBC:-musl}"
SDK_DIR="${SDK_DIR:-/tmp/wifidog_v3_sdk}"
DOCKER_IMAGE="${DOCKER_IMAGE:-debian:bookworm-slim}"
OPENWRT_DOWNLOAD_BASE="${OPENWRT_DOWNLOAD_BASE:-https://downloads.openwrt.org}"
DEBIAN_MIRROR_BASE="${DEBIAN_MIRROR_BASE:-}"

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
OUTPUT_DIR="$REPO_ROOT/dist/openwrt25"
SDK_BASENAME="openwrt-sdk-${OPENWRT_VERSION}-x86-64_gcc-${SDK_GCC}_${SDK_LIBC}.Linux-${SDK_HOST}"
SDK_TARBALL="${SDK_BASENAME}.tar.zst"
SDK_URL="${OPENWRT_DOWNLOAD_BASE%/}/releases/${OPENWRT_VERSION}/targets/${TARGET}/${SDK_TARBALL}"

mkdir -p "$SDK_DIR" "$OUTPUT_DIR"

if [ -f "$SDK_DIR/$SDK_TARBALL" ] && ! zstd -t "$SDK_DIR/$SDK_TARBALL" >/dev/null 2>&1; then
    echo "Removing incomplete OpenWrt SDK tarball: $SDK_DIR/$SDK_TARBALL"
    rm -f "$SDK_DIR/$SDK_TARBALL"
fi

if [ ! -f "$SDK_DIR/$SDK_TARBALL" ]; then
    echo "Downloading OpenWrt SDK: $SDK_URL"
    curl -fL "$SDK_URL" -o "$SDK_DIR/$SDK_TARBALL"
fi

echo "Building APK with OpenWrt ${OPENWRT_VERSION} SDK..."
docker run --rm --platform linux/amd64 \
    -e DEBIAN_MIRROR_BASE="$DEBIAN_MIRROR_BASE" \
    -v "$SDK_DIR/$SDK_TARBALL:/sdk.tar.zst:ro" \
    -v "$REPO_ROOT:/repo" \
    -w /work \
    "$DOCKER_IMAGE" \
bash -lc '
set -euo pipefail
if [ -n "${DEBIAN_MIRROR_BASE:-}" ]; then
    mirror="${DEBIAN_MIRROR_BASE%/}"
    sed -i \
        -e "s|http://deb.debian.org/debian-security|${mirror}/debian-security|g" \
        -e "s|http://deb.debian.org/debian|${mirror}/debian|g" \
        /etc/apt/sources.list /etc/apt/sources.list.d/*.sources 2>/dev/null || true
fi
apt-get update >/dev/null
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    build-essential gawk gcc-multilib flex gettext git libncurses-dev libssl-dev \
    python3 python3-distutils rsync unzip zlib1g-dev file wget ca-certificates \
    ccache zstd xz-utils >/dev/null

zstd -dc /sdk.tar.zst | tar -xf -
cd openwrt-sdk-*
rm -rf package/luci-app-wifidog-v3
cp -a /repo/luci-app-wifidog-v3 package/luci-app-wifidog-v3
echo CONFIG_PACKAGE_luci-app-wifidog-v3=m > .config
make defconfig >/tmp/wifidog_v3_openwrt25_defconfig.log
make package/luci-app-wifidog-v3/compile V=s -j1
mkdir -p /repo/dist/openwrt25
find bin -type f -name "luci-app-wifidog-v3*.apk" -print -exec cp -f {} /repo/dist/openwrt25/ \;
'

echo ""
echo "=== APK Package Built Successfully ==="
find "$OUTPUT_DIR" -maxdepth 1 -type f -name "luci-app-wifidog-v3*.apk" -print -exec ls -lh {} \;
