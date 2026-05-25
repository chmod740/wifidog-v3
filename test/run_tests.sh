#!/bin/bash
# Comprehensive test script for WiFiDog V3

set -e

PASS=0
FAIL=0
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_pass() { echo -e "${GREEN}[PASS]${NC} $1"; PASS=$((PASS+1)); }
log_fail() { echo -e "${RED}[FAIL]${NC} $1"; FAIL=$((FAIL+1)); }
log_info() { echo -e "${YELLOW}[INFO]${NC} $1"; }

echo "=========================================="
echo "WiFiDog V3 Test Suite"
echo "=========================================="

# ============================================
# Test 1: File Structure Verification
# ============================================
log_info "Test 1: File Structure Verification"

check_file() {
    if [ -f "$1" ] || [ -d "$1" ]; then
        log_pass "File exists: $1"
    else
        log_fail "Missing file: $1"
    fi
}

check_file "/etc/config/wifidog_v3"
check_file "/etc/init.d/wifidog_v3"
check_file "/usr/lib/lua/luci/controller/wifidog_v3.lua"
check_file "/usr/lib/lua/luci/model/cbi/wifidog_v3/devices.lua"
check_file "/usr/lib/lua/luci/model/cbi/wifidog_v3/whitelist.lua"
check_file "/usr/lib/lua/luci/model/cbi/wifidog_v3/blacklist.lua"
check_file "/usr/lib/lua/luci/model/cbi/wifidog_v3/auth_codes.lua"
check_file "/usr/lib/lua/luci/model/cbi/wifidog_v3/settings.lua"
check_file "/usr/lib/lua/luci/view/wifidog_v3/devices.htm"
check_file "/usr/lib/lua/luci/view/wifidog_v3/whitelist.htm"
check_file "/usr/lib/lua/luci/view/wifidog_v3/blacklist.htm"
check_file "/usr/lib/lua/luci/view/wifidog_v3/auth_codes.htm"
check_file "/usr/lib/lua/luci/view/wifidog_v3/status.htm"
check_file "/www/wifidog_v3/index.html"
check_file "/www/cgi-bin/wifidog_v3/portal"

# Check executable permissions
if [ -x "/www/cgi-bin/wifidog_v3/portal" ]; then
    log_pass "Portal CGI is executable"
else
    log_fail "Portal CGI is not executable"
fi

if [ -x "/etc/init.d/wifidog_v3" ]; then
    log_pass "Init script is executable"
else
    log_fail "Init script is not executable"
fi

# ============================================
# Test 2: UCI Configuration
# ============================================
log_info "Test 2: UCI Configuration Tests"

# Test uci get
SETTINGS_ENABLED=$(uci -q get wifidog_v3.settings.enabled 2>/dev/null || echo "")
if [ "$SETTINGS_ENABLED" = "0" ]; then
    log_pass "UCI get: settings.enabled = 0 (correct default)"
else
    log_fail "UCI get: settings.enabled = $SETTINGS_ENABLED (expected 0)"
fi

# Test uci set
uci set wifidog_v3.settings.enabled=1
uci commit wifidog_v3
NEW_VAL=$(uci -q get wifidog_v3.settings.enabled 2>/dev/null)
if [ "$NEW_VAL" = "1" ]; then
    log_pass "UCI set: settings.enabled = 1"
else
    log_fail "UCI set: settings.enabled = $NEW_VAL (expected 1)"
fi

# Reset
uci set wifidog_v3.settings.enabled=0
uci commit wifidog_v3

# Test auth code lookup
VIP_CODE=$(uci -q get wifidog_v3.auth_VIP2024.code 2>/dev/null)
if [ "$VIP_CODE" = "VIP2024" ]; then
    log_pass "UCI get: auth code VIP2024 exists"
else
    log_fail "UCI get: auth code VIP2024 not found ($VIP_CODE)"
fi

# ============================================
# Test 3: Auth Code Validation Logic
# ============================================
log_info "Test 3: Auth Code Validation Logic"

# Test valid code
uci set wifidog_v3.settings.enabled=1
uci commit wifidog_v3

