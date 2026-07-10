#!/bin/bash
# Build IPK package for luci-app-wifidog-v3
set -e

PKG_NAME="luci-app-wifidog-v3"
PKG_VERSION="1.0.4"
PKG_RELEASE="1"
PKG_ARCH="all"
PKG_MAINTAINER="WiFiDog V3 Team"
PKG_DESCRIPTION="WiFiDog V3 Network Authentication System for OpenWrt"
PKG_DEPENDS="firewall4, nftables-json, lua, uhttpd, libuci-lua, luci-compat, luci-lib-jsonc, luasocket"

BUILD_DIR="/tmp/ipk-build"
APP_DIR="$(cd "$(dirname "$0")" && pwd)/luci-app-wifidog-v3"
OUTPUT_DIR="$(cd "$(dirname "$0")" && pwd)/dist"

echo "=== Building IPK: ${PKG_NAME}_${PKG_VERSION}-${PKG_RELEASE}_${PKG_ARCH}.ipk ==="

# Clean build directory
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR/control"
mkdir -p "$BUILD_DIR/data"
mkdir -p "$OUTPUT_DIR"

# ============================================
# Step 1: Create control file
# ============================================
cat > "$BUILD_DIR/control/control" << EOF
Package: ${PKG_NAME}
Version: ${PKG_VERSION}-${PKG_RELEASE}
Architecture: ${PKG_ARCH}
Maintainer: ${PKG_MAINTAINER}
Section: luci
Priority: optional
Depends: ${PKG_DEPENDS}
Description: ${PKG_DESCRIPTION}
 WiFiDog V3 is a network authentication system for OpenWrt.
 It provides captive portal functionality with device management
 including whitelist, blacklist, and time-based authorization.
 .
 Features:
  - Network device scanning and management
  - Whitelist/Blacklist/Auth code based access control
  - Captive portal with HTTP redirect
  - Time-based authorization (24h default)
  - Auth code generation with usage limits
  - Optional FreeRADIUS PAP authentication
EOF

cat > "$BUILD_DIR/control/conffiles" << 'EOF'
/etc/config/wifidog_v3
EOF

# ============================================
# Step 2: Install application files to data directory
# ============================================

echo "Installing application files..."

# LuCI Controller
mkdir -p "$BUILD_DIR/data/usr/lib/lua/luci/controller"
cp "$APP_DIR/luasrc/controller/wifidog_v3.lua" "$BUILD_DIR/data/usr/lib/lua/luci/controller/"

# LuCI Models
mkdir -p "$BUILD_DIR/data/usr/lib/lua/luci/model/cbi/wifidog_v3"
cp "$APP_DIR/luasrc/model/cbi/wifidog_v3/"*.lua "$BUILD_DIR/data/usr/lib/lua/luci/model/cbi/wifidog_v3/"

# LuCI Views
mkdir -p "$BUILD_DIR/data/usr/lib/lua/luci/view/wifidog_v3"
cp "$APP_DIR/luasrc/view/wifidog_v3/"*.htm "$BUILD_DIR/data/usr/lib/lua/luci/view/wifidog_v3/"

# UCI Config
mkdir -p "$BUILD_DIR/data/etc/config"
cp "$APP_DIR/root/etc/config/wifidog_v3" "$BUILD_DIR/data/etc/config/"

# Init Script
mkdir -p "$BUILD_DIR/data/etc/init.d"
cp "$APP_DIR/root/etc/init.d/wifidog_v3" "$BUILD_DIR/data/etc/init.d/"
chmod 755 "$BUILD_DIR/data/etc/init.d/wifidog_v3"

# UCI Defaults
mkdir -p "$BUILD_DIR/data/etc/uci-defaults"
cp "$APP_DIR/root/etc/uci-defaults/40_luci-wifidog-v3" "$BUILD_DIR/data/etc/uci-defaults/"
chmod 755 "$BUILD_DIR/data/etc/uci-defaults/40_luci-wifidog-v3"

# Captive Portal uhttpd CGI
mkdir -p "$BUILD_DIR/data/www/wifidog_v3/cgi-bin/wifidog_v3"
cp "$APP_DIR/root/www/wifidog_v3/cgi-bin/wifidog_v3/portal" "$BUILD_DIR/data/www/wifidog_v3/cgi-bin/wifidog_v3/"
chmod 755 "$BUILD_DIR/data/www/wifidog_v3/cgi-bin/wifidog_v3/portal"
mkdir -p "$BUILD_DIR/data/www/cgi-bin/wifidog_v3"
cp "$APP_DIR/root/www/cgi-bin/wifidog_v3/portal" "$BUILD_DIR/data/www/cgi-bin/wifidog_v3/"
chmod 755 "$BUILD_DIR/data/www/cgi-bin/wifidog_v3/portal"

