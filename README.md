# WiFiDog V3

[English](README_en.md)

WiFiDog V3 是一个面向 OpenWrt 的 LuCI 网络认证系统，用于在路由器上管理待授权设备、白名单、黑名单、授权码和 Captive Portal 认证流程。

## 功能演示

![Captive Portal 功能演示](docs/assets/captive-portal-demo.gif)

## 功能特性

- 网络设备扫描：从 ARP 表和 DHCP leases 中识别内网设备。
- 设备名单管理：待授权、白名单、黑名单、已授权设备均支持备注，备注按 MAC 地址保留。
- 白名单：设备访问内外网不受限制。
- 黑名单：设备可访问内网资源，禁止访问公网资源，Portal 页面仅提示被拉黑，不能自助授权。
- 手动授权：管理后台可授权设备默认 24 小时访问权限。
- 授权码：支持自定义授权码、可用次数、授权码有效期、单独授权时长、启用/停用和自助认证。
- Captive Portal 兼容：
  - RFC 8908 Captive Portal API
  - RFC 8910 DHCP option 114
  - odhcpd captive portal URI
  - iOS、Android、Windows、NetworkManager 等旧探测路径
- Portal 页面：使用独立 uhttpd 实例，支持主题切换和后台自定义提示词、标题、按钮文案。
- 配置备份恢复：支持导入/导出系统设置、黑白名单、备注、授权码和 Portal 页面配置。
- Passwall2 共存：使用更早优先级的 nftables 规则，尽量在分流规则前完成认证控制。
- 安全卸载：卸载时清理 nftables、Portal 进程、DHCP/RA 广告、运行状态和配置文件。

## 支持版本

已验证版本：

- OpenWrt 23.05.6 x86/64：IPK
- OpenWrt 24.10.6 x86/64：IPK
- OpenWrt 25.12.3 x86/64：APK

运行依赖：

- firewall4
- nftables-json
- lua
- uhttpd
- libuci-lua
- luci-compat
- luci-lib-jsonc

## 构建

构建 OpenWrt 23/24 IPK：

```sh
./build_ipk.sh
```

输出：

```text
dist/luci-app-wifidog-v3_1.0.0-1_all.ipk
```

构建 OpenWrt 25 APK：

```sh
./build_openwrt25_apk.sh
```

输出：

```text
dist/openwrt25/luci-app-wifidog-v3-1.0.0-r1.apk
```

## 安装

OpenWrt 23/24：

```sh
opkg update
opkg install /tmp/luci-app-wifidog-v3_1.0.0-1_all.ipk
```

OpenWrt 25：

```sh
apk add --allow-untrusted /tmp/luci-app-wifidog-v3-1.0.0-r1.apk
```

安装后进入 LuCI：

```text
服务 -> WiFiDog V3
```

也可以使用 init 脚本：

```sh
/etc/init.d/wifidog_v3 start
/etc/init.d/wifidog_v3 stop
/etc/init.d/wifidog_v3 restart
```

## 配置

主要 UCI 配置位于：

```text
/etc/config/wifidog_v3
```

常用设置：

- `enabled`：是否启用系统
- `lan_interface`：LAN 接口
- `wan_interface`：WAN 接口
- `portal_port`：Portal 服务端口，默认 `8080`
- `lan_subnet`：内网网段
- `auth_timeout`：授权时长，单位分钟，默认 `1440`
- `authcode.*.auth_minutes`：单个授权码使用后的授权时长，单位分钟；为空时使用 `auth_timeout`
- `portal_theme`：Portal 页面主题
- `portal_title`：Portal 页面标题
- `portal_prompt`：Portal 主提示词
- `portal_hint`：Portal 底部提示词
- `portal_button_text`：Portal 按钮文案

## 测试

Docker 回归：

```sh
python3 test/e2e_openwrt23_container.py
```

OpenWrt 25 / APK 模式：

```sh
PKG_MANAGER=apk python3 test/e2e_openwrt23_container.py
```

UTM 烟测脚本：

```sh
lua /tmp/utm_smoke.lua
```

最近回归结果：

- Docker OpenWrt 23.05.6：`90 passed, 0 failed`
- Docker OpenWrt 24.10.6：`90 passed, 0 failed`
- Docker OpenWrt 25.12.3：`90 passed, 0 failed`
- UTM OpenWrt 23.05.6：`UTM_SMOKE_OK`
- UTM OpenWrt 24.10.6：`UTM_SMOKE_OK`
- UTM OpenWrt 25.12.3：`UTM_SMOKE_OK`
- UTM OpenWrt 25 卸载检查：`PKG_REMOVED`、`PROC_CLEAN`、`CONFIG_CLEAN`、`NFT_CLEAN`

## 卸载

OpenWrt 23/24：

```sh
opkg remove luci-app-wifidog-v3
```

OpenWrt 25：

```sh
apk del luci-app-wifidog-v3
```

卸载脚本会清理：

- `/etc/config/wifidog_v3`
- `/www/wifidog_v3`
- 独立 uhttpd Portal 进程
- `inet wifidog_v3` nftables 表
- `/tmp/dnsmasq.d/wifidog_v3.conf`
- `dhcp.lan.captive_portal_uri`
- `/tmp/wifidog_v3_ip_sessions`

## 注意事项

- HTTPS 劫持无法避免证书警告，这是 Captive Portal 的常见限制；推荐依赖系统 Captive Portal 探测触发认证页。
- iOS 认证弹窗关闭依赖系统重新探测网络状态，页面会轮询 Captive Portal API 并触发兼容探测作为兜底。
- 如果客户端启用随机 MAC，授权、备注和名单状态会绑定到当前随机 MAC。
