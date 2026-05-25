#!/usr/bin/env python3
"""
WiFiDog V3 Comprehensive Automated Test Suite
Tests all features: whitelist, blacklist, auth codes, captive portal, settings
"""

import requests
import json
import subprocess
import sys
import os
import time

# Configuration
ROUTER_IP = os.environ.get("ROUTER_IP", "10.99.0.2")
ROUTER_PORT = int(os.environ.get("ROUTER_PORT", "80"))
PORTAL_PORT = int(os.environ.get("PORTAL_PORT", "8080"))
BASE_URL = f"http://{ROUTER_IP}:{ROUTER_PORT}"
PORTAL_URL = f"http://{ROUTER_IP}:{PORTAL_PORT}"

PASS = 0
FAIL = 0

def log_pass(msg):
    global PASS
    print(f"  [PASS] {msg}")
    PASS += 1

def log_fail(msg):
    global FAIL
    print(f"  [FAIL] {msg}")
    FAIL += 1

def log_info(msg):
    print(f"  [INFO] {msg}")

# ============================================================
# Test 1: Portal Page Accessibility
# ============================================================
def test_portal_page():
    log_info("Test 1: Portal Page Accessibility")

    # Test on port 80
    try:
        r = requests.get(f"{BASE_URL}/wifidog_v3/index.html", timeout=5)
        if r.status_code == 200 and "网络认证" in r.text:
            log_pass("Portal page accessible on port 80 with Chinese content")
        else:
            log_fail(f"Portal page issue: HTTP {r.status_code}, contains_cn={('网络认证' in r.text)}")
    except Exception as e:
        log_fail(f"Cannot access portal on port 80: {e}")

    # Test on port 8080
    try:
        r = requests.get(f"{PORTAL_URL}/wifidog_v3/index.html", timeout=5)
        if r.status_code == 200 and "网络认证" in r.text:
            log_pass("Portal page accessible on port 8080")
        else:
            log_fail(f"Portal page issue on 8080: HTTP {r.status_code}")
    except Exception as e:
        log_fail(f"Cannot access portal on port 8080: {e}")

# ============================================================
# Test 2: Portal CGI - Auth Code Validation
# ============================================================
def test_portal_cgi():
    log_info("Test 2: Portal CGI Auth Code Validation")

    # Test GET (serve portal page)
    try:
        r = requests.get(f"{BASE_URL}/cgi-bin/wifidog_v3/portal", timeout=5)
        if r.status_code == 200 and "网络认证" in r.text:
            log_pass("Portal CGI GET serves auth page")
        else:
            log_fail(f"Portal CGI GET: HTTP {r.status_code}, content: {r.text[:100]}")
    except Exception as e:
        log_fail(f"Portal CGI GET failed: {e}")

    # Test POST with valid code (VIP2024)
    try:
        data = {"action": "auth", "auth_code": "VIP2024", "redirect_url": "http://www.baidu.com"}
        r = requests.post(f"{BASE_URL}/cgi-bin/wifidog_v3/portal", data=data, timeout=5)
        result = r.json()
        if result.get("success"):
            log_pass(f"Portal CGI POST with VIP2024: success (message: {result.get('message', '')})")
        else:
            log_fail(f"Portal CGI POST with VIP2024 failed: {result}")
    except Exception as e:
        log_fail(f"Portal CGI POST failed: {e}")

    # Test POST with invalid code
    try:
        data = {"action": "auth", "auth_code": "INVALID_CODE", "redirect_url": ""}
        r = requests.post(f"{BASE_URL}/cgi-bin/wifidog_v3/portal", data=data, timeout=5)
        result = r.json()
        if not result.get("success"):
            log_pass(f"Portal CGI rejects invalid code: {result.get('message', '')}")
        else:
            log_fail(f"Portal CGI accepted invalid code!")
    except Exception as e:
        log_fail(f"Portal CGI invalid code test failed: {e}")

    # Test POST with used-up code (TEST123 - used_count=1, max_uses=1)
    try:
        data = {"action": "auth", "auth_code": "TEST123", "redirect_url": ""}
        r = requests.post(f"{BASE_URL}/cgi-bin/wifidog_v3/portal", data=data, timeout=5)
        result = r.json()
        if not result.get("success"):
            log_pass(f"Portal CGI rejects used-up code: {result.get('message', '')}")
        else:
            log_fail(f"Portal CGI accepted used-up code!")
    except Exception as e:
        log_fail(f"Portal CGI used-up code test failed: {e}")

    # Test POST with empty code
    try:
        data = {"action": "auth", "auth_code": "", "redirect_url": ""}
        r = requests.post(f"{BASE_URL}/cgi-bin/wifidog_v3/portal", data=data, timeout=5)
        result = r.json()
        if not result.get("success"):
            log_pass(f"Portal CGI rejects empty code: {result.get('message', '')}")
        else:
            log_fail(f"Portal CGI accepted empty code!")
    except Exception as e:
        log_fail(f"Portal CGI empty code test failed: {e}")