# Translation
mkdir -p "$BUILD_DIR/data/usr/lib/lua/luci/i18n"
cp "$APP_DIR/po/zh-cn/wifidog_v3.po" "$BUILD_DIR/data/usr/lib/lua/luci/i18n/wifidog_v3.zh-cn.po" 2>/dev/null || true

# ============================================
# Step 3: Create postinst and prerm scripts
# ============================================
cat > "$BUILD_DIR/control/postinst" << 'EOF'
#!/bin/sh
# Post-install script for luci-app-wifidog-v3
if [ -z "${IPKG_INSTROOT}" ]; then
    # Run UCI defaults
    if [ -f /etc/uci-defaults/40_luci-wifidog-v3 ]; then
        ( . /etc/uci-defaults/40_luci-wifidog-v3 ) && rm -f /etc/uci-defaults/40_luci-wifidog-v3
    fi
    if [ -f /etc/config/wifidog_v3 ]; then
        rm -f /etc/config/wifidog_v3-opkg /etc/config/wifidog_v3.apk-new
    fi
    # Make init script executable
    chmod 755 /etc/init.d/wifidog_v3 2>/dev/null
    chmod 755 /www/wifidog_v3/cgi-bin/wifidog_v3/portal 2>/dev/null
    chmod 755 /www/cgi-bin/wifidog_v3/portal 2>/dev/null
    # Create rc.d symlink
    ln -sf ../init.d/wifidog_v3 /etc/rc.d/S90wifidog_v3 2>/dev/null
    if [ "$(uci -q get wifidog_v3.settings.enabled 2>/dev/null)" = "1" ]; then
        /etc/init.d/wifidog_v3 restart >/dev/null 2>&1 || true
    fi
fi
exit 0
EOF
chmod 755 "$BUILD_DIR/control/postinst"

cat > "$BUILD_DIR/control/prerm" << 'EOF'
#!/bin/sh
# Pre-remove script for luci-app-wifidog-v3
if [ -f /etc/init.d/wifidog_v3 ]; then
    /etc/init.d/wifidog_v3 stop 2>/dev/null || true
    /etc/init.d/wifidog_v3 disable 2>/dev/null || true
fi
for pid in $(ps w 2>/dev/null | awk '/[l]ua/ && /\/usr\/share\/wifidog_v3\/portal_server\.lua/ { print $1 }'); do
    kill "$pid" >/dev/null 2>&1 || true
done
for pid in $(ps w 2>/dev/null | awk '/[u]httpd/ && /\/www\/wifidog_v3/ { print $1 }'); do
    kill "$pid" >/dev/null 2>&1 || true
done
sleep 1
for pid in $(ps w 2>/dev/null | awk '/[l]ua/ && /\/usr\/share\/wifidog_v3\/portal_server\.lua/ { print $1 }'); do
    kill -9 "$pid" >/dev/null 2>&1 || true
done
for pid in $(ps w 2>/dev/null | awk '/[u]httpd/ && /\/www\/wifidog_v3/ { print $1 }'); do
    kill -9 "$pid" >/dev/null 2>&1 || true
done
nft delete table inet wifidog_v3 2>/dev/null || true

if command -v iptables >/dev/null 2>&1; then
    cleanup_jump() {
        table="$1"; parent="$2"; target="$3"
        while true; do
            if [ -n "$table" ]; then
                num=$(iptables -t "$table" -L "$parent" --line-numbers -n 2>/dev/null | awk -v t="$target" '$2 == t { print $1; exit }')
                [ -n "$num" ] || break
                iptables -t "$table" -D "$parent" "$num" 2>/dev/null || break
            else
                num=$(iptables -L "$parent" --line-numbers -n 2>/dev/null | awk -v t="$target" '$2 == t { print $1; exit }')
                [ -n "$num" ] || break
                iptables -D "$parent" "$num" 2>/dev/null || break
            fi
        done
    }
    cleanup_jump nat PREROUTING wifidog_v3
    cleanup_jump "" FORWARD wifidog_v3
    iptables -t nat -F wifidog_v3 2>/dev/null || true
    iptables -t nat -X wifidog_v3 2>/dev/null || true
    iptables -F wifidog_v3 2>/dev/null || true
    iptables -X wifidog_v3 2>/dev/null || true
fi

if uci -q get uhttpd.wifidog_v3 >/dev/null 2>&1; then
    uci -q delete uhttpd.wifidog_v3
    uci -q commit uhttpd
    /etc/init.d/uhttpd restart 2>/dev/null || true