# Simulate the portal CGI validation logic
test_auth_code() {
    local code="$1"
    local expected="$2"

    # Simulate CGI: check auth code
    FOUND=0
    CODE_ENABLED=0
    MAX_USES=0
    USED_COUNT=0
    EXPIRY_DAYS=30
    CREATED_DATE=""
    SECTION_NAME=""

    for section in $(uci show wifidog_v3 2>/dev/null | grep -E "\.code=" | cut -d. -f1-2 | sort -u); do
        cfg="${section#wifidog_v3.}"
        code_val=$(uci -q get "wifidog_v3.${cfg}.code" 2>/dev/null)
        if [ "$code_val" = "$code" ]; then
            SECTION_NAME="$cfg"
            CODE_ENABLED=$(uci -q get "wifidog_v3.${cfg}.enabled" 2>/dev/null || echo "0")
            MAX_USES=$(uci -q get "wifidog_v3.${cfg}.max_uses" 2>/dev/null || echo "1")
            USED_COUNT=$(uci -q get "wifidog_v3.${cfg}.used_count" 2>/dev/null || echo "0")
            FOUND=1
            break
        fi
    done

    local result="invalid"
    if [ "$FOUND" = "1" ] && [ "$CODE_ENABLED" = "1" ]; then
        if [ "$USED_COUNT" -lt "$MAX_USES" ]; then
            result="valid"
        fi
    fi

    if [ "$result" = "$expected" ]; then
        log_pass "Auth code '$code': expected=$expected, got=$result"
    else
        log_fail "Auth code '$code': expected=$expected, got=$result"
    fi
}

test_auth_code "VIP2024" "valid"
test_auth_code "TEST123" "invalid"  # used_count (1) >= max_uses (1)
test_auth_code "INVALID" "invalid"
test_auth_code "" "invalid"

uci set wifidog_v3.settings.enabled=0
uci commit wifidog_v3

# ============================================
# Test 4: Portal CGI Script
# ============================================
log_info "Test 4: Portal CGI Script Tests"

# Test GET request (serve portal page)
echo "Testing portal CGI GET..."
PORTAL_HTML=$(REQUEST_METHOD=GET REMOTE_ADDR=192.168.1.100 /www/cgi-bin/wifidog_v3/portal 2>&1 || true)
if echo "$PORTAL_HTML" | grep -q "网络认证"; then
    log_pass "Portal CGI GET: serves auth page with Chinese text"
else
    log_fail "Portal CGI GET: page does not contain expected content"
    log_info "Output preview: $(echo "$PORTAL_HTML" | head -5)"
fi

# Test POST with valid auth code (system disabled)
echo "Testing portal CGI POST (system disabled)..."
POST_RESULT=$(echo "action=auth&auth_code=VIP2024" | REQUEST_METHOD=POST REMOTE_ADDR=192.168.1.100 /www/cgi-bin/wifidog_v3/portal 2>&1 || true)
if echo "$POST_RESULT" | grep -q "false"; then
    log_pass "Portal CGI POST: rejects auth when system disabled (expected)"
else
    log_fail "Portal CGI POST: unexpected response: $(echo "$POST_RESULT" | head -3)"
fi

# Enable system and test
uci set wifidog_v3.settings.enabled=1
uci commit wifidog_v3

echo "Testing portal CGI POST (system enabled)..."
POST_RESULT=$(echo "action=auth&auth_code=VIP2024" | REQUEST_METHOD=POST REMOTE_ADDR=192.168.1.100 /www/cgi-bin/wifidog_v3/portal 2>&1 || true)
if echo "$POST_RESULT" | grep -q "true"; then
    log_pass "Portal CGI POST: accepts valid auth code VIP2024"
else
    log_fail "Portal CGI POST: valid code not accepted: $(echo "$POST_RESULT" | head -3)"
fi

# Check that usage count was incremented
USED=$(uci -q get wifidog_v3.auth_VIP2024.used_count 2>/dev/null)
if [ "$USED" = "1" ]; then
    log_pass "Portal CGI: usage count incremented from 0 to 1"
else
    log_fail "Portal CGI: usage count = $USED (expected 1)"
fi

uci set wifidog_v3.settings.enabled=0
uci commit wifidog_v3

# ============================================
# Test 5: Init Script Syntax
# ============================================
log_info "Test 5: Init Script Syntax Check"

