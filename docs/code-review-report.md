# WiFiDog V3 代码审查与测试补充报告

日期：2026-07-10  
审查范围：LuCI 控制器与页面、Portal CGI、nftables/服务脚本、UCI 配置、IPK/APK 构建与卸载脚本、Docker/UTM 测试代码。

## 结论

初次审查发现的 P0/P1/P2 问题已在 v1.0.3 全部修复，并转为强制通过的自动化测试。当前主流程覆盖待授权、白名单、黑名单、手工授权、授权码、RADIUS PAP、`Session-Timeout`、RFC 8908/8910、Passwall2 前置拦截、配置备份恢复、故障回滚、停用和卸载清理。

最终结果：源码契约测试 `33 passed, 0 failed`；OpenWrt 23.05 Docker 回归 `124 passed, 0 failed`；UTM OpenWrt 24.10.6 IPK 与 OpenWrt 25.12.3 APK 的安装、功能、RADIUS、停用和卸载回归通过。

## v1.0.3 修复状态

- 已删除旧免登录 LuCI 认证路由，独立 Portal 统一执行黑名单和认证开关检查。
- 已修复授权码列表存储型 XSS、数组保护和设备接口 MAC/数值校验。
- 授权码校验、设备授权和次数递增现在使用跨进程锁与一次 UCI 提交。
- 授权过期改为 `pending`，保留备注、主机名和 UA。
- nftables 或 Portal 启动失败会回滚规则和 DHCP/RA 广告。
- HTTPS/443 明确采用未授权阻断，不再把明文 Portal 重定向到 TLS 连接。
- 已加入 16 KiB 请求限制、安全响应头、512 KiB 日志轮转、会话容量限制和敏感临时文件权限保护。
- 备份默认排除 RADIUS 密钥，管理员可显式选择包含敏感配置。

## 新增测试

新增 `test/test_source_contracts.py`，共 33 条快速契约测试，现已全部强制通过，覆盖打包一致性、输入与输出安全、认证事务、服务回滚、日志限制、HTTPS 行为和卸载清理。

扩展 `test/e2e_openwrt23_container.py` 至 124 个实际 Docker 断言，新增重点包括：

- 运行日志按字面关键词筛选。
- 授权码大小写不敏感的重复检测。
- 单码授权时长为 0 时拒绝且不留下半成品。
- 单码时长留空时正确复用系统默认值。
- 错误应用备份、畸形 JSON 均不改变已提交配置。
- 停用和卸载后精确恢复其他组件原有的 RFC 8910 `captive_portal_uri`。
- 未知 MAC 不消耗授权码，10 路并发单次码只成功一次。
- 授权过期保留备注、请求体 413、日志轮转、安全响应头和启动失败回滚。
- 默认备份脱敏，显式选择后完整导出 RADIUS 共享密钥。

执行结果：

```text
python3 test/test_source_contracts.py
Ran 33 tests
OK

python3 test/e2e_openwrt23_container.py
Result: 124 passed, 0 failed
```

## 初始 P0 发现（v1.0.3 已修复）

### 1. 公开旧 Portal 入口可绕过当前访问控制并存在反射型 XSS

位置：`luci-app-wifidog-v3/luasrc/controller/wifidog_v3.lua:72`、`:1512`、`:1557`。

控制器注册了免登录的 `/cgi-bin/luci/wifidog_v3/portal`。该旧处理器没有检查：

- `settings.enabled`
- `auth_code_enabled`
- 设备是否为黑名单
- 当前启用的认证方式

黑名单设备按设计仍可访问路由器内网地址，因此可以直接向该入口提交授权码；旧处理器会删除原黑名单记录并写入 `authorized`。此外，`redirect_url` 和错误信息直接拼接进 HTML，没有调用 HTML 转义函数，可形成路由器同源的反射型 XSS。

建议：删除公开 LuCI 入口及旧 `action_portal()`/`render_portal_page()`，只保留独立 uhttpd CGI。若必须兼容旧 URL，应仅做固定 302 跳转到独立 Portal，且禁止处理认证 POST。

## 初始 P1 发现（v1.0.3 已修复）

### 2. 授权码管理页存在存储型 XSS

