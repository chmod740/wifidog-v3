# WiFiDog V3

WiFiDog V3 是一个面向 OpenWrt 的 LuCI 网络认证系统，用于在路由器上管理待授权设备、白名单、黑名单和授权码，并通过 Captive Portal 控制内网设备访问公网。

## 功能

- 网络设备扫描：从 ARP 表和 DHCP leases 中识别内网设备。
- 待授权设备管理：支持添加白名单、添加黑名单、手动授权和备注。
- 白名单：设备访问内外网不受限制。
- 黑名单：设备可访问内网资源，禁止访问公网资源，且不能自助授权。
- 授权码：支持创建授权码、可用次数、有效期和启停管理。
- 自助认证：未授权设备可通过 Portal 页面输入授权码获取临时访问权限。
- 认证有效期：默认 24 小时，到期后需重新授权。
- Captive Portal 标准兼容：
  - RFC 8908 Captive Portal API
  - RFC 8910 DHCP option 114 / odhcpd captive portal URI
  - Android、iOS、Windows、NetworkManager 常见探测路径兼容
- Passwall2 共存：使用更早优先级的 nftables 规则，尽量在分流规则前完成认证控制。
- Portal 页面配置：后台可切换主题，并配置标题、提示词、按钮文案等。
- 配置备份恢复：支持导入/导出黑白名单、备注、授权码和 Portal 页面设置。
- 安全卸载：卸载时清理 nftables、uhttpd portal 进程、DHCP 广告、运行状态和配置文件。

## 目录结构

```text
.
├── build_ipk.sh
├── luci-app-wifidog-v3/
│   ├── Makefile
│   ├── luasrc/
│   │   ├── controller/
│   │   ├── model/
│   │   └── view/
│   ├── po/
│   └── root/
│       ├── etc/
│       └── www/
└── test/
    ├── e2e_openwrt23_container.py
    ├── utm_smoke.lua
    └── utm_serial.py
```

## 依赖

目标系统：

- OpenWrt 23.05 x86/64
- 已验证 Docker 环境：OpenWrt 23.05.6、OpenWrt 24.10.6
- 已验证 UTM 环境：OpenWrt 23.05.6；OpenWrt 24.10.6 可安装和运行主要功能，但导入配置测试未完全通过

运行依赖：

- firewall4
- nftables-json
- lua
- uhttpd
- libuci-lua
- luci-compat
- luci-lib-jsonc

## 构建 IPK

```sh
./build_ipk.sh
```

构建产物会生成到：

```text
dist/luci-app-wifidog-v3_1.0.0-1_all.ipk
```

`dist/` 是构建输出目录，不纳入 git。

## 安装

将 IPK 上传到 OpenWrt 后执行：

```sh
opkg update
opkg install /tmp/luci-app-wifidog-v3_1.0.0-1_all.ipk
```

安装后在 LuCI 中进入：

```text
服务 -> WiFiDog V3
```

或使用 init 脚本：

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
- `lan_interface`：LAN 接口，留空时自动检测
- `wan_interface`：WAN 接口，留空时自动检测
- `portal_port`：Portal 服务端口，默认 `8080`
- `lan_subnet`：内网网段，留空时自动检测
- `auth_timeout`：授权时长，单位分钟，默认 `1440`
- `portal_theme`：Portal 页面主题
- `portal_title`：Portal 页面标题
- `portal_prompt`：Portal 主提示词
- `portal_hint`：Portal 底部提示词

## 测试

Docker 回归测试：

```sh
python3 test/e2e_openwrt23_container.py
```

UTM smoke 测试脚本：

```sh
lua /tmp/utm_smoke.lua
```

当前主要验证结果：

- OpenWrt 23.05.6 Docker：通过
- OpenWrt 23.05.6 UTM：通过
- OpenWrt 24.10.6 Docker：通过，`90 passed, 0 failed`
- OpenWrt 24.10.6 UTM：安装、服务启动、Portal、nft、禁用和卸载清理通过；配置导入恢复测试失败

## 卸载

```sh
opkg remove luci-app-wifidog-v3
```

卸载脚本会清理：

- package-owned LuCI 文件
- `/etc/config/wifidog_v3`
- `/www/wifidog_v3`
- 独立 uhttpd Portal 进程
- `inet wifidog_v3` nftables 表
- `/tmp/dnsmasq.d/wifidog_v3.conf`
- `dhcp.lan.captive_portal_uri`
- `/tmp/wifidog_v3_ip_sessions`

## 注意事项

- HTTPS 被劫持时浏览器可能显示证书警告，这是 Captive Portal 常见限制；推荐依赖系统 Captive Portal 探测触发认证页。
- iOS 认证弹窗关闭依赖系统重新探测网络状态，页面会轮询 Captive Portal API 并触发兼容探测作为兜底。
- 如果设备启用随机 MAC，授权、备注和名单状态会绑定到当前随机 MAC。