# Check syntax with bash -n
if bash -n /etc/init.d/wifidog_v3 2>&1; then
    log_pass "Init script: bash syntax OK"
else
    log_fail "Init script: bash syntax error"
fi

# ============================================
# Test 6: Lua Controller Syntax
# ============================================
log_info "Test 6: Lua Controller Syntax Check"

for lua_file in /usr/lib/lua/luci/controller/wifidog_v3.lua \
                /usr/lib/lua/luci/model/cbi/wifidog_v3/devices.lua \
                /usr/lib/lua/luci/model/cbi/wifidog_v3/whitelist.lua \
                /usr/lib/lua/luci/model/cbi/wifidog_v3/blacklist.lua \
                /usr/lib/lua/luci/model/cbi/wifidog_v3/auth_codes.lua \
                /usr/lib/lua/luci/model/cbi/wifidog_v3/settings.lua; do
    if [ -f "$lua_file" ]; then
        # Check Lua syntax
        if lua5.1 -e "local f = assert(loadfile('$lua_file'))" 2>&1 | grep -q "error"; then
            log_fail "Lua syntax error in: $lua_file"
            lua5.1 -e "local f = assert(loadfile('$lua_file'))" 2>&1
        else
            log_pass "Lua syntax OK: $lua_file"
        fi
    fi
done

# ============================================
# Test 7: Firewall Rules Generation
# ============================================
log_info "Test 7: Firewall Rules Tests"

# Test ipset
ipset create test_whitelist hash:mac -exist 2>/dev/null && log_pass "ipset: can create test set" || log_fail "ipset: cannot create set"
ipset add test_whitelist aa:bb:cc:dd:ee:01 -exist 2>/dev/null && log_pass "ipset: can add entry" || log_fail "ipset: cannot add entry"
ipset destroy test_whitelist 2>/dev/null

# Test iptables
iptables -N TEST_WIFIDOG 2>/dev/null && log_pass "iptables: can create chain" || log_fail "iptables: cannot create chain"
iptables -A TEST_WIFIDOG -j ACCEPT 2>/dev/null && log_pass "iptables: can add rule" || log_fail "iptables: cannot add rule"
iptables -F TEST_WIFIDOG 2>/dev/null
iptables -X TEST_WIFIDOG 2>/dev/null
log_pass "iptables: cleanup OK"

# ============================================
# Test 8: Lighttpd Serving
# ============================================
log_info "Test 8: Web Server Tests"

# Start lighttpd if not running
if ! pgrep lighttpd > /dev/null 2>&1; then
    lighttpd -f /etc/lighttpd/lighttpd.conf 2>&1 || true
    sleep 2
fi

# Test static file serving
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:80/wifidog_v3/index.html 2>/dev/null || echo "000")
if [ "$HTTP_CODE" = "200" ]; then
    log_pass "Web server: portal page accessible (HTTP $HTTP_CODE)"
else
    log_fail "Web server: cannot access portal page (HTTP $HTTP_CODE)"
fi

# ============================================
# Test 9: IPK Build Structure
# ============================================
log_info "Test 9: IPK Build Structure"

# Check that Makefile exists for building
if [ -f "/app/luci-app-wifidog-v3/Makefile" ]; then
    log_pass "IPK: Makefile exists"
else
    log_fail "IPK: Makefile missing"
fi

# Check that all required directories exist in source
for dir in luasrc/controller luasrc/model/cbi/wifidog_v3 luasrc/view/wifidog_v3 root/etc/config root/etc/init.d po/zh-cn; do
    if [ -d "/app/luci-app-wifidog-v3/$dir" ]; then
        log_pass "IPK source: directory $dir exists"
    else
        log_fail "IPK source: directory $dir missing"
    fi
done

# ============================================
# Summary
# ============================================
echo ""
echo "=========================================="
echo "Test Summary"
echo "=========================================="
echo -e "${GREEN}Passed: $PASS${NC}"
echo -e "${RED}Failed: $FAIL${NC}"
echo "Total: $((PASS + FAIL))"

if [ "$FAIL" -eq 0 ]; then
    echo -e "\n${GREEN}All tests passed!${NC}"
    exit 0
else
    echo -e "\n${RED}Some tests failed. Please review.${NC}"
    exit 1
fi