位置：`luci-app-wifidog-v3/luasrc/view/wifidog_v3/auth_codes.htm:58` 附近。

授权码可由管理页或备份导入，允许包含 `<`、引号等字符。页面把 `c.code` 直接拼入 `innerHTML`，并拼入内联 `onclick`。导入不可信备份后，打开授权码页面可能在 LuCI 管理员会话中执行脚本。

建议：像设备页面一样统一调用 `esc()`，移除内联事件，把授权码放入 `textContent`/`dataset` 后使用事件委托。服务端也应限制授权码字符集，例如 `[A-Z0-9_-]{1,64}`。

### 3. 服务启动失败没有回滚，可能出现“已阻断但无 Portal”

位置：`luci-app-wifidog-v3/root/etc/init.d/wifidog_v3:602-604`。

启动顺序为 DHCP/RA 广告、nftables、uhttpd。若 nftables 或 uhttpd 启动失败，函数直接返回，但先前成功的广告或防火墙规则不会清理。最危险的状态是 nftables 已拦截公网、Portal 进程却未启动。

建议：把启动过程改成带失败清理的事务；任何一步失败都调用 `stop_portal_server`、`cleanup_firewall`、`cleanup_captive_portal_advertisement` 和 `stop_expiry_worker`。

### 4. 授权过期会丢失备注和 UA

位置：`luci-app-wifidog-v3/root/etc/init.d/wifidog_v3:566-583`。

`check_device_expiry()` 直接删除整个设备 section。设备重新出现在待授权列表时只来自 ARP/DHCP，之前按 MAC 保存的备注、主机名和 UA 均丢失，违背“备注跟 MAC 绑定并跨名单保留”的要求。

建议：过期时把 section 转为 `pending`，只清空 `auth_expiry`、`auth_source`、`auth_code`、`radius_user`，保留 MAC、备注、主机名和 UA。

### 5. 授权码先计数后确认客户端，且并发计数不安全

位置：`luci-app-wifidog-v3/root/www/wifidog_v3/cgi-bin/wifidog_v3/portal:909-949`、`:1591-1599`。

`validate_auth_code()` 先增加 `used_count` 并提交，随后才判断能否识别客户端 MAC。MAC 获取失败或设备写入失败时，授权码次数仍被消耗。多个并发请求还可能同时读取同一 `used_count`，使单次码被使用多次。

建议：先确认 MAC，再在互斥锁内完成“校验次数、写授权设备、增加次数、提交”。失败时不得增加计数。Docker 中增加 10 到 50 个并发 POST 的压力回归。

### 6. 当前 HTTPS 测试不等于真实 HTTPS 劫持

位置：`luci-app-wifidog-v3/root/etc/init.d/wifidog_v3:545-546`、`test/e2e_openwrt23_container.py:300` 附近。

现有测试访问的是 `http://WAN:443/`，只是明文 HTTP 使用 443 端口。真实 `https://` 首先进行 TLS 握手，而 Portal uhttpd 只提供明文 HTTP，因此会握手失败；即使部署自签证书，也会遇到证书域名不匹配/HSTS，无法透明展示认证页。

建议：产品行为应明确为“HTTPS 阻断，不保证展示 Portal”，依靠 RFC 8910、系统探测 URL 和 HTTP 请求唤起认证页。新增真实 TLS 测试，断言未授权时 HTTPS 不可访问、授权后恢复，而不是断言返回 Portal HTML。

## 初始 P2 发现（v1.0.3 已修复）

### 7. 同时关闭两种认证方式时，代码会自动重新启用授权码

位置：Portal CGI `:1164-1168`、`:1543-1547`。

这与后台“可启用一种或多种认证”的语义不一致。两者均关闭时应显示“管理员未启用自助认证”，只允许后台手工授权。

### 8. LuCI 设备写接口没有统一校验 MAC/IP/数值范围

位置：控制器 `:923-1095`、`:1284-1340`。

导入流程有 `normalize_mac()`，但添加白名单、黑名单、授权、备注接口只判断非空。异常 MAC 可生成异常 UCI section，极端值可能覆盖 `settings` section。`max_uses`、`expiry_days` 也可接收负数、小数和超大值。

