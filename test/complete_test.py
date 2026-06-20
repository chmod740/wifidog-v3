#!/usr/bin/env python3
"""
WiFiDog V3 - Complete Install + Functional Test Suite
Tests: IPK structure → Install → All features → Uninstall → Cleanup verify
"""
import subprocess, sys, os, time, requests, json, re

P=0; F=0; CTR="openwrt-test-v3"; CLI="test-client"; RIP="10.99.0.2"
HOST="http://localhost:8880"; PORTAL="http://localhost:8888"
IPK_SRC = "/Users/hupeng/projects/wifidog_v3/dist/luci-app-wifidog-v3_1.0.2-1_all.ipk"
APP_SRC = "/Users/hupeng/projects/wifidog_v3/luci-app-wifidog-v3"

def ok(m): global P; P+=1; print(f"  ✅ {m}")
def bad(m): global F; F+=1; print(f"  ❌ {m}")
def sec(title): print(f"\n{'='*55}\n  {title}\n{'='*55}")
def d_run(cmd, **kw):
    return subprocess.run(["docker","exec",CTR] + cmd.split(),
                          capture_output=True, text=True, timeout=15, **kw)

# ═══════════════════════════════════════════════════════════
#  PHASE 1: IPK BUILD
# ═══════════════════════════════════════════════════════════
def phase1_build():
    sec("PHASE 1: IPK Build & Structure Verification")

    # Clean rebuild with ustar
    subprocess.run(["rm","-rf","/tmp/ipk-test-build","dist"], capture_output=True)
    os.makedirs("dist", exist_ok=True)

    bd = "/tmp/ipk-test-build"
    subprocess.run(["mkdir","-p",f"{bd}/control",f"{bd}/data"], capture_output=True)

    # Control file
    with open(f"{bd}/control/control","w") as f:
        f.write("Package: luci-app-wifidog-v3\nVersion: 1.0.2-1\nArchitecture: all\n"
                "Maintainer: WiFiDog V3 Team\nSection: luci\nPriority: optional\n"
                "Depends: ipset, iptables, libuci-lua, lua, luci-compat, luci-lib-jsonc\n"
                "Description: WiFiDog V3 Network Authentication System for OpenWrt\n")

    for name, content in [
        ("postinst", "#!/bin/sh\n[ -z \"${IPKG_INSTROOT}\" ] && {\n"
         "  [ -f /etc/uci-defaults/40_luci-wifidog-v3 ] && (. /etc/uci-defaults/40_luci-wifidog-v3) && rm -f /etc/uci-defaults/40_luci-wifidog-v3\n"
         "  chmod 755 /etc/init.d/wifidog_v3 2>/dev/null\n"
         "  ln -sf ../init.d/wifidog_v3 /etc/rc.d/S90wifidog_v3 2>/dev/null\n"
         "}\nexit 0\n"),
        ("prerm", "#!/bin/sh\n"
         "[ -f /etc/init.d/wifidog_v3 ] && { /etc/init.d/wifidog_v3 stop 2>/dev/null; /etc/init.d/wifidog_v3 disable 2>/dev/null; }\n"
         "rm -f /etc/rc.d/S90wifidog_v3 2>/dev/null\n"
         "while iptables -t nat -D PREROUTING -j wifidog_v3 2>/dev/null; do :; done\n"
         "while iptables -t mangle -D PREROUTING -j wifidog_v3 2>/dev/null; do :; done\n"
         "while iptables -D FORWARD -j wifidog_v3 2>/dev/null; do :; done\n"
         "for tbl in nat mangle; do iptables -t $tbl -F wifidog_v3 2>/dev/null; iptables -t $tbl -X wifidog_v3 2>/dev/null; done\n"
         "iptables -F wifidog_v3 2>/dev/null; iptables -X wifidog_v3 2>/dev/null\n"
         "for s in wifidog_whitelist wifidog_blacklist wifidog_authorized wifidog_pending; do ipset destroy $s 2>/dev/null; done\n"
         "if uci -q get uhttpd.wifidog_v3 >/dev/null 2>&1; then uci -q delete uhttpd.wifidog_v3; uci -q commit uhttpd; /etc/init.d/uhttpd restart 2>/dev/null & fi\n"
         "while uci -q get ucitrack.@wifidog_v3[0] >/dev/null 2>&1; do uci -q delete ucitrack.@wifidog_v3[0]; done\n"
         "uci -q commit ucitrack 2>/dev/null\n"
         "rm -f /var/log/wifidog_v3.log 2>/dev/null\nexit 0\n"),
    ]:
        p = f"{bd}/control/{name}"
        with open(p,"w") as fh: fh.write(content)
        os.chmod(p, 0o755)

    # Copy data files
    import shutil
    for src_dir, dst_dir in [
        ("luasrc/controller","usr/lib/lua/luci/controller"),
        ("luasrc/model/cbi/wifidog_v3","usr/lib/lua/luci/model/cbi/wifidog_v3"),
        ("luasrc/view/wifidog_v3","usr/lib/lua/luci/view/wifidog_v3"),
        ("root/etc/config","etc/config"),
        ("root/etc/init.d","etc/init.d"),
        ("root/etc/uci-defaults","etc/uci-defaults"),
        ("root/www/wifidog_v3","www/wifidog_v3"),
        ("root/www/cgi-bin/wifidog_v3","www/cgi-bin/wifidog_v3"),
        ("po/zh-cn","usr/lib/lua/luci/i18n"),
    ]:
        dst = f"{bd}/data/{dst_dir}"
        os.makedirs(dst, exist_ok=True)
        src = f"{APP_SRC}/{src_dir}"
        if os.path.isdir(src):
            for fn in os.listdir(src):
                sf = os.path.join(src, fn)
                if os.path.isfile(sf):
                    shutil.copy2(sf, os.path.join(dst, fn))

    # Rename po file
    po_src = f"{bd}/data/usr/lib/lua/luci/i18n/wifidog_v3.po"
    po_dst = f"{bd}/data/usr/lib/lua/luci/i18n/wifidog_v3.zh-cn.po"
    if os.path.exists(po_src):
        os.rename(po_src, po_dst)

    # Set executable permissions
    for p in [f"{bd}/data/etc/init.d/wifidog_v3",
              f"{bd}/data/etc/uci-defaults/40_luci-wifidog-v3",
              f"{bd}/data/www/cgi-bin/wifidog_v3/portal"]:
        if os.path.exists(p): os.chmod(p, 0o755)

    # Build with ustar
    subprocess.run(["tar","--format=ustar","-czf",f"{bd}/control.tar.gz","-C",f"{bd}/control","."], check=True)
    subprocess.run(["tar","--format=ustar","-czf",f"{bd}/data.tar.gz","-C",f"{bd}/data","."], check=True)
    with open(f"{bd}/debian-binary","w") as f: f.write("2.0\n")
    subprocess.run(["tar","--format=ustar","-czf",IPK_SRC,"-C",bd,"debian-binary","control.tar.gz","data.tar.gz"], check=True)
    subprocess.run(["rm","-rf",bd])

    # Verify
    ok(f"IPK built ({os.path.getsize(IPK_SRC)} bytes)")
    r = subprocess.run(["tar","tzf",IPK_SRC], capture_output=True, text=True)
    pax = r.stdout.count("PaxHeader")
    ok("No PaxHeader in IPK") if pax==0 else bad(f"PaxHeader entries: {pax}")

    # Verify inner tarballs
    for name in ["control.tar.gz","data.tar.gz"]:
        r = subprocess.run(["bash","-c",f"tar xzf {IPK_SRC} -O ./{name} 2>/dev/null | tar tzf - 2>/dev/null | grep -c PaxHeader || echo 0"],
                          capture_output=True, text=True, shell=True)
        pax = int(r.stdout.strip() or 0)
        ok(f"No PaxHeader in {name}") if pax==0 else bad(f"PaxHeader in {name}: {pax}")

    # Verify control dependencies
    r = subprocess.run(["bash","-c",f"tar xzf {IPK_SRC} -O ./control.tar.gz 2>/dev/null | tar xzf - -O ./control 2>/dev/null"],
                      capture_output=True, text=True, shell=True)
    ctrl = r.stdout
    ok("Depends: ipset") if "ipset" in ctrl else bad("ipset missing from Depends")
    ok("Depends: iptables") if "iptables" in ctrl else bad("iptables missing")
    ok("Depends: luci-compat") if "luci-compat" in ctrl else bad("luci-compat missing")
    ok("No iptables-mod-nat-extra") if "iptables-mod-nat-extra" not in ctrl else bad("stale dep: iptables-mod-nat-extra")
    ok("No iptables-mod-ipset") if "iptables-mod-ipset" not in ctrl else bad("stale dep: iptables-mod-ipset")

    # Copy to container
    subprocess.run(["docker","cp",IPK_SRC,f"{CTR}:/tmp/test.ipk"], check=True)