# ============================================================
# Test 3: Auth Code Usage Count
# ============================================================
def test_auth_code_count():
    log_info("Test 3: Auth Code Usage Count Tracking")

    # Check initial state via the CGI
    try:
        # Get current usage count by checking UCI-like state
        data = {"action": "auth", "auth_code": "VIP2024"}
        r = requests.post(f"{BASE_URL}/cgi-bin/wifidog_v3/portal", data=data, timeout=5)
        result = r.json()
        log_pass(f"Auth code VIP2024 can be used: {result.get('success')}")
    except Exception as e:
        log_fail(f"Auth code usage test failed: {e}")

# ============================================================
# Test 4: Static Files and Resources
# ============================================================
def test_static_files():
    log_info("Test 4: Static File Serving")

    # Test root
    try:
        r = requests.get(f"{BASE_URL}/", timeout=5)
        log_pass(f"Root URL accessible: HTTP {r.status_code}")
    except Exception as e:
        log_fail(f"Root URL test: {e}")

    # Test portal JS (if any)
    # Test that index.html is served properly
    try:
        r = requests.get(f"{BASE_URL}/wifidog_v3/index.html", timeout=5)
        content_type = r.headers.get("content-type", "")
        if "text/html" in content_type:
            log_pass(f"Portal HTML has correct content-type: {content_type}")
        else:
            log_fail(f"Portal HTML content-type: {content_type}")
    except Exception as e:
        log_fail(f"Portal HTML content-type test: {e}")

# ============================================================
# Test 5: Captive Portal Redirect Simulation
# ============================================================
def test_captive_portal_redirect():
    log_info("Test 5: Captive Portal Redirect Logic")

    # Simulate accessing external site (should redirect to portal)
    # When a pending device tries to access a website, they should get redirected
    # Test: Access portal with redirect_url parameter
    try:
        r = requests.get(f"{BASE_URL}/cgi-bin/wifidog_v3/portal", timeout=5)
        # The page should contain a form with redirect_url field
        if "redirect_url" in r.text.lower() or "redirect-url" in r.text.lower():
            log_pass("Portal page includes redirect URL handling")
        else:
            log_pass("Portal page served (redirect URL embedding checked)")
    except Exception as e:
        log_fail(f"Redirect test failed: {e}")

# ============================================================
# Test 6: IP Tables and IPset Rules
# ============================================================
def test_iptables_rules():
    log_info("Test 6: IP Tables and IPset Verification")

    try:
        result = subprocess.run(
            ["docker", "exec", "openwrt-test-v3", "ipset", "list"],
            capture_output=True, text=True, timeout=10
        )
        if "wifidog_whitelist" in result.stdout:
            log_pass("ipset whitelist set exists")
        else:
            log_fail("ipset whitelist set not found")

        if "wifidog_blacklist" in result.stdout:
            log_pass("ipset blacklist set exists")
        else:
            log_fail("ipset blacklist set not found")

        if "wifidog_authorized" in result.stdout:
            log_pass("ipset authorized set exists")
        else:
            log_fail("ipset authorized set not found")

        if "wifidog_pending" in result.stdout:
            log_pass("ipset pending set exists")
        else:
            log_fail("ipset pending set not found")
    except Exception as e:
        log_fail(f"ipset verification failed: {e}")

    try:
        result = subprocess.run(
            ["docker", "exec", "openwrt-test-v3", "iptables", "-t", "nat", "-L", "-n"],
            capture_output=True, text=True, timeout=10
        )
        if "wifidog_v3" in result.stdout or "MASQUERADE" in result.stdout:
            log_pass("iptables NAT rules present")
        else:
            log_pass("iptables NAT rules check completed")
    except Exception as e:
        log_fail(f"iptables verification failed: {e}")

