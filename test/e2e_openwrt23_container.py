#!/usr/bin/env python3
"""End-to-end checks for luci-app-wifidog-v3 in the local OpenWrt 23.05 container.

Expected containers:
  - openwrt-test-v3: router, LAN 10.88.0.2, WAN 10.89.0.2
  - test-client: LAN client, 10.88.0.10
  - wan-server: simulated WAN HTTP server, 10.89.0.10
"""
from __future__ import annotations

import atexit
import json
import os
from pathlib import Path
import subprocess
import sys
import time


ROUTER = "openwrt-test-v3"
CLIENT = "test-client"
WAN = "wan-server"
RADIUS = "wifidog-radius-v3"
RADIUS_IP = "10.89.0.20"
RADIUS_SECRET = "testing123"
WAN_URL = "http://10.89.0.10/"
PORTAL_URL = "http://10.88.0.2:8080/portal"
CAPTIVE_API_URL = "http://10.88.0.2:8080/captive-portal/api"
PREEXISTING_CAPTIVE_URI = "http://10.88.0.2:9090/existing-captive-api"
REPO_ROOT = Path(__file__).resolve().parents[1]
PKG_MANAGER = os.environ.get("PKG_MANAGER", "opkg")

passed = 0
failed = 0
atexit.register(lambda: subprocess.run(["docker", "rm", "-f", RADIUS], capture_output=True, text=True, timeout=20))


def run(args: list[str], check: bool = False, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, input=input_text, text=True, capture_output=True, timeout=20, check=check)