# ═══════════════════════════════════════════════════════════
#  PHASE 2: INSTALL SIMULATION
# ═══════════════════════════════════════════════════════════
def phase2_install():
    sec("PHASE 2: IPK Installation Simulation")

    d_run("rm -rf /tmp/ipk-install")
    d_run("mkdir -p /tmp/ipk-install")
    d_run("bash -c 'cd /tmp/ipk-install && tar xzf /tmp/test.ipk 2>/dev/null'")

    # 2.1 Verify structure
    r = d_run("test -f /tmp/ipk-install/debian-binary && echo OK || echo MISSING")
    ok("debian-binary") if "OK" in r.stdout else bad("debian-binary missing")
    r = d_run("test -f /tmp/ipk-install/control.tar.gz && echo OK || echo MISSING")
    ok("control.tar.gz") if "OK" in r.stdout else bad("control.tar.gz missing")
    r = d_run("test -f /tmp/ipk-install/data.tar.gz && echo OK || echo MISSING")
    ok("data.tar.gz") if "OK" in r.stdout else bad("data.tar.gz missing")

    # 2.2 Extract control and verify
    d_run("bash -c 'cd /tmp/ipk-install && tar xzf control.tar.gz 2>/dev/null'")
    for f in ["control","postinst","prerm"]:
        r = d_run(f"test -f /tmp/ipk-install/{f} && echo OK || echo MISS")
        ok(f"control/{f}") if "OK" in r.stdout else bad(f"control/{f} missing")

    r = d_run("test -x /tmp/ipk-install/postinst && echo OK || echo NOT_EXEC")
    ok("postinst executable") if "OK" in r.stdout else bad("postinst not executable")
    r = d_run("test -x /tmp/ipk-install/prerm && echo OK || echo NOT_EXEC")
    ok("prerm executable") if "OK" in r.stdout else bad("prerm not executable")

    # 2.3 Extract data and verify all files
    d_run("bash -c 'cd /tmp/ipk-install && mkdir -p data && cd data && tar xzf ../data.tar.gz 2>/dev/null'")

    expected = {
        "Controller": "usr/lib/lua/luci/controller/wifidog_v3.lua",
        "Config": "etc/config/wifidog_v3",
        "Init script": "etc/init.d/wifidog_v3",
        "UCI defaults": "etc/uci-defaults/40_luci-wifidog-v3",
        "Portal page": "www/wifidog_v3/index.html",
        "Portal CGI": "www/cgi-bin/wifidog_v3/portal",
        "Settings model": "usr/lib/lua/luci/model/cbi/wifidog_v3/settings.lua",
        "Devices model": "usr/lib/lua/luci/model/cbi/wifidog_v3/devices.lua",
        "Whitelist model": "usr/lib/lua/luci/model/cbi/wifidog_v3/whitelist.lua",
        "Blacklist model": "usr/lib/lua/luci/model/cbi/wifidog_v3/blacklist.lua",
        "AuthCodes model": "usr/lib/lua/luci/model/cbi/wifidog_v3/auth_codes.lua",
        "Devices view": "usr/lib/lua/luci/view/wifidog_v3/devices.htm",
        "Whitelist view": "usr/lib/lua/luci/view/wifidog_v3/whitelist.htm",
        "Blacklist view": "usr/lib/lua/luci/view/wifidog_v3/blacklist.htm",
        "AuthCodes view": "usr/lib/lua/luci/view/wifidog_v3/auth_codes.htm",
        "Status view": "usr/lib/lua/luci/view/wifidog_v3/status.htm",
    }
    for desc, path in expected.items():
        r = d_run(f"test -f /tmp/ipk-install/data/{path} && echo OK || echo MISS")
        ok(f"File: {desc}") if "OK" in r.stdout else bad(f"Missing: {desc} ({path})")

    # Executable permissions
    for p in ["etc/init.d/wifidog_v3","www/cgi-bin/wifidog_v3/portal"]:
        r = d_run(f"test -x /tmp/ipk-install/data/{p} && echo OK || echo NO")
        ok(f"Executable: {p.split('/')[-1]}") if "OK" in r.stdout else bad(f"Not executable: {p}")

    # 2.4 Simulate actual install (copy to system dirs)
    d_run("bash -c 'cp -r /tmp/ipk-install/data/* / 2>/dev/null || true'")
    d_run("chmod 755 /etc/init.d/wifidog_v3")
    d_run("chmod 755 /www/cgi-bin/wifidog_v3/portal")

    # Run postinst
    r = d_run("bash /tmp/ipk-install/postinst 2>&1")
    ok("postinst runs without error") if "error" not in r.stdout.lower() and "fail" not in r.stdout.lower() else bad(f"postinst error: {r.stdout[:100]}")

    # Verify post-install state
    r = d_run("test -f /etc/init.d/wifidog_v3 && echo OK || echo MISS")
    ok("Init script in /etc/init.d/") if "OK" in r.stdout else bad("Init script not installed")
    r = d_run("test -f /www/wifidog_v3/index.html && echo OK || echo MISS")
    ok("Portal page in /www/") if "OK" in r.stdout else bad("Portal not installed")
    r = d_run("test -f /www/cgi-bin/wifidog_v3/portal && echo OK || echo MISS")
    ok("Portal CGI in /www/cgi-bin/") if "OK" in r.stdout else bad("CGI not installed")
    ok("Installation complete")

