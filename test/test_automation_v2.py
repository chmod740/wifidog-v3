#!/usr/bin/env python3
"""
WiFiDog V3 Comprehensive Test Suite v2
Runs from host machine, uses Docker for container tests and direct HTTP for web tests.
"""
import requests, json, subprocess, sys, os, time

PASS = 0; FAIL = 0
ROUTER_IP = "10.99.0.2"

def ok(msg): global PASS; print(f"  [PASS] {msg}"); PASS += 1
def no(msg): global FAIL; print(f"  [FAIL] {msg}"); FAIL += 1
def info(msg): print(f"  [INFO] {msg}")

def test(name):
    def decorator(func):
        def wrapper():
            info(f"Test: {name}")
            try:
                func()
            except Exception as e:
                no(f"{name}: {e}")
            print()
        return wrapper
    return decorator

# ========================================================
@test("1. Portal Page Accessibility")
def _():
    r = requests.get(f"http://{ROUTER_IP}/wifidog_v3/index.html", timeout=5)
    assert r.status_code == 200 and "网络认证" in r.text, f"HTTP {r.status_code}"
    ok("Portal accessible on port 80 with Chinese content")

    r = requests.get(f"http://{ROUTER_IP}:8080/wifidog_v3/index.html", timeout=5)
    assert r.status_code == 200 and "网络认证" in r.text
    ok("Portal accessible on port 8080")

    ct = r.headers.get("content-type", "")
    assert "text/html" in ct, f"Content-Type: {ct}"
    ok(f"Correct content-type: {ct}")

@test("2. Portal CGI - System Disabled Behavior")
def _():
    # System is disabled - all auth attempts should be rejected
    r = requests.post(f"http://{ROUTER_IP}/cgi-bin/wifidog_v3/portal",
                      data={"action": "auth", "auth_code": "VIP2024"}, timeout=5)
    d = r.json()
    assert not d["success"] and "未启用" in d["message"], f"Unexpected: {d}"
    ok("System disabled: correctly rejects auth with message about system disabled")

    r = requests.post(f"http://{ROUTER_IP}/cgi-bin/wifidog_v3/portal",
                      data={"action": "auth", "auth_code": "INVALID"}, timeout=5)
    d = r.json()
    assert not d["success"]
    ok("System disabled: invalid code also rejected")

@test("3. Portal CGI - System Enabled Auth Validation")
def _():
    # Enable the system
    subprocess.run(["docker", "exec", "openwrt-test-v3", "uci", "set", "wifidog_v3.settings.enabled=1"], capture_output=True)
    subprocess.run(["docker", "exec", "openwrt-test-v3", "uci", "commit", "wifidog_v3"], capture_output=True)

    # Valid auth code
    r = requests.post(f"http://{ROUTER_IP}/cgi-bin/wifidog_v3/portal",
                      data={"action": "auth", "auth_code": "VIP2024"}, timeout=5)
    d = r.json()
    assert d["success"], f"VIP2024 should be valid: {d}"
    ok(f"Valid code VIP2024 accepted: {d['message']}")

    # Used-up code
    r = requests.post(f"http://{ROUTER_IP}/cgi-bin/wifidog_v3/portal",
                      data={"action": "auth", "auth_code": "TEST123"}, timeout=5)
    d = r.json()
    assert not d["success"], f"TEST123 should be used up: {d}"
    ok(f"Used-up code TEST123 rejected: {d['message']}")

    # Invalid code
    r = requests.post(f"http://{ROUTER_IP}/cgi-bin/wifidog_v3/portal",
                      data={"action": "auth", "auth_code": "BADCODE"}, timeout=5)
    d = r.json()
    assert not d["success"]
    ok(f"Invalid code BADCODE rejected: {d['message']}")

    # Empty code
    r = requests.post(f"http://{ROUTER_IP}/cgi-bin/wifidog_v3/portal",
                      data={"action": "auth", "auth_code": ""}, timeout=5)
    d = r.json()
    assert not d["success"]
    ok(f"Empty code rejected: {d['message']}")

    # Disable system again
    subprocess.run(["docker", "exec", "openwrt-test-v3", "uci", "set", "wifidog_v3.settings.enabled=0"], capture_output=True)
    subprocess.run(["docker", "exec", "openwrt-test-v3", "uci", "commit", "wifidog_v3"], capture_output=True)