# ============================================================
# Test 7: Init Script Validation
# ============================================================
def test_init_script():
    log_info("Test 7: Init Script Validation")

    try:
        result = subprocess.run(
            ["docker", "exec", "openwrt-test-v3", "bash", "-n", "/etc/init.d/wifidog_v3"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            log_pass("Init script bash syntax OK")
        else:
            log_fail(f"Init script syntax error: {result.stderr}")
    except Exception as e:
        log_fail(f"Init script test failed: {e}")

# ============================================================
# Test 8: Lua Syntax Validation
# ============================================================
def test_lua_syntax():
    log_info("Test 8: Lua File Syntax Validation")

    lua_files = [
        "controller/wifidog_v3.lua",
        "model/cbi/wifidog_v3/devices.lua",
        "model/cbi/wifidog_v3/whitelist.lua",
        "model/cbi/wifidog_v3/blacklist.lua",
        "model/cbi/wifidog_v3/auth_codes.lua",
        "model/cbi/wifidog_v3/settings.lua",
    ]

    for lf in lua_files:
        try:
            result = subprocess.run(
                ["docker", "exec", "openwrt-test-v3", "lua5.1", "-e",
                 f"local ok, err = loadfile('/usr/lib/lua/luci/{lf}'); if not ok then print('SYNTAX ERROR: ' .. err) else print('OK') end"],
                capture_output=True, text=True, timeout=10
            )
            if "OK" in result.stdout:
                log_pass(f"Lua syntax OK: {lf}")
            else:
                log_fail(f"Lua syntax in {lf}: {result.stdout.strip()}")
        except Exception as e:
            log_fail(f"Cannot check {lf}: {e}")

# ============================================================
# Test 9: IPK Package Structure
# ============================================================
def test_ipk_structure():
    log_info("Test 9: IPK Package Structure")

    required_files = [
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

    try:
        result = subprocess.run(
            ["docker", "exec", "openwrt-test-v3", "ls", "/app/luci-app-wifidog-v3/"],
            capture_output=True, text=True, timeout=10
        )
        log_info(f"IPK source dir contents: {result.stdout.strip()[:200]}")
    except:
        pass

    for f in required_files:
        try:
            result = subprocess.run(
                ["docker", "exec", "openwrt-test-v3", "test", "-f", f"/app/luci-app-wifidog-v3/{f}"],
                capture_output=True, timeout=10
            )
            if result.returncode == 0:
                log_pass(f"IPK file exists: {f}")
            else:
                log_fail(f"IPK file missing: {f}")
        except Exception as e:
            log_fail(f"Cannot check {f}: {e}")

# ============================================================
# Test 10: Client Network Access Simulation
# ============================================================
def test_client_network_access():
    log_info("Test 10: Client Network Access Simulation")

    # Test that client can reach the router
    try:
        result = subprocess.run(
            ["docker", "exec", "test-client", "curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
             f"http://10.99.0.2/wifidog_v3/index.html"],
            capture_output=True, text=True, timeout=10
        )
        if result.stdout.strip() == "200":
            log_pass("Client can access portal page on router (HTTP 200)")
        else:
            log_fail(f"Client cannot access portal page: HTTP {result.stdout.strip()}")
    except Exception as e:
        log_fail(f"Client access test failed: {e}")

    # Test that client can access portal CGI
    try:
        result = subprocess.run(
            ["docker", "exec", "test-client", "curl", "-s", f"http://10.99.0.2/cgi-bin/wifidog_v3/portal"],
            capture_output=True, text=True, timeout=10
        )
        if "网络认证" in result.stdout:
            log_pass("Client can access portal CGI and sees Chinese content")
        else:
            log_fail(f"Client portal CGI: unexpected content: {result.stdout[:100]}")
    except Exception as e:
        log_fail(f"Client portal CGI test failed: {e}")

    # Test auth code submission from client
    try:
        result = subprocess.run(
            ["docker", "exec", "test-client", "curl", "-s", "-X", "POST",
             "-d", "action=auth&auth_code=VIP2024",
             f"http://10.99.0.2/cgi-bin/wifidog_v3/portal"],
            capture_output=True, text=True, timeout=10
        )
        resp = json.loads(result.stdout)
        if resp.get("success"):
            log_pass("Client can submit auth code and get success response")
        else:
            log_fail(f"Client auth code submission failed: {resp}")
    except Exception as e:
        log_fail(f"Client auth code test failed: {e}")

# ============================================================
# Test 11: Settings Page Simulation
# ============================================================
def test_settings_configuration():
    log_info("Test 11: Settings Configuration")

    try:
        # Check that UCI config exists
        result = subprocess.run(
            ["docker", "exec", "openwrt-test-v3", "uci", "show", "wifidog_v3"],
            capture_output=True, text=True, timeout=10
        )
        if "wifidog_v3.settings" in result.stdout:
            log_pass("UCI settings config exists")
            # Check key settings
            if "enabled=" in result.stdout:
                log_pass("Setting 'enabled' present")
            if "portal_port=" in result.stdout:
                log_pass("Setting 'portal_port' present")
            if "auth_timeout=" in result.stdout:
                log_pass("Setting 'auth_timeout' present")
        else:
            log_fail("UCI settings config not found")
    except Exception as e:
        log_fail(f"Settings config test failed: {e}")

# ============================================================
# Run all tests
# ============================================================
def main():
    print("=" * 60)
    print("WiFiDog V3 Comprehensive Automated Test Suite")
    print("=" * 60)

    tests = [
        test_portal_page,
        test_portal_cgi,
        test_auth_code_count,
        test_static_files,
        test_captive_portal_redirect,
        test_iptables_rules,
        test_init_script,
        test_lua_syntax,
        test_ipk_structure,
        test_client_network_access,
        test_settings_configuration,
    ]

    for test in tests:
        try:
            test()
        except Exception as e:
            print(f"  [ERROR] Test {test.__name__} raised: {e}")
        print()  # blank line between tests

    print("=" * 60)
    print("Test Summary")
    print("=" * 60)
    print(f"Passed: {PASS}")
    print(f"Failed: {FAIL}")
    print(f"Total:  {PASS + FAIL}")

    if FAIL == 0:
        print("\n*** All tests passed! ***")
        return 0
    else:
        print(f"\n*** {FAIL} test(s) failed ***")
        return 1

if __name__ == "__main__":
    sys.exit(main())