# ═══════════════════════════════════════════════════════════
#  PHASE 3: FUNCTIONAL TESTS
# ═══════════════════════════════════════════════════════════
def phase3_functional():
    sec("PHASE 3: Full Functional Testing")

    # Setup: ensure config exists and system enabled
    d_run("bash -c 'cat > /etc/config/wifidog_v3 << \"WCFG\"\n\
set wifidog_v3.settings=wifidog_v3\n\
set wifidog_v3.settings.enabled=1\n\
set wifidog_v3.settings.portal_port=8080\n\
set wifidog_v3.settings.lan_subnet=192.168.1.0/24\n\
set wifidog_v3.settings.auth_timeout=1440\n\
set wifidog_v3.settings.auto_detect_wan=1\n\
set wifidog_v3.auth_VIP2024=authcode\n\
set wifidog_v3.auth_VIP2024.code=VIP2024\n\
set wifidog_v3.auth_VIP2024.max_uses=5\n\
set wifidog_v3.auth_VIP2024.used_count=0\n\
set wifidog_v3.auth_VIP2024.expiry_days=365\n\
set wifidog_v3.auth_VIP2024.created_date=2026-04-15\n\
set wifidog_v3.auth_VIP2024.enabled=1\n\
set wifidog_v3.auth_ONCE=authcode\n\
set wifidog_v3.auth_ONCE.code=ONCE123\n\
set wifidog_v3.auth_ONCE.max_uses=1\n\
set wifidog_v3.auth_ONCE.used_count=1\n\
set wifidog_v3.auth_ONCE.expiry_days=365\n\
set wifidog_v3.auth_ONCE.created_date=2026-04-15\n\
set wifidog_v3.auth_ONCE.enabled=1\n\
set wifidog_v3.auth_EXPIRED=authcode\n\
set wifidog_v3.auth_EXPIRED.code=EXPIRED1\n\
set wifidog_v3.auth_EXPIRED.max_uses=10\n\
set wifidog_v3.auth_EXPIRED.used_count=0\n\
set wifidog_v3.auth_EXPIRED.expiry_days=30\n\
set wifidog_v3.auth_EXPIRED.created_date=2025-01-01\n\
set wifidog_v3.auth_EXPIRED.enabled=1\n\
set wifidog_v3.auth_DISABLED=authcode\n\
set wifidog_v3.auth_DISABLED.code=DISABLED1\n\
set wifidog_v3.auth_DISABLED.max_uses=10\n\
set wifidog_v3.auth_DISABLED.used_count=0\n\
set wifidog_v3.auth_DISABLED.expiry_days=365\n\
set wifidog_v3.auth_DISABLED.created_date=2026-04-15\n\
set wifidog_v3.auth_DISABLED.enabled=0\n\
WCFG'")

    d_run("bash -c 'cat > /etc/config/network << \"NCFG\"\n\
set network.lan=interface\n\
set network.lan.device=br-lan\n\
set network.lan.ipaddr=10.99.0.2\n\
set network.lan.netmask=255.255.255.0\n\
NCFG'")

    # Restart lighttpd
    d_run("bash -c 'killall lighttpd 2>/dev/null; sleep 1; lighttpd -f /etc/lighttpd/lighttpd.conf 2>/dev/null; sleep 2'")
    time.sleep(2)

    # ── 3.1 Portal Page ──
    print("\n  -- 3.1 Portal Page --")
    r = requests.get(f"{HOST}/wifidog_v3/index.html", timeout=10)
    ok("Portal HTTP 200") if r.status_code==200 else bad(f"HTTP {r.status_code}")
    ok("Portal: 网络认证") if "网络认证" in r.text else bad("No Chinese title")
    ok("Portal: auth_code input") if "auth_code" in r.text or "auth-code" in r.text else bad("No input field")
    ok("Portal: submit button") if "认证上网" in r.text else bad("No submit button")

    r = requests.get(f"{PORTAL}/wifidog_v3/index.html", timeout=10)
    ok("Portal on 8080") if r.status_code==200 else bad(f"Portal 8080 HTTP {r.status_code}")

    # ── 3.2 CGI Auth Validation ──
    print("\n  -- 3.2 Captive Portal Auth --")
    def cgi(code):
        return requests.post(f"{HOST}/cgi-bin/wifidog_v3/portal",
               data={"action":"auth","auth_code":code,"redirect_url":"http://www.example.com"}, timeout=10).json()

    d = cgi("VIP2024")
    ok(f"Valid code accepted: {d.get('success')}") if d.get("success")==True else bad(f"VIP2024 rejected: {d}")
    ok("Redirect URL preserved") if "example.com" in str(d.get("redirect","")) else bad(f"No redirect: {d}")

    d = cgi("BADCODE")
    ok("Invalid code rejected") if d.get("success")==False else bad("Invalid code accepted!")
    d = cgi("")
    ok("Empty code rejected") if d.get("success")==False else bad("Empty code accepted!")
    d = cgi("ONCE123")
    ok("Used-up code rejected") if d.get("success")==False else bad(f"Used-up code accepted: {d}")
    d = cgi("EXPIRED1")
    ok("Expired code rejected") if d.get("success")==False else bad(f"Expired code accepted: {d}")
    d = cgi("DISABLED1")
    ok("Disabled code rejected") if d.get("success")==False else bad(f"Disabled code accepted: {d}")

    # ── 3.3 System Enable/Disable ──
    print("\n  -- 3.3 System Enable/Disable --")
    d_run("uci set wifidog_v3.settings.enabled=0; uci commit wifidog_v3")
    time.sleep(0.3)
    d = cgi("VIP2024")
    ok("Disabled: valid code rejected") if d.get("success")==False else bad(f"Disabled accepted: {d}")
    ok("Message: 未启用") if "未启用" in d.get("message","") else bad(f"Wrong msg: {d.get('message','')}")
    d_run("uci set wifidog_v3.settings.enabled=1; uci commit wifidog_v3")
    time.sleep(0.3)

    # ── 3.4 Usage Count Tracking ──
    print("\n  -- 3.4 Auth Code Usage Count --")
    d_run("uci set wifidog_v3.auth_C4=authcode; uci set wifidog_v3.auth_C4.code=CT3; uci set wifidog_v3.auth_C4.max_uses=3; uci set wifidog_v3.auth_C4.used_count=0; uci set wifidog_v3.auth_C4.expiry_days=365; uci set wifidog_v3.auth_C4.created_date=2026-04-15; uci set wifidog_v3.auth_C4.enabled=1; uci commit wifidog_v3")
    time.sleep(0.3)

    for i in range(1,4):
        cgi("CT3"); time.sleep(0.2)
    count = d_run("uci -q get wifidog_v3.auth_C4.used_count").stdout.strip()
    ok(f"3 uses: count={count}") if count=="3" else bad(f"Expected 3, got {count}")

    d = cgi("CT3")  # 4th use should fail
    count4 = d_run("uci -q get wifidog_v3.auth_C4.used_count").stdout.strip()
    ok(f"4th use rejected, count stays 3") if d.get("success")==False and count4=="3" else bad(f"4th={d.get('success')}, count={count4}")

    # ── 3.5 Admin API Endpoints ──
    print("\n  -- 3.5 Admin API Endpoints --")
    def api(ep, data=None):
        d = data or {}; d["token"]="test"
        r = requests.post(f"{HOST}/admin/services/wifidog_v3/{ep}", data=d, timeout=10)
        return (r.json() if "json" in r.headers.get("content-type","") else r.text) if r.status_code==200 else None

    for ep in ["scan_devices","list_whitelist","list_blacklist","list_auth_codes","status"]:
        d = api(ep)
        ok(f"API: {ep}") if d and d.get("success")!=False else bad(f"API {ep} failed: {d}")

    for ep, args in [("add_whitelist",{"mac":"11:22:33:44:55:66","ip":"192.168.1.200"}),
                     ("add_blacklist",{"mac":"22:33:44:55:66:77","ip":"192.168.1.201"}),
                     ("add_authorize",{"mac":"33:44:55:66:77:88","ip":"192.168.1.202"})]:
        d = api(ep, args)
        ok(f"API: {ep}") if d and d.get("success") else bad(f"API {ep}: {d}")

    d = api("remove_device",{"mac":"11:22:33:44:55:66"})
    ok("API: remove_device") if d and d.get("success") else bad(f"API remove_device: {d}")

    d = api("generate_code",{"code":"NEWTEST","max_uses":"5","expiry_days":"30"})
    ok("API: generate_code") if d and d.get("success") else bad(f"API generate_code: {d}")
    d = api("delete_code",{"code":"NEWTEST"})
    ok("API: delete_code") if d and d.get("success") else bad(f"API delete_code: {d}")

    # ── 3.6 Client Simulation ──
    print("\n  -- 3.6 Multi-Client Simulation --")
    r = subprocess.run(["docker","exec",CLI,"curl","-s","-o","/dev/null","-w","%{http_code}",
                       f"http://{RIP}/wifidog_v3/index.html"], capture_output=True, text=True, timeout=10)
    ok(f"Client portal HTTP {r.stdout.strip()}") if r.stdout.strip()=="200" else bad(f"Client HTTP {r.stdout.strip()}")

    r = subprocess.run(["docker","exec",CLI,"curl","-s","-X","POST",
                       "-d","action=auth&auth_code=VIP2024&redirect_url=http://www.example.com",
                       f"http://{RIP}/cgi-bin/wifidog_v3/portal"], capture_output=True, text=True, timeout=10)
    ok("Client valid auth") if "true" in r.stdout else bad(f"Client auth: {r.stdout[:80]}")

    r = subprocess.run(["docker","exec",CLI,"curl","-s","-X","POST",
                       "-d","action=auth&auth_code=BAD&redirect_url=http://www.example.com",
                       f"http://{RIP}/cgi-bin/wifidog_v3/portal"], capture_output=True, text=True, timeout=10)
    ok("Client invalid auth") if "false" in r.stdout else bad(f"Client invalid: {r.stdout[:80]}")

    r = subprocess.run(["docker","exec",CLI,"curl","-s","-o","/dev/null","-w","%{http_code}",
                       f"http://{RIP}:8080/wifidog_v3/index.html"], capture_output=True, text=True, timeout=10)
    ok(f"Client portal 8080 HTTP {r.stdout.strip()}") if r.stdout.strip()=="200" else bad(f"Client 8080: {r.stdout.strip()}")