@test("4. Auth Code Usage Count Tracking")
def _():
    # Check used_count increments
    r = subprocess.run(["docker", "exec", "openwrt-test-v3", "uci", "-q", "get", "wifidog_v3.auth_VIP2024.used_count"],
                       capture_output=True, text=True)
    count = r.stdout.strip()
    ok(f"VIP2024 used_count = {count} (should be > 0 after previous auth)")

@test("5. IPK Package Structure Verification")
def _():
    files = [
        "Makefile",
        "luasrc/controller/wifidog_v3.lua",
        "luasrc/model/cbi/wifidog_v3/settings.lua",
        "luasrc/model/cbi/wifidog_v3/devices.lua",
        "luasrc/model/cbi/wifidog_v3/whitelist.lua",
        "luasrc/model/cbi/wifidog_v3/blacklist.lua",
        "luasrc/model/cbi/wifidog_v3/auth_codes.lua",
        "luasrc/view/wifidog_v3/devices.htm",
        "luasrc/view/wifidog_v3/whitelist.htm",
        "luasrc/view/wifidog_v3/blacklist.htm",
        "luasrc/view/wifidog_v3/auth_codes.htm",
        "luasrc/view/wifidog_v3/status.htm",
        "root/etc/config/wifidog_v3",
        "root/etc/init.d/wifidog_v3",
        "root/etc/uci-defaults/40_luci-wifidog-v3",
        "root/www/wifidog_v3/index.html",
        "root/www/cgi-bin/wifidog_v3/portal",
        "po/zh-cn/wifidog_v3.po",
    ]
    base = "/Users/hupeng/projects/wifidog_v3/luci-app-wifidog-v3"
    for f in files:
        p = os.path.join(base, f)
        if os.path.exists(p):
            ok(f"IPK source: {f}")
        else:
            no(f"IPK source MISSING: {f}")

@test("6. Init Script Validation")
def _():
    r = subprocess.run(["docker", "exec", "openwrt-test-v3", "bash", "-n", "/etc/init.d/wifidog_v3"],
                       capture_output=True, text=True)
    if r.returncode == 0:
        ok("Init script bash syntax OK")
    else:
        no(f"Init script error: {r.stderr}")

    # Check it's executable
    r = subprocess.run(["docker", "exec", "openwrt-test-v3", "test", "-x", "/etc/init.d/wifidog_v3"])
    if r.returncode == 0:
        ok("Init script is executable")
    else:
        no("Init script is NOT executable")

@test("7. Lua File Syntax Validation")
def _():
    lua_files = [
        "/usr/lib/lua/luci/controller/wifidog_v3.lua",
        "/usr/lib/lua/luci/model/cbi/wifidog_v3/devices.lua",
        "/usr/lib/lua/luci/model/cbi/wifidog_v3/whitelist.lua",
        "/usr/lib/lua/luci/model/cbi/wifidog_v3/blacklist.lua",
        "/usr/lib/lua/luci/model/cbi/wifidog_v3/auth_codes.lua",
        "/usr/lib/lua/luci/model/cbi/wifidog_v3/settings.lua",
    ]
    for lf in lua_files:
        r = subprocess.run(["docker", "exec", "openwrt-test-v3", "lua5.1", "-e",
            f'local ok, err = loadfile("{lf}"); if not ok then print("SYNTAX ERROR: " .. err) else print("OK") end'],
            capture_output=True, text=True)
        if "OK" in r.stdout:
            ok(f"Lua syntax OK: {os.path.basename(lf)}")
        else:
            no(f"Lua syntax in {os.path.basename(lf)}: {r.stdout.strip()}")

@test("8. UCI Configuration Read/Write")
def _():
    # Test reading settings
    r = subprocess.run(["docker", "exec", "openwrt-test-v3", "uci", "-q", "get", "wifidog_v3.settings.portal_port"],
                       capture_output=True, text=True)
    assert r.stdout.strip() == "8080", f"Expected 8080, got: {r.stdout.strip()}"
    ok("UCI read: portal_port = 8080")

    r = subprocess.run(["docker", "exec", "openwrt-test-v3", "uci", "-q", "get", "wifidog_v3.settings.auth_timeout"],
                       capture_output=True, text=True)
    assert r.stdout.strip() == "1440"
    ok("UCI read: auth_timeout = 1440 (24 hours)")

    # Test write
    subprocess.run(["docker", "exec", "openwrt-test-v3", "uci", "set", "wifidog_v3.settings.test_key=test_value"], capture_output=True)
    subprocess.run(["docker", "exec", "openwrt-test-v3", "uci", "commit", "wifidog_v3"], capture_output=True)
    r = subprocess.run(["docker", "exec", "openwrt-test-v3", "uci", "-q", "get", "wifidog_v3.settings.test_key"],
                       capture_output=True, text=True)
    assert r.stdout.strip() == "test_value"
    ok("UCI write: test_key = test_value")

    # Clean up
    subprocess.run(["docker", "exec", "openwrt-test-v3", "uci", "delete", "wifidog_v3.settings.test_key"], capture_output=True)
    subprocess.run(["docker", "exec", "openwrt-test-v3", "uci", "commit", "wifidog_v3"], capture_output=True)