建议：所有入口复用统一校验器；MAC 必须标准化为 6 字节，IP 使用合法 IPv4/IPv6 校验，次数和天数设置明确上下限。

### 9. POST 请求体、运行日志和短期会话文件没有容量上限

位置：Portal CGI `:1005-1011`，三个组件的 `append_runtime_log()`。

缺少请求体上限会允许过大表单占用 Lua/uhttpd 资源；`/var/log/wifidog_v3.log` 无轮转，在 OpenWrt 常见的 `/var -> /tmp` 布局下会持续消耗内存。IP 会话文件也缺少总条目限制和文件锁。

建议：POST 限制到 8-16 KiB，日志按 256-512 KiB 轮转并保留 1-2 份，会话设置最大条目数并使用原子替换。

### 10. 授权码列表缺少数组保护

位置：`auth_codes.htm:45-53`。

设备列表已使用 `Array.isArray()`，授权码页面仍直接调用 `data.codes.forEach()`。异常响应会使页面停在加载/报错状态。

建议：统一为 `var codes = Array.isArray(data.codes) ? data.codes : [];`，并为所有 `fetch()` 检查 HTTP 状态和 JSON 解析错误。

### 11. RADIUS MD5 临时文件和备份密钥处理可加强

位置：Portal CGI `:438-458`，控制器 `settings_keys` 中的 `radius_secret`。

RADIUS 计算 MD5 时把包含共享密钥的数据短暂写入 `/tmp`，未显式设置 0600；配置导出也默认包含明文共享密钥。两者均属于敏感数据暴露面。

建议：优先使用已允许的 `lua-openssl` 在内存中计算摘要；至少设置 `umask 077` 并保证异常路径删除临时文件。导出时明确提示包含密钥，或提供“包含/不包含敏感信息”选项。

### 12. 测试目录中存在大量过期脚本

`test/complete_test.py`、`test/test_automation*.py`、`test/run_tests.sh` 等仍以 iptables、ipset、lighttpd 为主，与当前 nftables + uhttpd 实现不一致，可能产生错误结论。当前可信主线应以：

- `test/test_source_contracts.py`
- `test/e2e_openwrt23_container.py`
- `test/utm_smoke.lua`
- `test/utm_radius_check.sh`

为准。建议给旧脚本加 `legacy` 标记或删除，建立一个统一入口输出 JSON/JUnit 报告。

## 进一步测试建议

以下场景尚未在本轮自动执行，建议按优先级补充：

1. UTM 中使用真实 iPhone、Android、Windows、macOS，验证 DHCP option 114、自动弹窗、认证后关闭和 Wi-Fi 重连。
2. 真实 `https://`、HSTS、QUIC/HTTP3、DoH/DoT 的未授权阻断和授权恢复。
3. 真实 Passwall2 国内外分流、TCP/UDP 节点、规则模式变化和 Passwall2 重启后的共存。
4. 10-50 并发授权码请求，验证 `max_uses=1` 只能成功一次。
5. uhttpd 缺失、端口占用、nft 规则错误、磁盘只读时的启动失败回滚。
6. `/16`、非连续掩码、多 LAN/VLAN、访客网络、PPPoE、多 WAN 和 IPv6-only/双栈。
7. 断电/强制重启发生在 UCI 提交、备份恢复和授权计数中间时的数据一致性。
8. 备注、主机名、授权码和备份字段的引号、反斜杠、Unicode、HTML、超长输入和模糊测试。
9. OpenWrt 23/24 IPK 与 25 APK 的安装、升级、降级、保留配置、停用和卸载矩阵。
10. 长时间运行 7-30 天，观察日志、UCI 写入频率、内存、进程和 nftables 规则稳定性。

## 建议整改顺序

1. 删除旧公开 LuCI Portal，修复两处 XSS。
2. 实现服务启动失败回滚，补充端口占用/缺依赖故障注入测试。
3. 授权过期改为 pending 并保留备注/UA。
4. 授权码计数加锁并调整事务顺序。
5. 补齐输入校验、请求/日志容量限制。
6. 清理旧测试，执行 UTM 真机与 OpenWrt 23/24/25 矩阵。