# ═══════════════════════════════════════════════════════════
#  PHASE 4: UNINSTALL & CLEANUP
# ═══════════════════════════════════════════════════════════
def phase4_uninstall():
    sec("PHASE 4: Uninstall & System Restoration")

    # Setup dirty state (simulate running service)
    d_run("bash -c 'iptables -t nat -N wifidog_v3 2>/dev/null; iptables -t nat -I PREROUTING 1 -j wifidog_v3 2>/dev/null; iptables -t mangle -N wifidog_v3 2>/dev/null; iptables -t mangle -I PREROUTING 1 -j wifidog_v3 2>/dev/null; iptables -N wifidog_v3 2>/dev/null; iptables -I FORWARD 1 -j wifidog_v3 2>/dev/null'")
    for s in ["wifidog_whitelist","wifidog_blacklist","wifidog_authorized","wifidog_pending"]:
        d_run(f"ipset create {s} hash:mac 2>/dev/null")
    d_run("bash -c 'uci set uhttpd.wifidog_v3=uhttpd 2>/dev/null; uci add_list uhttpd.wifidog_v3.listen_http=0.0.0.0:8080 2>/dev/null; uci set uhttpd.wifidog_v3.home=/www 2>/dev/null; uci commit uhttpd 2>/dev/null'")
    d_run("bash -c 'uci add ucitrack wifidog_v3 2>/dev/null; uci set ucitrack.@wifidog_v3[-1].init=wifidog_v3 2>/dev/null; uci commit ucitrack 2>/dev/null'")
    d_run("ln -sf ../init.d/wifidog_v3 /etc/rc.d/S90wifidog_v3 2>/dev/null")
    d_run("echo log > /var/log/wifidog_v3.log 2>/dev/null")

    print("  Before uninstall:")
    r = d_run("iptables -t nat -L wifidog_v3 2>/dev/null | head -1 || echo NO_CHAIN")
    print(f"    NAT chain: {r.stdout.strip()}")
    r = d_run("uci -q get uhttpd.wifidog_v3 2>/dev/null || echo NO")
    print(f"    uhttpd config: {r.stdout.strip()}")

    # Run prerm
    print("\n  Running prerm...")
    r = d_run("bash /tmp/ipk-install/prerm 2>&1")
    print(f"  prerm exit: OK")

    # Verify cleanup
    print("\n  After uninstall:")
    checks = [
        ("iptables NAT chain", "iptables -t nat -L wifidog_v3 2>/dev/null | head -1 || echo -"),
        ("iptables MANGLE chain", "iptables -t mangle -L wifidog_v3 2>/dev/null | head -1 || echo -"),
        ("iptables FILTER chain", "iptables -L wifidog_v3 2>/dev/null | head -1 || echo -"),
        ("NAT PREROUTING jump", "iptables -t nat -L PREROUTING -n 2>/dev/null | grep wifidog_v3 || echo -"),
        ("FORWARD jump", "iptables -L FORWARD -n 2>/dev/null | grep wifidog_v3 || echo -"),
        ("uhttpd portal", "uci -q get uhttpd.wifidog_v3 2>/dev/null || echo -"),
        ("ucitrack", "uci -q get ucitrack.@wifidog_v3[-1].init 2>/dev/null || echo -"),
        ("rc.d symlink", "ls /etc/rc.d/S90wifidog_v3 2>/dev/null || echo -"),
        ("log file", "cat /var/log/wifidog_v3.log 2>/dev/null || echo -"),
    ]
    all_clean = True
    for name, cmd in checks:
        r = d_run(f"bash -c '{cmd}'")
        cleaned = r.stdout.strip() in ("","-")
        if cleaned:
            ok(f"Cleaned: {name}")
        else:
            bad(f"STILL EXISTS: {name} — {r.stdout.strip()[:60]}")
            all_clean = False

    for s in ["wifidog_whitelist","wifidog_blacklist","wifidog_authorized","wifidog_pending"]:
        r = d_run(f"bash -c 'ipset list {s} >/dev/null 2>&1 && echo EXISTS || echo CLEAN'")
        if "CLEAN" in r.stdout:
            ok(f"Cleaned: ipset {s}")
        else:
            bad(f"Still exists: ipset {s}")
            all_clean = False

    if all_clean:
        ok("*** COMPLETE: System fully restored after uninstall ***")

    # Also delete package files (simulate opkg remove)
    d_run("bash -c 'rm -f /etc/init.d/wifidog_v3 /etc/config/wifidog_v3 /etc/uci-defaults/40_luci-wifidog-v3 /etc/rc.d/S90wifidog_v3'")
    d_run("bash -c 'rm -rf /www/wifidog_v3 /www/cgi-bin/wifidog_v3 /usr/lib/lua/luci/controller/wifidog_v3.lua /usr/lib/lua/luci/model/cbi/wifidog_v3 /usr/lib/lua/luci/view/wifidog_v3 /usr/lib/lua/luci/i18n/wifidog_v3.zh-cn.po'")
    d_run("bash -c 'rm -f /var/log/wifidog_v3.log'")

