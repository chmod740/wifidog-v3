# WiFiDog V3

[中文](README.md)

WiFiDog V3 is a LuCI network authentication system for OpenWrt. It manages pending devices, whitelists, blacklists, authorization codes, and Captive Portal access control directly on the router.

## Demo

![Captive Portal demo](docs/assets/captive-portal-demo.gif)

## LuCI Admin Screenshots

The screenshots below were captured from the actual LuCI pages in a Docker OpenWrt 23.05.6 environment.

### Device Scan

![Device scan](docs/assets/luci/devices.png)

### Whitelist

![Whitelist](docs/assets/luci/whitelist.png)

### Blacklist

![Blacklist](docs/assets/luci/blacklist.png)

### Authorization Codes

![Authorization codes](docs/assets/luci/auth-codes.png)

### Backup And Restore

![Backup and restore](docs/assets/luci/backup.png)

### Runtime Logs

![Runtime logs](docs/assets/luci/logs.png)

### Settings

![Settings](docs/assets/luci/settings.png)

## Features

- Device discovery from ARP tables and DHCP leases.
- Device list management for pending, whitelisted, blacklisted, and authorized clients.
- MAC-bound notes that survive list transitions.
- Device identification from Portal User-Agent strings, including device type, OS, browser, and detectable model/family, preserved by MAC address.
- Whitelist mode: unrestricted LAN and WAN access.
- Blacklist mode: LAN access allowed, public Internet blocked, self-service authorization disabled.
- Manual authorization from LuCI with a default 24-hour validity period.
- Authorization codes with custom code values, usage limits, code expiration, per-code authorization lifetime, enable/disable state, and self-service login.
- FreeRADIUS PAP authentication can run alongside authorization codes and honors `Session-Timeout` for per-login access lifetime.
- Captive Portal compatibility:
  - RFC 8908 Captive Portal API
  - RFC 8910 DHCP option 114
  - odhcpd captive portal URI
  - Legacy probes used by iOS, Android, Windows, and NetworkManager
- Portal UI served by a dedicated uhttpd instance, with selectable themes and editable copy.
- Backup and restore for settings, lists, notes, authorization codes, and portal UI settings.
- Runtime log viewer for app logs and related syslog entries, with safe app-log clearing.
- Passwall2 coexistence using early-priority nftables rules to enforce authorization before traffic splitting where possible.
- Safe uninstall cleanup for nftables, portal processes, DHCP/RA advertisements, runtime state, and config files.

## Supported Versions

Validated targets:

- OpenWrt 23.05.6 x86/64: IPK
- OpenWrt 24.10.6 x86/64: IPK
- OpenWrt 25.12.3 x86/64: APK

Runtime dependencies:

- firewall4
- nftables-json
- lua
- uhttpd
- libuci-lua
- luci-compat
- luci-lib-jsonc
- luasocket

## Build

Build the OpenWrt 23/24 IPK:

```sh
./build_ipk.sh
```

Output:

```text
dist/luci-app-wifidog-v3_1.0.2-1_all.ipk
```

Build the OpenWrt 25 APK:

```sh
./build_openwrt25_apk.sh
```

Output:

```text
dist/openwrt25/luci-app-wifidog-v3-1.0.2-r1.apk
```

## Install

Latest release packages:

- Release: <https://github.com/chmod740/wifidog-v3/releases/tag/v1.0.2>
- IPK: `luci-app-wifidog-v3_1.0.2-1_all.ipk`
- APK: `luci-app-wifidog-v3-1.0.2-r1.apk`

OpenWrt 23/24:

```sh
opkg update
opkg install /tmp/luci-app-wifidog-v3_1.0.2-1_all.ipk
```

OpenWrt 25:

```sh
apk add --allow-untrusted /tmp/luci-app-wifidog-v3-1.0.2-r1.apk
```

After installation, open LuCI:

```text
Services -> WiFiDog V3
```

The service can also be controlled from the shell:

```sh
/etc/init.d/wifidog_v3 start
/etc/init.d/wifidog_v3 stop
/etc/init.d/wifidog_v3 restart
```

## Configuration

Main UCI config:

```text
/etc/config/wifidog_v3
```

Common options:

- `enabled`: enable or disable the system
- `lan_interface`: LAN interface
- `wan_interface`: WAN interface
- `portal_port`: portal port, default `8080`
- `lan_subnet`: LAN subnet
- `auth_code_enabled`: enable authorization-code login, default `1`
- `auth_timeout`: authorization lifetime in minutes, default `1440`
- `authcode.*.auth_minutes`: per-code authorization lifetime in minutes; empty values fall back to `auth_timeout`
- `device.*.user_agent` / `ua_summary`: raw Portal User-Agent and parsed device summary
- `radius_enabled`: enable RADIUS authentication, default `0`
- `radius_server` / `radius_port` / `radius_secret`: FreeRADIUS server address, port, and shared secret
- `radius_nas_id`: NAS Identifier sent to the RADIUS server
- `radius_timeout` / `radius_retries`: RADIUS request timeout and retry count
- `portal_theme`: portal theme
- `portal_title`: portal page title
- `portal_prompt`: main portal prompt
- `portal_hint`: portal hint text
- `portal_button_text`: portal button text

## Testing

Docker regression:

```sh
python3 test/e2e_openwrt23_container.py
```

OpenWrt 25 / APK mode:

```sh
PKG_MANAGER=apk python3 test/e2e_openwrt23_container.py
```

UTM smoke test:

```sh
lua /tmp/utm_smoke.lua
```

Latest regression results:

- Docker OpenWrt 23.05.6: `107 passed, 0 failed`
- UTM OpenWrt 23.05.6: install, portal, authorization codes, RADIUS, Passwall2 coexistence, disable, and uninstall cleanup passed
- UTM OpenWrt 24.10.6: install, portal, authorization codes, RADIUS PAP, `Session-Timeout`, runtime logs, disable, and uninstall cleanup passed
- UTM OpenWrt 25.12.3: APK install, portal, authorization codes, RADIUS PAP, `Session-Timeout`, runtime logs, disable, and uninstall cleanup passed

UTM 24/25 uninstall checks confirmed no leftovers for:

- package records
- portal uhttpd processes
- `/www/wifidog_v3`
- `/www/cgi-bin/wifidog_v3`
- `/etc/config/wifidog_v3`
- `/var/run/wifidog_v3_portal.pid`
- `inet wifidog_v3` nftables table

## Uninstall

OpenWrt 23/24:

```sh
opkg remove luci-app-wifidog-v3
```

OpenWrt 25:

```sh
apk del luci-app-wifidog-v3
```

The uninstall scripts clean:

- `/etc/config/wifidog_v3`
- `/www/wifidog_v3`
- dedicated uhttpd portal processes
- `inet wifidog_v3` nftables table
- `/tmp/dnsmasq.d/wifidog_v3.conf`
- `dhcp.lan.captive_portal_uri`
- `/tmp/wifidog_v3_ip_sessions`

## Notes

- HTTPS interception may show certificate warnings. This is a common Captive Portal limitation; OS captive portal probes should be preferred for opening the login page.
- iOS captive portal window closing depends on the system re-checking network status. The portal polls the Captive Portal API and triggers compatible probes as a fallback.
- If clients use randomized MAC addresses, authorization, notes, and list state are bound to the current randomized MAC.