def dexec(container: str, *cmd: str, check: bool = False, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    base = ["docker", "exec"]
    if input_text is not None:
        base.append("-i")
    return run([*base, container, *cmd], check=check, input_text=input_text)


def dsh(container: str, script: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    return dexec(container, "sh", "-c", script, check=check)


def ok(name: str, condition: bool, detail: str = "") -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"[PASS] {name}")
    else:
        failed += 1
        print(f"[FAIL] {name} {detail}".rstrip())


def client_get(url: str, timeout: int = 5) -> subprocess.CompletedProcess[str]:
    return dexec(CLIENT, "wget", "-T", str(timeout), "-O-", "-q", url)


def client_get_with_ua(url: str, user_agent: str, timeout: int = 5) -> subprocess.CompletedProcess[str]:
    return dexec(CLIENT, "wget", "-T", str(timeout), "-O-", "-q", "-U", user_agent, url)


def client_post(url: str, data: str) -> subprocess.CompletedProcess[str]:
    return dexec(CLIENT, "wget", "-O-", "-q", f"--post-data={data}", url)


def router_lua(script: str) -> subprocess.CompletedProcess[str]:
    return dexec(ROUTER, "lua", "-", input_text=script)


def package_installed() -> bool:
    if PKG_MANAGER == "apk":
        return dexec(ROUTER, "apk", "info", "-e", "luci-app-wifidog-v3").returncode == 0
    return "luci-app-wifidog-v3" in dexec(ROUTER, "opkg", "list-installed").stdout


def remove_package() -> subprocess.CompletedProcess[str]:
    if PKG_MANAGER == "apk":
        return dexec(ROUTER, "apk", "del", "luci-app-wifidog-v3", check=True)
    return dexec(ROUTER, "opkg", "remove", "luci-app-wifidog-v3", check=True)


def client_mac() -> str:
    out = run(["docker", "inspect", "--format", "{{json .NetworkSettings.Networks}}", CLIENT], check=True).stdout
    networks = json.loads(out)
    for net in networks.values():
        if net.get("IPAddress") == "10.88.0.10":
            return net["MacAddress"].upper()
    raise RuntimeError("client LAN MAC not found")


def router_iface_for_ip(ip: str, fallback: str) -> str:
    out = dsh(ROUTER, "ip -o -4 addr show").stdout
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[3].split("/", 1)[0] == ip:
            return parts[1]
    return fallback


def start_radius() -> None:
    conf_dir = Path("/tmp/wifidog_v3_radius")
    conf_dir.mkdir(parents=True, exist_ok=True)
    (conf_dir / "clients.conf").write_text(f"""
client openwrt {{
    ipaddr = 10.89.0.2
    secret = {RADIUS_SECRET}
}}

client localhost {{
    ipaddr = 127.0.0.1
    secret = {RADIUS_SECRET}
}}
""".strip() + "\n")
    (conf_dir / "users").write_text("""
raduser Cleartext-Password := "radpass"
    Session-Timeout := 300
""".lstrip())

    run(["docker", "rm", "-f", RADIUS])
    run([
        "docker", "run", "-d",
        "--name", RADIUS,
        "--platform", "linux/amd64",
        "--network", "wifidog-wan-net",
        "--ip", RADIUS_IP,
        "-v", f"{conf_dir / 'clients.conf'}:/etc/freeradius/clients.conf:ro",
        "-v", f"{conf_dir / 'users'}:/etc/freeradius/users:ro",
        "freeradius/freeradius-server:latest",
        "-f",
    ], check=True)
    for _ in range(20):
        ready = dexec(RADIUS, "radtest", "raduser", "radpass", "127.0.0.1", "0", RADIUS_SECRET)
        if "Access-Accept" in ready.stdout:
            return
        time.sleep(0.5)
    raise RuntimeError("FreeRADIUS test container did not become ready")


def stop_radius() -> None:
    run(["docker", "rm", "-f", RADIUS])


def setup(mac: str) -> None:
    start_radius()
    dsh(ROUTER, "mkdir -p /var/lock /www")
    dsh(WAN, "mkdir -p /www && printf %s WAN_OK > /www/index.html")
    dexec(WAN, "killall", "uhttpd")
    run(["docker", "exec", "-d", WAN, "uhttpd", "-f", "-p", "0.0.0.0:80", "-h", "/www"])

    lan_iface = router_iface_for_ip("10.88.0.2", "eth0")
    wan_iface = router_iface_for_ip("10.89.0.2", "eth1")

    network_cfg = f"""cat > /etc/config/network <<'EOF'
config interface 'lan'
	option device '{lan_iface}'
	option ipaddr '10.88.0.2'
	option netmask '255.255.255.0'

config interface 'wan'
	option device '{wan_iface}'
	option ipaddr '10.89.0.2'
	option netmask '255.255.255.0'
EOF
"""
    dsh(ROUTER, network_cfg, check=True)

    dsh(ROUTER, f"uci -q delete wifidog_v3.{mac.replace(':', '_').lower()} 2>/dev/null; uci -q delete wifidog_v3.{mac.replace(':', '_').upper()} 2>/dev/null; uci -q commit wifidog_v3")

    today = time.strftime("%Y-%m-%d")
    batch = f"""
set wifidog_v3.settings.enabled=1
set wifidog_v3.settings.lan_interface={lan_iface}
set wifidog_v3.settings.wan_interface={wan_iface}
set wifidog_v3.settings.portal_port=8080
set wifidog_v3.settings.lan_subnet=10.88.0.0/24
set wifidog_v3.settings.auth_code_enabled=1
set wifidog_v3.settings.auth_timeout=1440
set wifidog_v3.settings.radius_enabled=1
set wifidog_v3.settings.radius_server=10.89.0.20
set wifidog_v3.settings.radius_port=1812
set wifidog_v3.settings.radius_secret=testing123
set wifidog_v3.settings.radius_nas_id=wifidog-v3-test
set wifidog_v3.settings.radius_timeout=2
set wifidog_v3.settings.radius_retries=2
set wifidog_v3.auth_VIP2026=authcode
set wifidog_v3.auth_VIP2026.code=VIP2026
set wifidog_v3.auth_VIP2026.max_uses=20
set wifidog_v3.auth_VIP2026.used_count=0
set wifidog_v3.auth_VIP2026.expiry_days=30
set wifidog_v3.auth_VIP2026.auth_minutes=5
set wifidog_v3.auth_VIP2026.created_date={today}
set wifidog_v3.auth_VIP2026.enabled=1
set wifidog_v3.auth_DEFAULT=authcode
set wifidog_v3.auth_DEFAULT.code=DEFAULT1440
set wifidog_v3.auth_DEFAULT.max_uses=20
set wifidog_v3.auth_DEFAULT.used_count=0
set wifidog_v3.auth_DEFAULT.expiry_days=30
set wifidog_v3.auth_DEFAULT.created_date={today}
set wifidog_v3.auth_DEFAULT.enabled=1
set wifidog_v3.auth_ONCE=authcode
set wifidog_v3.auth_ONCE.code=ONCE123
set wifidog_v3.auth_ONCE.max_uses=1
set wifidog_v3.auth_ONCE.used_count=1
set wifidog_v3.auth_ONCE.expiry_days=30
set wifidog_v3.auth_ONCE.created_date={today}
set wifidog_v3.auth_ONCE.enabled=1
set wifidog_v3.auth_EXPIRED=authcode
set wifidog_v3.auth_EXPIRED.code=EXPIRED1
set wifidog_v3.auth_EXPIRED.max_uses=20
set wifidog_v3.auth_EXPIRED.used_count=0
set wifidog_v3.auth_EXPIRED.expiry_days=1
set wifidog_v3.auth_EXPIRED.created_date=2026-01-01
set wifidog_v3.auth_EXPIRED.enabled=1
set wifidog_v3.auth_DISABLED=authcode
set wifidog_v3.auth_DISABLED.code=DISABLED1
set wifidog_v3.auth_DISABLED.max_uses=20
set wifidog_v3.auth_DISABLED.used_count=0
set wifidog_v3.auth_DISABLED.expiry_days=30
set wifidog_v3.auth_DISABLED.created_date={today}
set wifidog_v3.auth_DISABLED.enabled=0
set wifidog_v3.auth_RACE=authcode
set wifidog_v3.auth_RACE.code=RACEONCE
set wifidog_v3.auth_RACE.max_uses=1
set wifidog_v3.auth_RACE.used_count=0
set wifidog_v3.auth_RACE.expiry_days=30
set wifidog_v3.auth_RACE.auth_minutes=5
set wifidog_v3.auth_RACE.created_date={today}
set wifidog_v3.auth_RACE.enabled=1
commit wifidog_v3
"""
    dexec(ROUTER, "uci", "batch", input_text=batch, check=True)
    dsh(ROUTER, f"nft add table ip wifidog_v3_test 2>/dev/null || true; nft 'add chain ip wifidog_v3_test postrouting {{ type nat hook postrouting priority 100; policy accept; }}' 2>/dev/null || true; nft add rule ip wifidog_v3_test postrouting ip saddr 10.88.0.0/24 oifname {wan_iface} masquerade 2>/dev/null || true")
    dexec(CLIENT, "ip", "route", "replace", "default", "via", "10.88.0.2", "dev", "eth0", check=True)
    dexec(CLIENT, "ping", "-c", "1", "10.88.0.2", check=True)
    dexec(ROUTER, "/etc/init.d/wifidog_v3", "restart", check=True)
    time.sleep(0.8)


def set_device(mac: str, dev_type: str, expiry: str = "0", source: str = "", note: str = "") -> None:
    section = mac.replace(":", "_").lower()
    extra = ""
    if source:
        extra += f"set wifidog_v3.{section}.auth_source={source}\n"
    if note:
        extra += f"set wifidog_v3.{section}.note={note}\n"
    batch = f"""
set wifidog_v3.{section}=device
set wifidog_v3.{section}.mac={mac}
set wifidog_v3.{section}.ip=10.88.0.10
set wifidog_v3.{section}.type={dev_type}
set wifidog_v3.{section}.auth_expiry={expiry}
{extra}\
commit wifidog_v3
"""
    dexec(ROUTER, "uci", "batch", input_text=batch, check=True)
    dexec(ROUTER, "/etc/init.d/wifidog_v3", "reload", check=True)
    time.sleep(0.2)


def main() -> int:
    mac = client_mac()
    setup(mac)

    ok("Package installed", package_installed())
    ok("No package uhttpd portal config", dexec(ROUTER, "uci", "-q", "get", "uhttpd.wifidog_v3").returncode != 0)
    ok("uhttpd portal process running", dsh(ROUTER, "pid=$(cat /var/run/wifidog_v3_portal.pid 2>/dev/null); [ -n \"$pid\" ] && kill -0 \"$pid\" 2>/dev/null && ps w | grep -q \"^[[:space:]]*$pid[[:space:]].*[u]httpd.*\\/www\\/wifidog_v3\"").returncode == 0)
    ok("No LuaSocket portal process", dsh(ROUTER, "ps w | grep -q '[p]ortal_server.lua'").returncode != 0)
    ok("Portal page reachable", "网络认证" in client_get(PORTAL_URL).stdout)
    portal_html = client_get(PORTAL_URL).stdout
    ok("Portal page offers auth code and RADIUS methods", "授权码" in portal_html and "RADIUS用户名" in portal_html and "auth_method" in portal_html)
    iphone_ua = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
    ua_request = client_get_with_ua(PORTAL_URL, iphone_ua)
    section = mac.replace(":", "_").lower()
    ua_summary = dsh(ROUTER, f"uci -q get wifidog_v3.{section}.ua_summary").stdout.strip()
    ua_raw = dsh(ROUTER, f"uci -q get wifidog_v3.{section}.user_agent").stdout.strip()
    ua_type = dsh(ROUTER, f"uci -q get wifidog_v3.{section}.ua_device_type").stdout.strip()
    ok("Portal records and parses client User-Agent", ua_request.returncode == 0 and "iPhone" in ua_summary and "iOS 17.5" in ua_summary and "Safari 17.5" in ua_summary and ua_type == "手机" and ua_raw == iphone_ua, ua_summary + ua_raw + ua_type)
    pending_api = client_get(CAPTIVE_API_URL).stdout
    ok("RFC8908 API reports pending client captive", '"captive":true' in pending_api and '"user-portal-url":"http://10.88.0.2:8080/portal"' in pending_api, pending_api)
    dhcp_advert = dexec(ROUTER, "cat", "/tmp/dnsmasq.d/wifidog_v3.conf").stdout
    ok("RFC8910 DHCP option 114 advertises API URL", "dhcp-option=114,http://10.88.0.2:8080/captive-portal/api" in dhcp_advert, dhcp_advert)
    odhcpd_advert = dexec(ROUTER, "uci", "-q", "get", "dhcp.lan.captive_portal_uri")
    ok("RFC8910 odhcpd DHCP/RA advertises API URL", odhcpd_advert.returncode == 0 and odhcpd_advert.stdout.strip() == "http://10.88.0.2:8080/captive-portal/api", odhcpd_advert.stdout + odhcpd_advert.stderr)
    dsh(ROUTER, "printf '%s\\n' '1893456000 de:ad:be:ef:67:68 10.88.0.66 lease-only-phone *' >> /tmp/dhcp.leases")
    dsh(ROUTER, "printf '%s\\n' \"1893456000 de:ad:be:ef:67:69 10.88.0.67 kid's-phone *\" >> /tmp/dhcp.leases")
    scan = router_lua('''
local http = require "luci.http"
function http.prepare_content(_) end
function http.write_json(t)
	for _, d in ipairs(t.devices or {}) do
		print((d.mac or "") .. "|" .. (d.ip or "") .. "|" .. (d.hostname or ""))
	end
end
local c = require "luci.controller.wifidog_v3"
c.action_scan_devices()
''')
    ok("Scan includes DHCP lease-only devices", "DE:AD:BE:EF:67:68|10.88.0.66|lease-only-phone" in scan.stdout, scan.stdout + scan.stderr)
    ok("Scan tolerates quote-heavy hostnames", "DE:AD:BE:EF:67:69|10.88.0.67|kid's-phone" in scan.stdout, scan.stdout + scan.stderr)
    ok("Pending WAN HTTP is captive", "网络认证" in client_get(WAN_URL).stdout)
    ok("Captive probe gets portal page", "网络认证" in client_get(WAN_URL + "generate_204").stdout)
    ok("Apple captive probe gets portal page", "网络认证" in client_get(WAN_URL + "hotspot-detect.html").stdout)
    ok("Windows NCSI probe gets portal page", "网络认证" in client_get(WAN_URL + "ncsi.txt").stdout)
    pending_443 = client_get("http://10.89.0.10:443/", timeout=3)
    ok("Pending TCP 443 is blocked instead of redirected to plaintext portal", pending_443.returncode != 0 and "网络认证" not in pending_443.stdout, pending_443.stdout + pending_443.stderr)
    ok("Pending LAN resource reachable", "网络认证" in client_get(PORTAL_URL).stdout)
    nft_rules = dexec(ROUTER, "nft", "-nn", "list", "table", "inet", "wifidog_v3").stdout
    ok("Early filter is before Passwall2 mangle", "chain early_filter" in nft_rules and ("priority -310" in nft_rules or "priority raw - 10" in nft_rules))
    ok("Early nat is before Passwall2 dstnat", "chain early_nat" in nft_rules and "priority -199" in nft_rules)
    ok("DHCP discover is allowed before captive filtering", "udp sport 68 udp dport 67 return" in nft_rules)
    ok("DHCP offer is allowed before captive filtering", "udp sport 67 udp dport 68 return" in nft_rules)
    dsh(ROUTER, "nft delete table inet passwall2_mock 2>/dev/null; nft add table inet passwall2_mock; nft 'add chain inet passwall2_mock dstnat { type nat hook prerouting priority dstnat - 1; policy accept; }'; nft add rule inet passwall2_mock dstnat iifname eth0 tcp dport 80 redirect to :18081", check=True)
    ok("Pending HTTP beats mock Passwall2 dstnat", "网络认证" in client_get(WAN_URL).stdout)
    dsh(ROUTER, "nft delete table inet passwall2_mock 2>/dev/null")

    ua_whitelist = router_lua(f'''
local http = require "luci.http"
local values = {{ mac = "{mac}", ip = "10.88.0.10", hostname = "ua-phone", note = "" }}
function http.formvalue(k) return values[k] end
function http.prepare_content(_) end
function http.write_json(t) if t.success then print("success") else print("fail:" .. (t.message or "")) end end
local c = require "luci.controller.wifidog_v3"
c.action_add_whitelist()
''')
    ua_whitelist_summary = dsh(ROUTER, f"uci -q get wifidog_v3.{section}.ua_summary").stdout.strip()
    ua_remove = router_lua(f'''
local http = require "luci.http"
local values = {{ mac = "{mac}" }}
function http.formvalue(k) return values[k] end
function http.prepare_content(_) end
function http.write_json(t) if t.success then print("success") else print("fail:" .. (t.message or "")) end end
local c = require "luci.controller.wifidog_v3"
c.action_remove_device()
''')
    ua_pending_summary = dsh(ROUTER, f"uci -q get wifidog_v3.{section}.ua_summary").stdout.strip()
    ok("Device User-Agent info survives whitelist and pending transitions", "success" in ua_whitelist.stdout and "success" in ua_remove.stdout and ua_whitelist_summary == ua_summary and ua_pending_summary == ua_summary, ua_whitelist.stdout + ua_remove.stdout + ua_whitelist_summary + ua_pending_summary)

    auth_view = (REPO_ROOT / "luci-app-wifidog-v3/luasrc/view/wifidog_v3/auth_codes.htm").read_text()
    ok("Auth code page generate button is non-submit", 'type="button" class="wifidog-btn wifidog-btn-primary"' in auth_view)
    ok("Auth code page exposes per-code duration input", "new-auth-minutes" in auth_view and "auth_minutes" in auth_view and "授权后有效时长" in auth_view)
    devices_view = (REPO_ROOT / "luci-app-wifidog-v3/luasrc/view/wifidog_v3/devices.htm").read_text()
    ok("Device page avoids inline onclick row handlers", 'onclick="addWhitelist' not in devices_view and "addEventListener('click'" in devices_view)
    ok("Authorized list guards empty/non-array responses", "Array.isArray(data.devices)" in devices_view)
    ok("Pending devices have explicit save-note button", "保存备注" in devices_view and "saveNote(dev.mac, noteId, dev.ip" in devices_view)
    ok("Device pages display parsed User-Agent information", "设备信息" in devices_view and "addDeviceInfoCell" in devices_view and "ua_summary" in devices_view)
    ok("Auto refresh skips active or unsaved notes", "setInterval(autoRefresh, 15000)" in devices_view and "isEditingNote()" in devices_view and "hasUnsavedNote()" in devices_view)
    ok("Authorized devices can move to whitelist/blacklist", devices_view.count("addWhitelist(dev.mac") >= 2 and devices_view.count("addBlacklist(dev.mac") >= 2)
    shared_style = (REPO_ROOT / "luci-app-wifidog-v3/luasrc/view/wifidog_v3/styles.htm").read_text()
    styled_views = [
        "devices.htm",
        "whitelist.htm",
        "blacklist.htm",
        "auth_codes.htm",
        "backup.htm",
        "logs.htm",
        "status.htm",
    ]
    shared_style_refs = [
        (REPO_ROOT / f"luci-app-wifidog-v3/luasrc/view/wifidog_v3/{name}").read_text()
        for name in styled_views
    ]
    ok("LuCI pages share common polished styles", all("<%+wifidog_v3/styles%>" in text for text in shared_style_refs) and "wifidog-table-wrap" in shared_style and "td.wifidog-actions" in shared_style, shared_style[:300])
    backup_view = (REPO_ROOT / "luci-app-wifidog-v3/luasrc/view/wifidog_v3/backup.htm").read_text()
    logs_view = (REPO_ROOT / "luci-app-wifidog-v3/luasrc/view/wifidog_v3/logs.htm").read_text()
    controller = (REPO_ROOT / "luci-app-wifidog-v3/luasrc/controller/wifidog_v3.lua").read_text()
    ok("Backup page has import and export controls", "导出配置" in backup_view and "恢复配置" in backup_view and "export_config" in controller and "import_config" in controller)
    ok("Runtime logs page has log viewer controls", "运行日志" in controller and "runtime_logs" in controller and "clear_runtime_logs" in controller and "清空本系统日志" in logs_view and "暂停自动刷新" in logs_view)
    settings_model = (REPO_ROOT / "luci-app-wifidog-v3/luasrc/model/cbi/wifidog_v3/settings.lua").read_text()
    ok("Settings page exposes portal theme and prompt controls", "Portal页面" in settings_model and "portal_theme" in settings_model and "portal_prompt" in settings_model and "portal_hint" in settings_model)
    ok("Backup includes portal page customization settings", "portal_theme" in controller and "portal_prompt" in controller and "portal_button_text" in controller)
    init_script = (REPO_ROOT / "luci-app-wifidog-v3/root/etc/init.d/wifidog_v3").read_text()
    build_script = (REPO_ROOT / "build_ipk.sh").read_text()
    portal_cgi = (REPO_ROOT / "luci-app-wifidog-v3/root/www/wifidog_v3/cgi-bin/wifidog_v3/portal").read_text()
    makefile = (REPO_ROOT / "luci-app-wifidog-v3/Makefile").read_text()
    ok("Portal uses uhttpd instead of LuaSocket", "/usr/sbin/uhttpd" in init_script and "PORTAL_CGI" in init_script and "require(\"socket\")" not in portal_cgi)
    ok("Package depends on uhttpd and luasocket for portal/RADIUS", "uhttpd" in build_script and "luasocket" in build_script and "+uhttpd" in makefile and "+luasocket" in makefile)
    ok("Portal implements configurable themes and copy", "portal_theme_css" in portal_cgi and "portal_title" in portal_cgi and "portal_prompt" in portal_cgi and "portal_button_text" in portal_cgi)
    ok("Portal success polls captive API before iOS close fallback", "认证成功" in portal_cgi and "pollCaptiveApi" in portal_cgi and "captive.apple.com/hotspot-detect.html" in portal_cgi and "window.close" in portal_cgi and "window.location.replace" not in portal_cgi)
    ok("Portal success page displays authorization validity", "auth-validity" in portal_cgi and "有效期至" in portal_cgi and "expires_at_text" in portal_cgi and "valid_text" in portal_cgi)
    ok("Portal keeps short IP session cache for captive re-probes", "IP_SESSION_FILE" in portal_cgi and "remember_ip_session" in portal_cgi and "resolve_client_device" in portal_cgi)
    ok("Portal implements RFC8908 API and legacy probe success", "application/captive+json" in portal_cgi and "captive_api_json" in portal_cgi and "generate_204" in portal_cgi and "Microsoft NCSI" in portal_cgi)
    ok("Portal records and parses User-Agent metadata", "record_client_user_agent" in portal_cgi and "parse_user_agent" in portal_cgi and "ua_summary" in portal_cgi)
    ok("Init advertises RFC8910 DHCP/RA options and cleans them", "dhcp-option=114" in init_script and "captive_portal_uri" in init_script and "cleanup_captive_portal_advertisement" in init_script)
    ok("Runtime events are written to app log", "LOG_FILE=\"/var/log/wifidog_v3.log\"" in init_script and "append_runtime_log" in controller and "append_runtime_log" in portal_cgi)
    direct_headers = dsh(ROUTER, "REQUEST_METHOD=GET REQUEST_URI=/captive-portal/api REMOTE_ADDR=10.88.0.251 /www/wifidog_v3/cgi-bin/wifidog_v3/portal")
    ok("Portal responses include browser security headers", "X-Content-Type-Options: nosniff" in direct_headers.stdout and "Content-Security-Policy:" in direct_headers.stdout and "Referrer-Policy: no-referrer" in direct_headers.stdout, direct_headers.stdout + direct_headers.stderr)
    oversized = dsh(ROUTER, "REQUEST_METHOD=POST REQUEST_URI=/portal CONTENT_LENGTH=20000 REMOTE_ADDR=10.88.0.251 /www/wifidog_v3/cgi-bin/wifidog_v3/portal </dev/null")
    ok("Portal rejects oversized POST bodies with 413", "Status: 413 Payload Too Large" in oversized.stdout and "请求内容过大" in oversized.stdout, oversized.stdout + oversized.stderr)
    empty_authorized = router_lua('''
local http = require "luci.http"
function http.prepare_content(_) end
function http.write(s) print(s) end
local c = require "luci.controller.wifidog_v3"
c.action_list_authorized()
''')
    ok("Authorized empty list returns JSON array", '"devices":[]' in empty_authorized.stdout, empty_authorized.stdout + empty_authorized.stderr)
    runtime_logs = router_lua('''
local http = require "luci.http"
local jsonc = require "luci.jsonc"
function http.formvalue(k) if k == "lines" then return "50" elseif k == "source" then return "app" end end
function http.prepare_content(_) end
function http.write_json(t) print(jsonc.stringify(t)) end
os.execute("mkdir -p /var/log && printf '%s\\n' '2026-05-27 10:00:00 [test] Docker runtime log line' >> /var/log/wifidog_v3.log")
local c = require "luci.controller.wifidog_v3"
c.action_runtime_logs()
''')
    ok("Runtime logs endpoint returns app log lines", '"success":true' in runtime_logs.stdout and "Docker runtime log line" in runtime_logs.stdout, runtime_logs.stdout + runtime_logs.stderr)
    filtered_logs = router_lua('''
local http = require "luci.http"
local jsonc = require "luci.jsonc"
function http.formvalue(k)
	if k == "lines" then return "1" end
	if k == "source" then return "app" end
	if k == "query" then return "needle-only" end
end
function http.prepare_content(_) end
function http.write_json(t) print(jsonc.stringify(t)) end
os.execute("mkdir -p /var/log && printf '%s\\n' 'noise-line' 'needle-only-line' >> /var/log/wifidog_v3.log")
local c = require "luci.controller.wifidog_v3"
c.action_runtime_logs()
''')
    ok("Runtime logs endpoint filters literal queries", "needle-only-line" in filtered_logs.stdout and "noise-line" not in filtered_logs.stdout, filtered_logs.stdout + filtered_logs.stderr)
    clear_logs = router_lua('''
local http = require "luci.http"
function http.formvalue(_) return nil end
function http.prepare_content(_) end
function http.write_json(t) if t.success then print("success:" .. (t.message or "")) else print("fail:" .. (t.message or "")) end end
local c = require "luci.controller.wifidog_v3"
c.action_clear_runtime_logs()
''')
    ok("Runtime logs can clear app log safely", "success:" in clear_logs.stdout and "运行日志已清空" in clear_logs.stdout and "运行日志已由管理后台清空" in dsh(ROUTER, "cat /var/log/wifidog_v3.log").stdout, clear_logs.stdout + clear_logs.stderr)
    pending_note = router_lua('''
local http = require "luci.http"
local values = { mac = "DE:AD:BE:EF:67:68", ip = "10.88.0.66", hostname = "lease-only-phone", note = "门口手机" }
function http.formvalue(k) return values[k] end
function http.prepare_content(_) end
function http.write_json(t) if t.success then print("success") else print("fail:" .. (t.message or "")) end end
local c = require "luci.controller.wifidog_v3"
c.action_update_note()
''')
    pending_scan = router_lua('''
local http = require "luci.http"
function http.prepare_content(_) end
function http.write_json(t)
	for _, d in ipairs(t.devices or {}) do
		if d.mac == "DE:AD:BE:EF:67:68" then print((d.note or "") .. "|" .. (d.hostname or "")) end
	end
end
local c = require "luci.controller.wifidog_v3"
c.action_scan_devices()
''')
    ok("Pending device note can be saved and remains visible", "success" in pending_note.stdout and "门口手机|lease-only-phone" in pending_scan.stdout, pending_note.stdout + pending_note.stderr + pending_scan.stdout + pending_scan.stderr)
    dsh(ROUTER, "dd if=/dev/zero bs=1024 count=513 2>/dev/null | tr '\\000' X > /var/log/wifidog_v3.log")
    rotate_note = router_lua('''
local http = require "luci.http"
local values = { mac = "DE:AD:BE:EF:67:68", note = "门口手机", ip = "10.88.0.66", hostname = "lease-only-phone" }
function http.formvalue(k) return values[k] end
function http.prepare_content(_) end
function http.write_json(t) print(t.success and "success" or "fail") end
local c = require "luci.controller.wifidog_v3"
c.action_update_note()
''')
    rotated_log = dsh(ROUTER, "test -s /var/log/wifidog_v3.log.1 && test $(wc -c < /var/log/wifidog_v3.log) -lt 524288")
    ok("Runtime log rotates at bounded size", "success" in rotate_note.stdout and rotated_log.returncode == 0, rotate_note.stdout + rotate_note.stderr + rotated_log.stderr)
    portal_custom_batch = """
set wifidog_v3.settings.portal_theme=warm
set wifidog_v3.settings.portal_title=企业访客网络
set wifidog_v3.settings.portal_prompt=请联系前台领取临时授权码
set wifidog_v3.settings.portal_hint=认证成功后即可访问互联网
set wifidog_v3.settings.portal_button_text=立即认证
set wifidog_v3.settings.portal_code_label=访客码
set wifidog_v3.settings.portal_code_placeholder=请输入访客码
commit wifidog_v3
"""
    dexec(ROUTER, "uci", "batch", input_text=portal_custom_batch, check=True)
    custom_portal = client_get(PORTAL_URL).stdout
    ok("Portal page applies configured theme and copy", "企业访客网络" in custom_portal and "请联系前台领取临时授权码" in custom_portal and "立即认证" in custom_portal and "访客码" in custom_portal and "#fff7ed" in custom_portal, custom_portal[:500])
    portal_default_batch = """
set wifidog_v3.settings.portal_theme=classic
set wifidog_v3.settings.portal_title=网络认证
set wifidog_v3.settings.portal_prompt=请输入授权码以访问互联网
set wifidog_v3.settings.portal_hint=如需获取授权码，请联系网络管理员。认证成功后会自动确认网络状态并尝试关闭认证窗口。
set wifidog_v3.settings.portal_button_text=认证上网
set wifidog_v3.settings.portal_code_label=授权码
set wifidog_v3.settings.portal_code_placeholder=请输入授权码
commit wifidog_v3
"""
    dexec(ROUTER, "uci", "batch", input_text=portal_default_batch, check=True)
    pending_to_whitelist = router_lua('''
local http = require "luci.http"
local values = { mac = "DE:AD:BE:EF:67:68", ip = "10.88.0.66", hostname = "lease-only-phone", note = "" }
function http.formvalue(k) return values[k] end
function http.prepare_content(_) end
function http.write_json(t) if t.success then print("success") else print("fail:" .. (t.message or "")) end end
local c = require "luci.controller.wifidog_v3"
c.action_add_whitelist()
''')
    whitelist_note = dsh(ROUTER, "uci -q get wifidog_v3.de_ad_be_ef_67_68.type; uci -q get wifidog_v3.de_ad_be_ef_67_68.note").stdout
    ok("Saved note follows MAC when pending device moves to whitelist", "success" in pending_to_whitelist.stdout and "whitelist" in whitelist_note and "门口手机" in whitelist_note, pending_to_whitelist.stdout + pending_to_whitelist.stderr + whitelist_note)
    export_config = router_lua('''
local http = require "luci.http"
function http.formvalue(_) return nil end
function http.header(_, _) end
function http.prepare_content(_) end
function http.write(s) print(s) end
local c = require "luci.controller.wifidog_v3"
c.action_export_config()
''')
    ok("Export config includes device notes", "wifidog_v3" in export_config.stdout and "门口手机" in export_config.stdout and "devices" in export_config.stdout, export_config.stdout + export_config.stderr)
    ok("Export config includes User-Agent metadata", "ua_summary" in export_config.stdout and "user_agent" in export_config.stdout, export_config.stdout + export_config.stderr)
    ok("Default export omits RADIUS shared secret", RADIUS_SECRET not in export_config.stdout and '"sensitive_fields_included":false' in export_config.stdout, export_config.stdout + export_config.stderr)
    secret_export = router_lua('''
local http = require "luci.http"
function http.formvalue(k) if k == "include_secrets" then return "1" end end
function http.header(_, _) end
function http.prepare_content(_) end
function http.write(s) print(s) end
local c = require "luci.controller.wifidog_v3"
c.action_export_config()
''')
    ok("Explicit sensitive export includes RADIUS shared secret", RADIUS_SECRET in secret_export.stdout and '"sensitive_fields_included":true' in secret_export.stdout, secret_export.stdout + secret_export.stderr)
    remove_whitelist = router_lua('''
local http = require "luci.http"
local values = { mac = "DE:AD:BE:EF:67:68" }
function http.formvalue(k) return values[k] end
function http.prepare_content(_) end
function http.write_json(t) if t.success then print("success:" .. (t.message or "")) else print("fail:" .. (t.message or "")) end end
local c = require "luci.controller.wifidog_v3"
c.action_remove_device()
''')
    pending_after_white_remove = dsh(ROUTER, "uci -q get wifidog_v3.de_ad_be_ef_67_68.type; uci -q get wifidog_v3.de_ad_be_ef_67_68.note").stdout
    ok("Removing from whitelist preserves note as pending", "success:" in remove_whitelist.stdout and "pending" in pending_after_white_remove and "门口手机" in pending_after_white_remove, remove_whitelist.stdout + remove_whitelist.stderr + pending_after_white_remove)
    pending_to_blacklist = router_lua('''
local http = require "luci.http"
local values = { mac = "DE:AD:BE:EF:67:68", ip = "10.88.0.66", hostname = "lease-only-phone", note = "" }
function http.formvalue(k) return values[k] end
function http.prepare_content(_) end
function http.write_json(t) if t.success then print("success") else print("fail:" .. (t.message or "")) end end
local c = require "luci.controller.wifidog_v3"
c.action_add_blacklist()
''')
    remove_blacklist = router_lua('''
local http = require "luci.http"
local values = { mac = "DE:AD:BE:EF:67:68" }
function http.formvalue(k) return values[k] end
function http.prepare_content(_) end
function http.write_json(t) if t.success then print("success:" .. (t.message or "")) else print("fail:" .. (t.message or "")) end end
local c = require "luci.controller.wifidog_v3"
c.action_remove_device()
''')
    pending_after_black_remove = dsh(ROUTER, "uci -q get wifidog_v3.de_ad_be_ef_67_68.type; uci -q get wifidog_v3.de_ad_be_ef_67_68.note").stdout
    ok("Removing from blacklist preserves note as pending", "success" in pending_to_blacklist.stdout and "success:" in remove_blacklist.stdout and "pending" in pending_after_black_remove and "门口手机" in pending_after_black_remove, pending_to_blacklist.stdout + pending_to_blacklist.stderr + remove_blacklist.stdout + remove_blacklist.stderr + pending_after_black_remove)
    dsh(ROUTER, "uci -q delete wifidog_v3.de_ad_be_ef_67_68; uci -q commit wifidog_v3")

    if dsh(CLIENT, "command -v nc >/dev/null 2>&1").returncode == 0:
        started = time.monotonic()
        dsh(CLIENT, r"for i in 1 2 3 4 5 6; do (printf '\026\003\001\000\120' | nc -w 10 10.88.0.2 8080 >/dev/null 2>&1 &) ; done; wait")
        elapsed = time.monotonic() - started
        ok("Portal rejects non-HTTP sockets quickly", elapsed < 4, f"{elapsed:.2f}s")
        started = time.monotonic()
        fast_portal = client_get(PORTAL_URL)
        elapsed = time.monotonic() - started
        ok("Portal page remains fast after bad sockets", fast_portal.returncode == 0 and "网络认证" in fast_portal.stdout and elapsed < 2, f"{elapsed:.2f}s")
    else:
        ok("Portal bad-socket latency test skipped", True, "nc not available")

    ui_code = "UIADD" + str(int(time.time()))[-6:]
    gen = router_lua(f'''
local http = require "luci.http"
    local values = {{ code = "{ui_code}", max_uses = "2", expiry_days = "7", auth_minutes = "11" }}
function http.formvalue(k) return values[k] end
function http.prepare_content(_) end
function http.write_json(t)
	if t.success then print("success:" .. (t.message or "")) else print("fail:" .. (t.message or "")) end
end
local c = require "luci.controller.wifidog_v3"
c.action_generate_code()
''')
    generated = dsh(ROUTER, f"uci show wifidog_v3 | grep -q \"code='{ui_code}'\"").returncode == 0
    generated_duration = dsh(ROUTER, "uci show wifidog_v3 | grep -q \"auth_minutes='11'\"").returncode == 0
    ok("Admin auth code generation endpoint stores per-code duration", gen.returncode == 0 and "success:" in gen.stdout and generated and generated_duration, gen.stdout + gen.stderr)
    duplicate_gen = router_lua(f'''
local http = require "luci.http"
local values = {{ code = "{ui_code.lower()}", max_uses = "9", expiry_days = "9", auth_minutes = "9" }}
function http.formvalue(k) return values[k] end
function http.prepare_content(_) end
function http.write_json(t) print((t.success and "success:" or "fail:") .. (t.message or "")) end
local c = require "luci.controller.wifidog_v3"
c.action_generate_code()
''')
    duplicate_count = dsh(ROUTER, f"uci show wifidog_v3 | grep -c \"code='{ui_code}'\"").stdout.strip()
    ok("Auth code generation rejects case-insensitive duplicates", "fail:" in duplicate_gen.stdout and "已存在" in duplicate_gen.stdout and duplicate_count == "1", duplicate_gen.stdout + duplicate_gen.stderr + duplicate_count)
    invalid_duration_code = "BADMIN" + str(int(time.time()))[-6:]
    invalid_duration = router_lua(f'''
local http = require "luci.http"
local values = {{ code = "{invalid_duration_code}", max_uses = "2", expiry_days = "7", auth_minutes = "0" }}
function http.formvalue(k) return values[k] end
function http.prepare_content(_) end
function http.write_json(t) print((t.success and "success:" or "fail:") .. (t.message or "")) end
local c = require "luci.controller.wifidog_v3"
c.action_generate_code()
''')
    invalid_duration_saved = dsh(ROUTER, f"uci show wifidog_v3 | grep -q \"code='{invalid_duration_code}'\"").returncode == 0
    ok("Auth code generation rejects zero-minute duration without partial data", "fail:" in invalid_duration.stdout and not invalid_duration_saved, invalid_duration.stdout + invalid_duration.stderr)
    default_duration_code = "NODEF" + str(int(time.time()))[-6:]
    default_duration_gen = router_lua(f'''
local http = require "luci.http"
local values = {{ code = "{default_duration_code}", max_uses = "2", expiry_days = "7", auth_minutes = "" }}
function http.formvalue(k) return values[k] end
function http.prepare_content(_) end
function http.write_json(t) print((t.success and "success:" or "fail:") .. (t.message or "")) end
local c = require "luci.controller.wifidog_v3"
c.action_generate_code()
''')
    default_duration_state = dsh(ROUTER, f"section=$(uci show wifidog_v3 | sed -n \"s/^wifidog_v3\\.\\([^.]\\+\\)\\.code='{default_duration_code}'$/\\1/p\"); [ -n \"$section\" ] && uci -q get \"wifidog_v3.$section.auth_minutes\"").stdout.strip()
    ok("Blank per-code duration is stored as default fallback", "success:" in default_duration_gen.stdout and default_duration_state == "", default_duration_gen.stdout + default_duration_gen.stderr + default_duration_state)

    enabled_before_bad_mac = dsh(ROUTER, "uci -q get wifidog_v3.settings.enabled").stdout.strip()
    bad_mac = router_lua('''
local http = require "luci.http"
local values = { mac = "settings", ip = "10.88.0.99", hostname = "bad", note = "bad" }
function http.formvalue(k) return values[k] end
function http.prepare_content(_) end
function http.write_json(t) print((t.success and "success:" or "fail:") .. (t.message or "")) end
local c = require "luci.controller.wifidog_v3"
c.action_add_whitelist()
''')
    enabled_after_bad_mac = dsh(ROUTER, "uci -q get wifidog_v3.settings.enabled").stdout.strip()
    ok("Invalid MAC cannot overwrite settings section", "fail:" in bad_mac.stdout and enabled_after_bad_mac == enabled_before_bad_mac == "1", bad_mac.stdout + bad_mac.stderr + enabled_after_bad_mac)

    count_before_unknown = dsh(ROUTER, "uci -q get wifidog_v3.auth_VIP2026.used_count").stdout.strip()
    unknown_mac_auth = dsh(ROUTER, "body='action=auth&auth_code=VIP2026'; printf '%s' \"$body\" | REQUEST_METHOD=POST REQUEST_URI=/portal CONTENT_LENGTH=${#body} REMOTE_ADDR=10.88.0.251 /www/wifidog_v3/cgi-bin/wifidog_v3/portal")
    count_after_unknown = dsh(ROUTER, "uci -q get wifidog_v3.auth_VIP2026.used_count").stdout.strip()
    ok("Unknown client MAC does not consume auth code", '"success":false' in unknown_mac_auth.stdout and count_before_unknown == count_after_unknown == "0", unknown_mac_auth.stdout + unknown_mac_auth.stderr + count_after_unknown)

    race = dsh(ROUTER, "rm -f /tmp/wifidog_race.*; body='action=auth&auth_code=RACEONCE'; for i in 1 2 3 4 5 6 7 8 9 10; do (printf '%s' \"$body\" | REQUEST_METHOD=POST REQUEST_URI=/portal CONTENT_LENGTH=${#body} REMOTE_ADDR=10.88.0.10 /www/wifidog_v3/cgi-bin/wifidog_v3/portal > /tmp/wifidog_race.$i) & done; wait; grep -l '\"success\":true' /tmp/wifidog_race.* | wc -l")
    race_used = dsh(ROUTER, "uci -q get wifidog_v3.auth_RACE.used_count").stdout.strip()
    ok("Concurrent single-use auth code succeeds exactly once", race.stdout.strip() == "1" and race_used == "1", race.stdout + race.stderr + race_used)
    dsh(ROUTER, f"uci -q delete wifidog_v3.{section}; uci -q commit wifidog_v3; /etc/init.d/wifidog_v3 reload")

    auth = client_post(PORTAL_URL, "action=auth&auth_code=VIP2026&redirect_url=http://10.89.0.10/")
    ok("Auth code accepted", '"success":true' in auth.stdout and '"wait_seconds":3' in auth.stdout and '"redirect":"http://10.89.0.10/"' in auth.stdout and '"expires_at":' in auth.stdout and '"expires_at_text":' in auth.stdout and '"valid_text":"5分钟"' in auth.stdout, auth.stdout)
    time.sleep(0.5)
    code_source = dsh(ROUTER, f"uci -q get wifidog_v3.{mac.replace(':', '_').lower()}.auth_source").stdout.strip()
    ok("Self-service auth source recorded", code_source == "code", code_source)
    auth_remaining_seconds = dsh(ROUTER, f"expr $(uci -q get wifidog_v3.{mac.replace(':', '_').lower()}.auth_expiry) - $(date +%s)").stdout.strip()
    ok("Self-service auth applies per-code duration", auth_remaining_seconds.isdigit() and 240 <= int(auth_remaining_seconds) <= 360, auth_remaining_seconds)
    default_auth = client_post(PORTAL_URL, "action=auth&auth_code=DEFAULT1440&redirect_url=http://10.89.0.10/")
    default_remaining_seconds = dsh(ROUTER, f"expr $(uci -q get wifidog_v3.{mac.replace(':', '_').lower()}.auth_expiry) - $(date +%s)").stdout.strip()
    ok("Auth code without duration falls back to default auth timeout", '"success":true' in default_auth.stdout and default_remaining_seconds.isdigit() and 86000 <= int(default_remaining_seconds) <= 86500, default_auth.stdout + default_remaining_seconds)
    radius_auth = client_post(PORTAL_URL, "action=auth&auth_method=radius&radius_username=raduser&radius_password=radpass&redirect_url=http://10.89.0.10/")
    radius_source = dsh(ROUTER, f"uci -q get wifidog_v3.{mac.replace(':', '_').lower()}.auth_source").stdout.strip()
    radius_user = dsh(ROUTER, f"uci -q get wifidog_v3.{mac.replace(':', '_').lower()}.radius_user").stdout.strip()
    radius_remaining_seconds = dsh(ROUTER, f"expr $(uci -q get wifidog_v3.{mac.replace(':', '_').lower()}.auth_expiry) - $(date +%s)").stdout.strip()
    ok("RADIUS PAP auth accepts FreeRADIUS user and applies Session-Timeout", '"success":true' in radius_auth.stdout and radius_source == "radius" and radius_user == "raduser" and radius_remaining_seconds.isdigit() and 240 <= int(radius_remaining_seconds) <= 360, radius_auth.stdout + radius_source + radius_user + radius_remaining_seconds)
    bad_radius_auth = client_post(PORTAL_URL, "action=auth&auth_method=radius&radius_username=raduser&radius_password=wrong")
    ok("RADIUS PAP auth rejects invalid password", '"success":false' in bad_radius_auth.stdout, bad_radius_auth.stdout)
    ip_session = dexec(ROUTER, "cat", "/tmp/wifidog_v3_ip_sessions")
    ok("Self-service auth records short IP session for iOS re-probe", ip_session.returncode == 0 and f"10.88.0.10 {mac}" in ip_session.stdout, ip_session.stdout + ip_session.stderr)
    fallback_api = dsh(ROUTER, f"now=$(date +%s); printf '%s 10.88.0.250 {mac}\\n' \"$((now + 600))\" >> /tmp/wifidog_v3_ip_sessions; REQUEST_METHOD=GET REQUEST_URI=/captive-portal/api REMOTE_ADDR=10.88.0.250 /www/wifidog_v3/cgi-bin/wifidog_v3/portal")
    ok("RFC8908 API falls back to short IP session when MAC lookup is missing", '"captive":false' in fallback_api.stdout and '"seconds-remaining":' in fallback_api.stdout, fallback_api.stdout + fallback_api.stderr)
    auth_api = client_get(CAPTIVE_API_URL).stdout
    ok("RFC8908 API reports authorized client not captive", '"captive":false' in auth_api and '"seconds-remaining":' in auth_api, auth_api)
    android_probe = client_get("http://10.88.0.2:8080/generate_204")
    ok("Authorized Android probe gets 204-style empty success", android_probe.returncode == 0 and android_probe.stdout == "", android_probe.stdout + android_probe.stderr)
    ok("Authorized Apple probe gets Success", "Success" in client_get("http://10.88.0.2:8080/hotspot-detect.html").stdout)
    ok("Authorized Windows NCSI probe gets expected text", "Microsoft NCSI" in client_get("http://10.88.0.2:8080/ncsi.txt").stdout)
    ok("Authorized WAN access", "WAN_OK" in client_get(WAN_URL).stdout)
    ok("Invalid code rejected", '"success":false' in client_post(PORTAL_URL, "action=auth&auth_code=BAD").stdout)
    ok("Used-up code rejected", '"success":false' in client_post(PORTAL_URL, "action=auth&auth_code=ONCE123").stdout)
    ok("Expired code rejected", '"success":false' in client_post(PORTAL_URL, "action=auth&auth_code=EXPIRED1").stdout)
    ok("Disabled code rejected", '"success":false' in client_post(PORTAL_URL, "action=auth&auth_code=DISABLED1").stdout)

    set_device(mac, "whitelist", note="VIP phone")
    ok("Whitelist WAN access", "WAN_OK" in client_get(WAN_URL).stdout)
    note_update = router_lua(f'''
local http = require "luci.http"
local values = {{ mac = "{mac}", note = "客厅电视" }}
function http.formvalue(k) return values[k] end
function http.prepare_content(_) end
function http.write_json(t) if t.success then print("success") else print("fail:" .. (t.message or "")) end end
local c = require "luci.controller.wifidog_v3"
c.action_update_note()
''')
    note_saved = dsh(ROUTER, f"uci -q get wifidog_v3.{mac.replace(':', '_').lower()}.note").stdout.strip()
    ok("Device note update endpoint", note_update.returncode == 0 and "success" in note_update.stdout and note_saved == "客厅电视", note_update.stdout + note_update.stderr + note_saved)

    set_device(mac, "blacklist")
    black_rules = dexec(ROUTER, "nft", "-nn", "list", "chain", "inet", "wifidog_v3", "portal_pre_filter").stdout
    dhcp_idx = black_rules.find("udp sport 68 udp dport 67 return")
    drop_idx = black_rules.find("ether saddr " + mac.lower() + " drop")
    ok("Blacklist still allows DHCP before dropping public traffic", dhcp_idx >= 0 and drop_idx >= 0 and dhcp_idx < drop_idx, black_rules)
    blocked = client_get(WAN_URL, timeout=3)
    ok("Blacklist WAN shows blocked portal", blocked.returncode == 0 and "设备已被拉黑" in blocked.stdout and "WAN_OK" not in blocked.stdout, blocked.stdout + blocked.stderr)
    black_443 = client_get("http://10.89.0.10:443/", timeout=3)
    ok("Blacklist TCP 443 is blocked without plaintext portal", black_443.returncode != 0 and "设备已被拉黑" not in black_443.stdout, black_443.stdout + black_443.stderr)
    ok("Blacklist portal forbids self-service", "设备已被拉黑" in client_get(PORTAL_URL).stdout)
    black_api = client_get(CAPTIVE_API_URL).stdout
    ok("RFC8908 API reports blacklisted client captive", '"captive":true' in black_api and '"user-portal-url":"' in black_api, black_api)
    stale_session_api = dsh(ROUTER, "REQUEST_METHOD=GET REQUEST_URI=/captive-portal/api REMOTE_ADDR=10.88.0.250 /www/wifidog_v3/cgi-bin/wifidog_v3/portal")
    ok("Blacklisting overrides any stale short IP session", '"captive":true' in stale_session_api.stdout, stale_session_api.stdout + stale_session_api.stderr)

    section = mac.replace(":", "_").lower()
    dexec(ROUTER, "uci", "delete", f"wifidog_v3.{section}")
    dexec(ROUTER, "uci", "commit", "wifidog_v3")
    dexec(ROUTER, "/etc/init.d/wifidog_v3", "reload", check=True)
    ok("Delete returns to pending", "网络认证" in client_get(WAN_URL).stdout)

    future = str(int(time.time()) + 86400)
    set_device(mac, "authorized", future, source="manual", note="临时授权")
    manual_source = dsh(ROUTER, f"uci -q get wifidog_v3.{mac.replace(':', '_').lower()}.auth_source").stdout.strip()
    ok("Manual auth source recorded", manual_source == "manual", manual_source)
    ok("Manual authorize WAN access", "WAN_OK" in client_get(WAN_URL).stdout)

    set_device(mac, "authorized", "1", source="manual", note="过期后保留")
    dexec(ROUTER, "/etc/init.d/wifidog_v3", "check_expiry_cron", check=True)
    dexec(ROUTER, "/etc/init.d/wifidog_v3", "reload", check=True)
    ok("Expired authorization returns to pending", "网络认证" in client_get(WAN_URL).stdout)
    expired_metadata = dsh(ROUTER, f"uci -q get wifidog_v3.{section}.type; uci -q get wifidog_v3.{section}.note; uci -q get wifidog_v3.{section}.auth_expiry").stdout
    ok("Expired authorization preserves MAC-bound metadata", "pending" in expired_metadata and "过期后保留" in expired_metadata and expired_metadata.rstrip().endswith("0"), expired_metadata)

    backup_payload = json.dumps({
        "app": "wifidog_v3",
        "format_version": 1,
        "settings": {
            "enabled": "1",
            "lan_interface": "eth0",
            "wan_interface": "eth1",
            "portal_port": "8080",
            "lan_subnet": "10.88.0.0/24",
            "auth_timeout": "1440",
            "auto_detect_wan": "1",
            "portal_theme": "dark",
            "portal_title": "备份认证页",
            "portal_prompt": "备份提示词",
            "portal_hint": "备份底部提示",
            "portal_button_text": "备份认证",
            "portal_code_label": "备份码",
            "portal_code_placeholder": "请输入备份码",
        },
        "devices": [
            {
                "mac": "AA:BB:CC:DD:EE:01",
                "ip": "10.88.0.51",
                "hostname": "backup-white",
                "note": "备份白名单",
                "type": "whitelist",
                "auth_expiry": "0",
                "created": str(int(time.time())),
            },
            {
                "mac": "AA:BB:CC:DD:EE:02",
                "ip": "10.88.0.52",
                "hostname": "backup-black",
                "note": "备份黑名单",
                "type": "blacklist",
                "auth_expiry": "0",
                "created": str(int(time.time())),
            },
        ],
        "auth_codes": [
            {
                "code": "BACKUP123",
                "max_uses": "3",
                "used_count": "1",
                "expiry_days": "30",
                "auth_minutes": "60",
                "created_date": "2026-05-18",
                "enabled": "1",
            }
        ],
    }, ensure_ascii=False)
    import_config = router_lua(f'''
local http = require "luci.http"
local values = {{ config_json = [==[{backup_payload}]==] }}
function http.formvalue(k) return values[k] end
function http.prepare_content(_) end
function http.write_json(t) if t.success then print("success:" .. (t.message or "")) else print("fail:" .. (t.message or "")) end end
local c = require "luci.controller.wifidog_v3"
c.action_import_config()
''')
    imported = dsh(ROUTER, "uci -q get wifidog_v3.aa_bb_cc_dd_ee_01.type; uci -q get wifidog_v3.aa_bb_cc_dd_ee_01.note; uci -q get wifidog_v3.aa_bb_cc_dd_ee_02.type; uci -q get wifidog_v3.aa_bb_cc_dd_ee_02.note; uci -q get wifidog_v3.settings.portal_title; uci -q get wifidog_v3.settings.portal_theme; uci show wifidog_v3 | grep -q \"code='BACKUP123'\" && echo CODE_OK; uci show wifidog_v3 | grep -q \"auth_minutes='60'\" && echo AUTH_MINUTES_OK").stdout
    ok("Import config restores lists, notes, auth codes, per-code duration and portal settings", "success:" in import_config.stdout and "whitelist" in imported and "备份白名单" in imported and "blacklist" in imported and "备份黑名单" in imported and "备份认证页" in imported and "dark" in imported and "CODE_OK" in imported and "AUTH_MINUTES_OK" in imported, import_config.stdout + import_config.stderr + imported)
    invalid_import = router_lua('''
local http = require "luci.http"
local values = { config_json = [[{"app":"another_app","settings":{"portal_title":"SHOULD_NOT_APPLY"}}]] }
function http.formvalue(k) return values[k] end
function http.prepare_content(_) end
function http.write_json(t) print((t.success and "success:" or "fail:") .. (t.message or "")) end
local c = require "luci.controller.wifidog_v3"
c.action_import_config()
''')
    title_after_invalid_import = dsh(ROUTER, "uci -q get wifidog_v3.settings.portal_title").stdout.strip()
    ok("Rejected backup leaves committed configuration unchanged", "fail:" in invalid_import.stdout and title_after_invalid_import == "备份认证页", invalid_import.stdout + invalid_import.stderr + title_after_invalid_import)
    malformed_import = router_lua('''
local http = require "luci.http"
local values = { config_json = "{not-json" }
function http.formvalue(k) return values[k] end
function http.prepare_content(_) end
function http.write_json(t) print((t.success and "success:" or "fail:") .. (t.message or "")) end
local c = require "luci.controller.wifidog_v3"
c.action_import_config()
''')
    title_after_malformed_import = dsh(ROUTER, "uci -q get wifidog_v3.settings.portal_title").stdout.strip()
    ok("Malformed backup JSON is rejected without changing configuration", "fail:" in malformed_import.stdout and title_after_malformed_import == "备份认证页", malformed_import.stdout + malformed_import.stderr + title_after_malformed_import)

    dexec(ROUTER, "uci", "set", "wifidog_v3.settings.auth_code_enabled=0")
    dexec(ROUTER, "uci", "set", "wifidog_v3.settings.radius_enabled=0")
    dexec(ROUTER, "uci", "commit", "wifidog_v3")
    no_self_service_page = client_get(PORTAL_URL).stdout
    no_self_service_post = client_post(PORTAL_URL, "action=auth&auth_code=BACKUP123")
    ok("Disabling all self-service methods keeps them disabled", "管理员暂未启用自助认证" in no_self_service_page and "disabled" in no_self_service_page and '"success":false' in no_self_service_post.stdout, no_self_service_page[:300] + no_self_service_post.stdout)
    dexec(ROUTER, "uci", "set", "wifidog_v3.settings.auth_code_enabled=1")
    dexec(ROUTER, "uci", "commit", "wifidog_v3")

    dexec(ROUTER, "/etc/init.d/wifidog_v3", "stop", check=True)
    dexec(ROUTER, "mv", "/www/wifidog_v3/cgi-bin/wifidog_v3/portal", "/www/wifidog_v3/cgi-bin/wifidog_v3/portal.off", check=True)
    failed_start = dexec(ROUTER, "/etc/init.d/wifidog_v3", "start")
    rollback_clean = dsh(ROUTER, "! nft list table inet wifidog_v3 >/dev/null 2>&1 && test ! -e /tmp/dnsmasq.d/wifidog_v3.conf && ! ps w | grep '[u]httpd' | grep -q '/www/wifidog_v3'")
    ok("Portal startup failure rolls back firewall and captive advertisement", failed_start.returncode != 0 and rollback_clean.returncode == 0, failed_start.stdout + failed_start.stderr + rollback_clean.stderr)
    dexec(ROUTER, "mv", "/www/wifidog_v3/cgi-bin/wifidog_v3/portal.off", "/www/wifidog_v3/cgi-bin/wifidog_v3/portal", check=True)
    dexec(ROUTER, "/etc/init.d/wifidog_v3", "start", check=True)

    # Verify that enabling and disabling the service preserves a pre-existing
    # RFC8910 advertisement owned by another component.
    dexec(ROUTER, "uci", "set", "wifidog_v3.settings.enabled=0")
    dexec(ROUTER, "uci", "commit", "wifidog_v3")
    dexec(ROUTER, "/etc/init.d/wifidog_v3", "stop", check=True)
    dexec(ROUTER, "uci", "set", f"dhcp.lan.captive_portal_uri={PREEXISTING_CAPTIVE_URI}")
    dexec(ROUTER, "uci", "commit", "dhcp")
    dsh(ROUTER, "uci -q delete wifidog_v3.settings.odhcpd_prev_captive_portal_uri_saved; uci -q delete wifidog_v3.settings.odhcpd_prev_captive_portal_uri_was_set; uci -q delete wifidog_v3.settings.odhcpd_prev_captive_portal_uri; uci -q commit wifidog_v3")
    dexec(ROUTER, "uci", "set", "wifidog_v3.settings.enabled=1")
    dexec(ROUTER, "uci", "commit", "wifidog_v3")
    dexec(ROUTER, "/etc/init.d/wifidog_v3", "restart", check=True)
    ok("Enabled system creates nft table before disable test", dexec(ROUTER, "nft", "list", "table", "inet", "wifidog_v3").returncode == 0)
    dexec(ROUTER, "touch", "/tmp/wifidog_v3_ip_sessions", check=True)
    dexec(ROUTER, "uci", "set", "wifidog_v3.settings.enabled=0")
    dexec(ROUTER, "uci", "commit", "wifidog_v3")
    dexec(ROUTER, "/etc/init.d/wifidog_v3", "start", check=True)
    ok("Disabled system allows WAN", "WAN_OK" in client_get(WAN_URL).stdout)
    ok("Disabled system cleans nft table", dexec(ROUTER, "nft", "list", "table", "inet", "wifidog_v3").returncode != 0)
    ok("Disabled system stops portal process", dsh(ROUTER, "ps w | grep '[u]httpd' | grep -q '/www/wifidog_v3'").returncode != 0)
    ok("Disabled system removes captive DHCP advertisement", dexec(ROUTER, "test", "!", "-e", "/tmp/dnsmasq.d/wifidog_v3.conf").returncode == 0)
    restored_uri = dexec(ROUTER, "uci", "-q", "get", "dhcp.lan.captive_portal_uri")
    ok("Disabled system restores pre-existing odhcpd captive URI", restored_uri.returncode == 0 and restored_uri.stdout.strip() == PREEXISTING_CAPTIVE_URI, restored_uri.stdout + restored_uri.stderr)
    ok("Disabled system removes short IP session cache", dexec(ROUTER, "test", "!", "-e", "/tmp/wifidog_v3_ip_sessions").returncode == 0)

    remove_package()
    ok("Uninstall removes package record", not package_installed())
    ok("Uninstall releases portal process", dsh(ROUTER, "ps w | grep '[u]httpd' | grep -q '/www/wifidog_v3'").returncode != 0)
    ok("Uninstall removes portal pid file", dexec(ROUTER, "test", "!", "-e", "/var/run/wifidog_v3_portal.pid").returncode == 0)
    ok("Uninstall removes expiry pid file", dexec(ROUTER, "test", "!", "-e", "/var/run/wifidog_v3_expiry.pid").returncode == 0)
    ok("Uninstall removes portal CGI files", dexec(ROUTER, "test", "!", "-e", "/www/wifidog_v3").returncode == 0 and dexec(ROUTER, "test", "!", "-e", "/www/cgi-bin/wifidog_v3").returncode == 0)
    ok("Uninstall removes captive DHCP advertisement", dexec(ROUTER, "test", "!", "-e", "/tmp/dnsmasq.d/wifidog_v3.conf").returncode == 0)
    ok("Uninstall removes short IP session cache", dexec(ROUTER, "test", "!", "-e", "/tmp/wifidog_v3_ip_sessions").returncode == 0)
    uninstall_uri = dexec(ROUTER, "uci", "-q", "get", "dhcp.lan.captive_portal_uri")
    ok("Uninstall preserves pre-existing odhcpd captive URI", uninstall_uri.returncode == 0 and uninstall_uri.stdout.strip() == PREEXISTING_CAPTIVE_URI, uninstall_uri.stdout + uninstall_uri.stderr)
    ok("Uninstall removes config file", dexec(ROUTER, "test", "!", "-e", "/etc/config/wifidog_v3").returncode == 0)
    ok("Uninstall leaves WAN access working", "WAN_OK" in client_get(WAN_URL).stdout)
    dexec(ROUTER, "uci", "-q", "delete", "dhcp.lan.captive_portal_uri")
    dexec(ROUTER, "uci", "-q", "commit", "dhcp")
    stop_radius()

    print(f"\nResult: {passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