fi
if [ -e /tmp/dnsmasq.d/wifidog_v3.conf ]; then
    rm -f /tmp/dnsmasq.d/wifidog_v3.conf
    /etc/init.d/dnsmasq reload 2>/dev/null || /etc/init.d/dnsmasq restart 2>/dev/null || true
fi
portal_port="$(uci -q get wifidog_v3.settings.portal_port 2>/dev/null)"
[ -n "$portal_port" ] || portal_port="8080"
for pid in $(ps w 2>/dev/null | awk -v port="$portal_port" '
    /uhttpd/ && /\/www\/wifidog_v3/ {
        if ($0 ~ ("-p[[:space:]]+([^[:space:]]+:)?" port "([[:space:]]|$)")) print $1
    }
'); do
    kill "$pid" >/dev/null 2>&1 || true
done
while uci -q get ucitrack.@wifidog_v3[0] >/dev/null 2>&1; do
    uci -q delete ucitrack.@wifidog_v3[0]
done
uci -q commit ucitrack 2>/dev/null
rm -f /etc/rc.d/S90wifidog_v3 /var/log/wifidog_v3.log /var/log/wifidog_v3.log.1 /var/run/wifidog_v3_portal.pid /var/run/wifidog_v3_expiry.pid /tmp/dnsmasq.d/wifidog_v3.conf /tmp/wifidog_v3_ip_sessions 2>/dev/null
rm -rf /var/lock/wifidog_v3_auth.lock 2>/dev/null
exit 0
EOF
chmod 755 "$BUILD_DIR/control/prerm"

cat > "$BUILD_DIR/control/postrm" << 'EOF'
#!/bin/sh
# Post-remove cleanup for package-owned directories and state.
rm -rf /www/wifidog_v3 /www/cgi-bin/wifidog_v3 2>/dev/null || true
rm -rf /usr/share/wifidog_v3 2>/dev/null || true
rm -rf /usr/lib/lua/luci/model/cbi/wifidog_v3 2>/dev/null || true
rm -rf /usr/lib/lua/luci/view/wifidog_v3 2>/dev/null || true
rm -f /usr/lib/lua/luci/controller/wifidog_v3.lua 2>/dev/null || true
rm -f /usr/lib/lua/luci/i18n/wifidog_v3.zh-cn.po 2>/dev/null || true
rm -f /etc/config/wifidog_v3 /etc/uci-defaults/40_luci-wifidog-v3 2>/dev/null || true
for pid in $(ps w 2>/dev/null | awk '/[l]ua/ && /\/usr\/share\/wifidog_v3\/portal_server\.lua/ { print $1 }'); do
    kill "$pid" >/dev/null 2>&1 || true
done
for pid in $(ps w 2>/dev/null | awk '/[u]httpd/ && /\/www\/wifidog_v3/ { print $1 }'); do
    kill "$pid" >/dev/null 2>&1 || true
done
rm -f /etc/rc.d/S90wifidog_v3 /var/log/wifidog_v3.log /var/log/wifidog_v3.log.1 /var/run/wifidog_v3_portal.pid /var/run/wifidog_v3_expiry.pid /tmp/dnsmasq.d/wifidog_v3.conf /tmp/wifidog_v3_ip_sessions 2>/dev/null || true
rm -rf /var/lock/wifidog_v3_auth.lock 2>/dev/null || true
exit 0
EOF
chmod 755 "$BUILD_DIR/control/postrm"

# ============================================
# Step 4: Create the IPK archive
# ============================================
IPK_FILE="${OUTPUT_DIR}/${PKG_NAME}_${PKG_VERSION}-${PKG_RELEASE}_${PKG_ARCH}.ipk"

echo "Creating control tarball..."
cd "$BUILD_DIR/control"
tar --format=ustar -czf "$BUILD_DIR/control.tar.gz" ./*

echo "Creating data tarball..."
cd "$BUILD_DIR/data"
tar --format=ustar -czf "$BUILD_DIR/data.tar.gz" ./*

echo "Creating IPK package..."
cd "$BUILD_DIR"
echo "2.0" > debian-binary
tar --format=ustar -czf "$IPK_FILE" ./debian-binary ./control.tar.gz ./data.tar.gz

# Cleanup
rm -f "$BUILD_DIR/control.tar.gz" "$BUILD_DIR/data.tar.gz" "$BUILD_DIR/debian-binary"

echo ""
echo "=== IPK Package Built Successfully ==="
echo "Package: $IPK_FILE"
echo "Size: $(du -h "$IPK_FILE" | cut -f1)"
echo ""
echo "Package contents:"
tar tzf "$IPK_FILE" | head -30
echo "..."
echo ""
echo "Total files: $(tar tzf "$IPK_FILE" | wc -l)"