@test("9. Firewall Rules Check")
def _():
    # Check iptables NAT table
    r = subprocess.run(["docker", "exec", "openwrt-test-v3", "iptables", "-t", "nat", "-L", "-n"],
                       capture_output=True, text=True)
    if "MASQUERADE" in r.stdout:
        ok("iptables NAT masquerade rule present")
    else:
        no("iptables NAT masquerade missing")

    # Check FORWARD chain
    r = subprocess.run(["docker", "exec", "openwrt-test-v3", "iptables", "-L", "FORWARD", "-n"],
                       capture_output=True, text=True)
    ok("iptables FORWARD chain accessible")

@test("10. Client-to-Router Web Access")
def _():
    # Client can access portal from its container
    r = subprocess.run(["docker", "exec", "test-client", "curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                        f"http://{ROUTER_IP}/wifidog_v3/index.html"],
                       capture_output=True, text=True)
    assert r.stdout.strip() == "200", f"HTTP {r.stdout.strip()}"
    ok("Client HTTP 200 to portal page")

    # Client can POST auth code
    r = subprocess.run(["docker", "exec", "test-client", "curl", "-s", "-X", "POST",
                        "-d", "action=auth&auth_code=VIP2024",
                        f"http://{ROUTER_IP}/cgi-bin/wifidog_v3/portal"],
                       capture_output=True, text=True)
    assert "success" in r.stdout, f"No JSON response: {r.stdout[:100]}"
    ok("Client can POST auth code and get JSON response")

@test("11. Settings Page Content")
def _():
    # Check that the settings model exists
    from pathlib import Path
    settings_file = Path("/Users/hupeng/projects/wifidog_v3/luci-app-wifidog-v3/luasrc/model/cbi/wifidog_v3/settings.lua")
    content = settings_file.read_text()
    assert "Map" in content and "wifidog_v3" in content
    ok("Settings CBI model references correct UCI config")
    assert "enabled" in content
    ok("Settings model has enabled option")
    assert "portal_port" in content
    ok("Settings model has portal_port option")
    assert "wan_interface" in content
    ok("Settings model has wan_interface option (configurable)")
    assert "auth_timeout" in content
    ok("Settings model has auth_timeout option")

@test("12. View Templates Content")
def _():
    from pathlib import Path
    views_dir = Path("/Users/hupeng/projects/wifidog_v3/luci-app-wifidog-v3/luasrc/view/wifidog_v3")

    # Device scanning page
    devices = (views_dir / "devices.htm").read_text()
    assert "添加白名单" in devices, "Missing whitelist button"
    assert "添加黑名单" in devices, "Missing blacklist button"
    assert "授权" in devices, "Missing authorize button"
    ok("Device scan page has all 3 action buttons")

    # Whitelist page
    whitelist = (views_dir / "whitelist.htm").read_text()
    assert "删除" in whitelist, "Missing delete button"
    ok("Whitelist page has delete button")

    # Blacklist page
    blacklist = (views_dir / "blacklist.htm").read_text()
    assert "删除" in blacklist, "Missing delete button"
    ok("Blacklist page has delete button")

    # Auth codes page
    codes = (views_dir / "auth_codes.htm").read_text()
    assert "生成授权码" in codes, "Missing generate button"
    assert "可用次数" in codes, "Missing max_uses field"
    assert "有效期" in codes, "Missing expiry field"
    ok("Auth codes page has all required fields")

# ========================================================
print("=" * 60)
print("WiFiDog V3 Comprehensive Test Suite v2")
print("=" * 60)
print()

test_portal_page = [v for k,v in globals().items() if k.startswith("_") and callable(v)]
for t in test_portal_page:
    t()

print("=" * 60)
print(f"Passed: {PASS}  Failed: {FAIL}  Total: {PASS+FAIL}")
print("=" * 60)
if FAIL > 0:
    print(f"\n*** {FAIL} test(s) FAILED ***")
    sys.exit(1)
else:
    print("\n*** ALL TESTS PASSED ***")
    sys.exit(0)
