include $(TOPDIR)/rules.mk

PKG_NAME:=luci-app-wifidog-v3
PKG_VERSION:=1.0.0
PKG_RELEASE:=1
PKG_LICENSE:=MIT
PKG_MAINTAINER:=WiFiDog V3 Team

PKG_BUILD_DIR:=$(BUILD_DIR)/$(PKG_NAME)

include $(INCLUDE_DIR)/package.mk

define Package/$(PKG_NAME)
  SECTION:=luci
  CATEGORY:=LuCI
  SUBMENU:=3. Applications
  TITLE:=WiFiDog V3 Network Authentication System
  PKGARCH:=all
  DEPENDS:=+firewall4 +nftables-json +lua +uhttpd +libuci-lua +luci-compat +luci-lib-jsonc +luasocket
endef

define Package/$(PKG_NAME)/description
WiFiDog V3 is a network authentication system for OpenWrt.
It provides captive portal functionality with device management,
whitelist/blacklist, authorization codes, themes and timed access.
endef

define Build/Compile
endef

define Package/$(PKG_NAME)/install
	$(INSTALL_DIR) $(1)/usr/lib/lua/luci/controller
	$(INSTALL_DATA) ./luasrc/controller/wifidog_v3.lua $(1)/usr/lib/lua/luci/controller/

	$(INSTALL_DIR) $(1)/usr/lib/lua/luci/model/cbi/wifidog_v3
	$(INSTALL_DATA) ./luasrc/model/cbi/wifidog_v3/*.lua $(1)/usr/lib/lua/luci/model/cbi/wifidog_v3/

	$(INSTALL_DIR) $(1)/usr/lib/lua/luci/view/wifidog_v3
	$(INSTALL_DATA) ./luasrc/view/wifidog_v3/*.htm $(1)/usr/lib/lua/luci/view/wifidog_v3/

	$(INSTALL_DIR) $(1)/etc/config
	$(INSTALL_CONF) ./root/etc/config/wifidog_v3 $(1)/etc/config/

	$(INSTALL_DIR) $(1)/etc/init.d
	$(INSTALL_BIN) ./root/etc/init.d/wifidog_v3 $(1)/etc/init.d/

	$(INSTALL_DIR) $(1)/etc/uci-defaults
	$(INSTALL_BIN) ./root/etc/uci-defaults/40_luci-wifidog-v3 $(1)/etc/uci-defaults/

	$(INSTALL_DIR) $(1)/www/wifidog_v3/cgi-bin/wifidog_v3
	$(INSTALL_BIN) ./root/www/wifidog_v3/cgi-bin/wifidog_v3/portal $(1)/www/wifidog_v3/cgi-bin/wifidog_v3/

	$(INSTALL_DIR) $(1)/www/cgi-bin/wifidog_v3
	$(INSTALL_BIN) ./root/www/cgi-bin/wifidog_v3/portal $(1)/www/cgi-bin/wifidog_v3/

	$(INSTALL_DIR) $(1)/usr/lib/lua/luci/i18n
	$(INSTALL_DATA) ./po/zh-cn/wifidog_v3.po $(1)/usr/lib/lua/luci/i18n/wifidog_v3.zh-cn.po
endef

define Package/$(PKG_NAME)/postinst
#!/bin/sh
if [ -z "$${IPKG_INSTROOT}" ] && [ -f /etc/uci-defaults/40_luci-wifidog-v3 ]; then
	( . /etc/uci-defaults/40_luci-wifidog-v3 ) && rm -f /etc/uci-defaults/40_luci-wifidog-v3
fi
chmod 755 "$${IPKG_INSTROOT}/etc/init.d/wifidog_v3" >/dev/null 2>&1
chmod 755 "$${IPKG_INSTROOT}/www/wifidog_v3/cgi-bin/wifidog_v3/portal" >/dev/null 2>&1
chmod 755 "$${IPKG_INSTROOT}/www/cgi-bin/wifidog_v3/portal" >/dev/null 2>&1
ln -sf "../init.d/wifidog_v3" "$${IPKG_INSTROOT}/etc/rc.d/S90wifidog_v3" >/dev/null 2>&1
if [ -z "$${IPKG_INSTROOT}" ] && [ "$$(uci -q get wifidog_v3.settings.enabled 2>/dev/null)" = "1" ]; then
	/etc/init.d/wifidog_v3 restart >/dev/null 2>&1 || true
fi
exit 0
endef

define Package/$(PKG_NAME)/prerm
#!/bin/sh
# ============================================================
# WiFiDog V3 - Pre-removal cleanup (runs BEFORE files removed)
# This ensures complete system restoration on uninstall.
# ============================================================

# 1. Stop and disable service (handles iptables cleanup)
if [ -f /etc/init.d/wifidog_v3 ]; then
	/etc/init.d/wifidog_v3 stop 2>/dev/null
	/etc/init.d/wifidog_v3 disable 2>/dev/null
	rm -f /etc/rc.d/S90wifidog_v3 2>/dev/null
fi
for pid in $$(ps w 2>/dev/null | awk '/[l]ua/ && /\/usr\/share\/wifidog_v3\/portal_server\.lua/ { print $$1 }'); do
	kill "$$pid" >/dev/null 2>&1 || true
done
for pid in $$(ps w 2>/dev/null | awk '/[u]httpd/ && /\/www\/wifidog_v3/ { print $$1 }'); do
	kill "$$pid" >/dev/null 2>&1 || true
done
sleep 1
for pid in $$(ps w 2>/dev/null | awk '/[l]ua/ && /\/usr\/share\/wifidog_v3\/portal_server\.lua/ { print $$1 }'); do
	kill -9 "$$pid" >/dev/null 2>&1 || true
done
for pid in $$(ps w 2>/dev/null | awk '/[u]httpd/ && /\/www\/wifidog_v3/ { print $$1 }'); do
	kill -9 "$$pid" >/dev/null 2>&1 || true
done

# 2. Remove nftables table used by current builds
nft delete table inet wifidog_v3 2>/dev/null

# 3. Defense in depth: remove legacy iptables rules from older builds
if command -v iptables >/dev/null 2>&1; then
	cleanup_jump() {
		table="$$1"
		parent="$$2"
		target="$$3"
		while true; do
			if [ -n "$$table" ]; then
				num=$$(iptables -t "$$table" -L "$$parent" --line-numbers -n 2>/dev/null | awk -v t="$$target" '$$2 == t { print $$1; exit }')
				[ -n "$$num" ] || break
				iptables -t "$$table" -D "$$parent" "$$num" 2>/dev/null || break
			else
				num=$$(iptables -L "$$parent" --line-numbers -n 2>/dev/null | awk -v t="$$target" '$$2 == t { print $$1; exit }')
				[ -n "$$num" ] || break
				iptables -D "$$parent" "$$num" 2>/dev/null || break
			fi
		done
	}
	cleanup_jump nat PREROUTING wifidog_v3
	cleanup_jump "" FORWARD wifidog_v3
	iptables -t nat -F wifidog_v3 2>/dev/null
	iptables -t nat -X wifidog_v3 2>/dev/null
	iptables -F wifidog_v3 2>/dev/null
	iptables -X wifidog_v3 2>/dev/null
fi

# 4. Remove legacy uhttpd portal instance from older builds
if uci -q get uhttpd.wifidog_v3 >/dev/null 2>&1; then
	uci -q delete uhttpd.wifidog_v3
	uci -q commit uhttpd
	/etc/init.d/uhttpd restart 2>/dev/null || true
fi
if [ -e /tmp/dnsmasq.d/wifidog_v3.conf ]; then
	rm -f /tmp/dnsmasq.d/wifidog_v3.conf
	/etc/init.d/dnsmasq reload 2>/dev/null || /etc/init.d/dnsmasq restart 2>/dev/null || true
fi
portal_port="$$(uci -q get wifidog_v3.settings.portal_port 2>/dev/null)"
[ -n "$$portal_port" ] || portal_port="8080"
for pid in $$(ps w 2>/dev/null | awk -v port="$$portal_port" '\
	/uhttpd/ && /\/www\/wifidog_v3/ {\
		if ($$0 ~ ("-p[[:space:]]+([^[:space:]]+:)?" port "([[:space:]]|$$)")) print $$1\
	}\
'); do
	kill "$$pid" >/dev/null 2>&1 || true
done

# 5. Remove ucitrack entry
if uci -q get ucitrack.@wifidog_v3[0] >/dev/null 2>&1; then
	while uci -q get ucitrack.@wifidog_v3[0] >/dev/null 2>&1; do
		uci -q delete ucitrack.@wifidog_v3[0]
	done
	uci -q commit ucitrack
fi

# 6. Remove generated state files
rm -f /var/log/wifidog_v3.log /var/run/wifidog_v3_portal.pid /var/run/wifidog_v3_expiry.pid /tmp/dnsmasq.d/wifidog_v3.conf /tmp/wifidog_v3_ip_sessions 2>/dev/null

exit 0
endef

define Package/$(PKG_NAME)/postrm
#!/bin/sh
for pid in $$(ps w 2>/dev/null | awk '/[l]ua/ && /\/usr\/share\/wifidog_v3\/portal_server\.lua/ { print $$1 }'); do
	kill "$$pid" >/dev/null 2>&1 || true
done
for pid in $$(ps w 2>/dev/null | awk '/[u]httpd/ && /\/www\/wifidog_v3/ { print $$1 }'); do
	kill "$$pid" >/dev/null 2>&1 || true
done
rm -rf /www/wifidog_v3 /www/cgi-bin/wifidog_v3 2>/dev/null
rm -rf /usr/share/wifidog_v3 2>/dev/null
rm -rf /usr/lib/lua/luci/model/cbi/wifidog_v3 2>/dev/null
rm -rf /usr/lib/lua/luci/view/wifidog_v3 2>/dev/null
rm -f /usr/lib/lua/luci/controller/wifidog_v3.lua 2>/dev/null
rm -f /usr/lib/lua/luci/i18n/wifidog_v3.zh-cn.po 2>/dev/null
rm -f /etc/config/wifidog_v3 /etc/uci-defaults/40_luci-wifidog-v3 2>/dev/null
rm -f /etc/rc.d/S90wifidog_v3 /var/log/wifidog_v3.log /var/run/wifidog_v3_portal.pid /var/run/wifidog_v3_expiry.pid /tmp/dnsmasq.d/wifidog_v3.conf /tmp/wifidog_v3_ip_sessions 2>/dev/null
exit 0
endef

$(eval $(call BuildPackage,$(PKG_NAME)))