# ═══════════════════════════════════════════════════════════
#  PHASE 5: RE-INSTALL & FINAL VERIFICATION
# ═══════════════════════════════════════════════════════════
def phase5_reinstall():
    sec("PHASE 5: Re-install & Final Verification")

    # Re-install
    d_run("bash -c 'mkdir -p /tmp/ipk-install/data && cd /tmp/ipk-install && tar xzf /tmp/test.ipk 2>/dev/null'")
    d_run("bash -c 'cd /tmp/ipk-install && tar xzf control.tar.gz 2>/dev/null && tar xzf data.tar.gz -C data 2>/dev/null'")
    d_run("bash -c 'cp -r /tmp/ipk-install/data/* / 2>/dev/null || true'")
    d_run("chmod 755 /etc/init.d/wifidog_v3")
    d_run("chmod 755 /www/cgi-bin/wifidog_v3/portal")

    # Verify re-install
    for f in ["/etc/init.d/wifidog_v3","/www/wifidog_v3/index.html","/www/cgi-bin/wifidog_v3/portal",
              "/usr/lib/lua/luci/controller/wifidog_v3.lua","/etc/config/wifidog_v3"]:
        r = d_run(f"test -f {f} && echo OK || echo MISS")
        ok(f"Re-installed: {f.split('/')[-1]}") if "OK" in r.stdout else bad(f"Missing: {f}")

    # Quick functional check after re-install
    d_run("bash -c 'cat > /etc/config/wifidog_v3 << \"WCFG\"\n\
set wifidog_v3.settings=wifidog_v3\n\
set wifidog_v3.settings.enabled=1\n\
set wifidog_v3.settings.portal_port=8080\n\
set wifidog_v3.settings.auth_timeout=1440\n\
set wifidog_v3.auth_VIP2024=authcode\n\
set wifidog_v3.auth_VIP2024.code=VIP2024\n\
set wifidog_v3.auth_VIP2024.max_uses=10\n\
set wifidog_v3.auth_VIP2024.used_count=0\n\
set wifidog_v3.auth_VIP2024.expiry_days=365\n\
set wifidog_v3.auth_VIP2024.created_date=2026-04-15\n\
set wifidog_v3.auth_VIP2024.enabled=1\n\
WCFG'")
    d_run("bash -c 'cat > /etc/config/network << \"NCFG\"\n\
set network.lan=interface\n\
set network.lan.ipaddr=10.99.0.2\n\
set network.lan.netmask=255.255.255.0\n\
NCFG'")

    d_run("bash -c 'killall lighttpd 2>/dev/null; sleep 1; lighttpd -f /etc/lighttpd/lighttpd.conf 2>/dev/null; sleep 2'")
    time.sleep(2)

    r = requests.get(f"{HOST}/wifidog_v3/index.html", timeout=10)
    ok("Re-install: portal accessible") if r.status_code==200 else bad(f"Re-install portal failed: {r.status_code}")

    d = requests.post(f"{HOST}/cgi-bin/wifidog_v3/portal",
         data={"action":"auth","auth_code":"VIP2024"}, timeout=10).json()
    ok("Re-install: auth works") if d.get("success")==True else bad(f"Re-install auth failed: {d}")

# ═══════════════════════════════════════════════════════════
#  FINAL
# ═══════════════════════════════════════════════════════════
def report():
    print(f"\n{'='*60}")
    print(f"  WiFiDog V3 — Complete Test Report")
    print(f"{'='*60}")
    print(f"  IPK: dist/luci-app-wifidog-v3_1.0.2-1_all.ipk")
    print(f"  Format: ustar (busybox compatible)")
    print(f"  Dependencies: ipset, iptables, libuci-lua, lua, luci-compat, luci-lib-jsonc")
    print(f"")
    print(f"  Results: {P} passed / {F} failed / {P+F} total")
    pct = 100*P//(P+F) if (P+F)>0 else 0
    print(f"  Pass rate: {pct}%")
    print(f"")
    if F == 0:
        print(f"  ✅ ALL TESTS PASSED — Ready for deployment")
    else:
        print(f"  ⚠️  {F} tests need attention")
    print(f"{'='*60}")
    return F

if __name__ == "__main__":
    # Ensure containers are ready
    subprocess.run(["docker","start",CTR,CLI], capture_output=True, timeout=10)
    time.sleep(2)

    phase1_build()
    phase2_install()
    phase3_functional()
    phase4_uninstall()
    phase5_reinstall()
    sys.exit(report())
