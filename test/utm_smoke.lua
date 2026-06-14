local http = require "luci.http"
local controller = require "luci.controller.wifidog_v3"

local form = {}
local last_json = nil
local last_write = ""
local failed = 0

function http.formvalue(key)
	return form[key]
end

function http.prepare_content(_) end
function http.header(_, _) end

function http.write_json(value)
	last_json = value
	if value and value.success ~= nil then
		print((value.success and "JSON_SUCCESS " or "JSON_FAIL ") .. tostring(value.message or ""))
	end
end

function http.write(value)
	last_write = tostring(value or "")
	print("WRITE_LEN " .. tostring(#last_write))
end

local function read_cmd(cmd)
	local fp = io.popen(cmd .. " 2>/dev/null")
	if not fp then return "" end
	local data = fp:read("*a") or ""
	fp:close()
	return (data:gsub("^%s+", ""):gsub("%s+$", ""))
end

local function pass(name)
	print("PASS " .. name)
end

local function fail(name, detail)
	failed = failed + 1
	print("FAIL " .. name .. " " .. tostring(detail or ""))
end

local function expect(name, condition, detail)
	if condition then
		pass(name)
	else
		fail(name, detail)
	end
end

local function run_action(values, action)
	form = values or {}
	last_json = nil
	last_write = ""
	action()
	return last_json, last_write
end

local function section(mac)
	return mac:lower():gsub(":", "_")
end

local function uci_get(path)
	return read_cmd("uci -q get " .. path)
end

local api = read_cmd("wget -q -O- http://127.0.0.1:8080/captive-portal/api")
expect("rfc8908 api reachable", api:find('"captive":true', 1, true) ~= nil and api:find("user-portal-url", 1, true) ~= nil, api)
local dhcp_advert = read_cmd("cat /tmp/dnsmasq.d/wifidog_v3.conf")
expect("rfc8910 dhcp option advertised", dhcp_advert:find("dhcp-option=114,", 1, true) ~= nil and dhcp_advert:find("/captive-portal/api", 1, true) ~= nil, dhcp_advert)
expect("rfc8910 odhcpd dhcp ra advertised", uci_get("dhcp.lan.captive_portal_uri"):find("/captive-portal/api", 1, true) ~= nil, uci_get("dhcp.lan.captive_portal_uri"))

local mac = "AA:BB:CC:DD:EE:31"
local sec = section(mac)

os.execute("uci -q delete wifidog_v3." .. sec .. " >/dev/null 2>&1")
os.execute("uci -q commit wifidog_v3 >/dev/null 2>&1")

local iphone_ua = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
os.execute("printf '%s\\n' '1893456000 " .. mac .. " 192.168.77.31 utm-phone *' >> /tmp/dhcp.leases")
read_cmd('env REQUEST_METHOD=GET REQUEST_URI=/portal REMOTE_ADDR=192.168.77.31 HTTP_USER_AGENT="' .. iphone_ua .. '" /www/wifidog_v3/cgi-bin/wifidog_v3/portal >/tmp/wifidog_v3_ua_probe.html && echo ok')
expect("portal records parsed ua", uci_get("wifidog_v3." .. sec .. ".ua_summary"):find("iPhone", 1, true) ~= nil and uci_get("wifidog_v3." .. sec .. ".ua_summary"):find("iOS 17.5", 1, true) ~= nil and uci_get("wifidog_v3." .. sec .. ".ua_browser"):find("Safari 17.5", 1, true) ~= nil and uci_get("wifidog_v3." .. sec .. ".ua_device_type") == "手机")

run_action({
	mac = mac,
	ip = "192.168.77.31",
	hostname = "utm-phone",
	note = "UTM-NOTE"
}, controller.action_update_note)
expect("pending note saved", uci_get("wifidog_v3." .. sec .. ".type") == "pending" and uci_get("wifidog_v3." .. sec .. ".note") == "UTM-NOTE" and uci_get("wifidog_v3." .. sec .. ".ua_summary"):find("iPhone", 1, true) ~= nil)

run_action({
	mac = mac,
	ip = "192.168.77.31",
	hostname = "utm-phone",
	note = ""
}, controller.action_add_whitelist)
expect("pending to whitelist keeps note and ua", uci_get("wifidog_v3." .. sec .. ".type") == "whitelist" and uci_get("wifidog_v3." .. sec .. ".note") == "UTM-NOTE" and uci_get("wifidog_v3." .. sec .. ".ua_summary"):find("iPhone", 1, true) ~= nil)

run_action({ mac = mac }, controller.action_remove_device)
expect("whitelist remove keeps pending note and ua", uci_get("wifidog_v3." .. sec .. ".type") == "pending" and uci_get("wifidog_v3." .. sec .. ".note") == "UTM-NOTE" and uci_get("wifidog_v3." .. sec .. ".ua_summary"):find("iPhone", 1, true) ~= nil)

run_action({
	mac = mac,
	ip = "192.168.77.31",
	hostname = "utm-phone",
	note = ""
}, controller.action_add_authorize)
expect("manual auth keeps note and ua", uci_get("wifidog_v3." .. sec .. ".type") == "authorized" and uci_get("wifidog_v3." .. sec .. ".note") == "UTM-NOTE" and uci_get("wifidog_v3." .. sec .. ".auth_source") == "manual" and uci_get("wifidog_v3." .. sec .. ".ua_summary"):find("iPhone", 1, true) ~= nil)

run_action({
	mac = mac,
	ip = "192.168.77.31",
	hostname = "utm-phone",
	note = ""
}, controller.action_add_blacklist)
expect("authorized to blacklist keeps note and ua", uci_get("wifidog_v3." .. sec .. ".type") == "blacklist" and uci_get("wifidog_v3." .. sec .. ".note") == "UTM-NOTE" and uci_get("wifidog_v3." .. sec .. ".ua_summary"):find("iPhone", 1, true) ~= nil)

run_action({}, controller.action_export_config)
expect("export contains note", last_write:find('"app"%s*:%s*"wifidog_v3"') ~= nil and last_write:find("UTM%-NOTE") ~= nil, last_write)
expect("export contains ua metadata", last_write:find("ua_summary", 1, true) ~= nil and last_write:find("iPhone", 1, true) ~= nil, last_write)

local backup_json = [[{
	"app": "wifidog_v3",
	"format_version": 1,
	"settings": {
		"enabled": "1",
		"wan_interface": "eth0",
		"lan_interface": "eth0",
		"portal_port": "8080",
		"lan_subnet": "192.168.77.0/24",
		"auth_code_enabled": "1",
		"auth_timeout": "1440",
		"radius_enabled": "0",
		"radius_port": "1812",
		"radius_nas_id": "wifidog-v3",
		"radius_timeout": "3",
		"radius_retries": "1",
		"auto_detect_wan": "1"
	},
	"devices": [
		{
			"mac": "AA:BB:CC:DD:EE:32",
			"ip": "192.168.77.32",
			"hostname": "utm-backup",
			"note": "UTM-BACKUP-NOTE",
			"type": "whitelist",
			"auth_expiry": "0",
			"user_agent": "Mozilla/5.0 (Linux; Android 14; Pixel 8 Build/AP1A.240505.005) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36",
			"ua_device_type": "手机",
			"ua_os": "Android 14",
			"ua_browser": "Chrome 125.0.0.0",
			"ua_model": "Pixel 8",
			"ua_summary": "Pixel 8 / Android 14 / Chrome 125.0.0.0",
			"ua_seen": "1779450001",
			"created": "1779450000"
		}
	],
	"auth_codes": [
		{
			"code": "UTMBACKUP",
			"max_uses": "5",
			"used_count": "1",
			"expiry_days": "30",
			"auth_minutes": "45",
			"created_date": "2026-05-22",
			"enabled": "1"
		}
	]
}]]

run_action({ config_json = backup_json }, controller.action_import_config)
local import_sec = section("AA:BB:CC:DD:EE:32")
expect("import restores whitelist note", uci_get("wifidog_v3." .. import_sec .. ".type") == "whitelist" and uci_get("wifidog_v3." .. import_sec .. ".note") == "UTM-BACKUP-NOTE")
expect("import restores ua metadata", uci_get("wifidog_v3." .. import_sec .. ".ua_summary") == "Pixel 8 / Android 14 / Chrome 125.0.0.0" and uci_get("wifidog_v3." .. import_sec .. ".ua_device_type") == "手机")
expect("import restores auth code", read_cmd("uci show wifidog_v3 | grep -c \"code='UTMBACKUP'\"") ~= "0")
expect("import restores auth code duration", read_cmd("uci show wifidog_v3 | grep -c \"auth_minutes='45'\"") ~= "0")

local fp = io.open("/www/wifidog_v3/cgi-bin/wifidog_v3/portal", "r")
local portal = fp and fp:read("*a") or ""
if fp then fp:close() end
expect("portal success polls api then uses ios close fallback", portal:find("pollCaptiveApi", 1, true) ~= nil and portal:find("captive.apple.com/hotspot-detect.html", 1, true) ~= nil and portal:find("window.close", 1, true) ~= nil and portal:find("window.location.replace", 1, true) == nil)
expect("portal has short ip session fallback", portal:find("IP_SESSION_FILE", 1, true) ~= nil and portal:find("resolve_client_device", 1, true) ~= nil)
expect("portal implements captive api and legacy probes", portal:find("application/captive+json", 1, true) ~= nil and portal:find("generate_204", 1, true) ~= nil and portal:find("Microsoft NCSI", 1, true) ~= nil)
expect("portal supports configurable themes and copy", portal:find("portal_theme_css", 1, true) ~= nil and portal:find("portal_prompt", 1, true) ~= nil and portal:find("portal_button_text", 1, true) ~= nil)
expect("portal supports per-code auth duration", portal:find("effective_auth_seconds", 1, true) ~= nil and portal:find("auth_minutes", 1, true) ~= nil)
expect("portal supports radius auth", portal:find("radius_authenticate", 1, true) ~= nil and portal:find("session_timeout", 1, true) ~= nil and portal:find("auth_method", 1, true) ~= nil)
expect("portal records and parses ua", portal:find("record_client_user_agent", 1, true) ~= nil and portal:find("parse_user_agent", 1, true) ~= nil and portal:find("ua_summary", 1, true) ~= nil)

local controller_file = read_cmd("cat /usr/lib/lua/luci/controller/wifidog_v3.lua")
expect("controller exposes runtime logs api", controller_file:find("action_runtime_logs", 1, true) ~= nil and controller_file:find("action_clear_runtime_logs", 1, true) ~= nil and controller_file:find("/var/log/wifidog_v3.log", 1, true) ~= nil)
expect("controller preserves ua metadata", controller_file:find("device_ua_options", 1, true) ~= nil and controller_file:find("enrich_device_payload", 1, true) ~= nil and controller_file:find("ua_summary", 1, true) ~= nil)

os.execute("uci -q set wifidog_v3.settings.portal_theme=warm")
os.execute("uci -q set wifidog_v3.settings.portal_title='UTM访客网络'")
os.execute("uci -q set wifidog_v3.settings.portal_prompt='请输入UTM授权码'")
os.execute("uci -q set wifidog_v3.settings.portal_button_text='UTM认证'")
os.execute("uci -q commit wifidog_v3")
local themed_portal = read_cmd("wget -q -O- http://127.0.0.1:8080/portal")
expect("portal renders configured theme and copy", themed_portal:find("UTM访客网络", 1, true) ~= nil and themed_portal:find("请输入UTM授权码", 1, true) ~= nil and themed_portal:find("UTM认证", 1, true) ~= nil and themed_portal:find("#fff7ed", 1, true) ~= nil)

local api_mac = "AA:BB:CC:DD:EE:41"
local api_sec = section(api_mac)
local api_expiry = tostring(os.time() + 3600)
os.execute("uci -q set wifidog_v3." .. api_sec .. "=device")
os.execute("uci -q set wifidog_v3." .. api_sec .. ".mac=" .. api_mac)
os.execute("uci -q set wifidog_v3." .. api_sec .. ".ip=192.168.77.41")
os.execute("uci -q set wifidog_v3." .. api_sec .. ".type=authorized")
os.execute("uci -q set wifidog_v3." .. api_sec .. ".auth_expiry=" .. api_expiry)
os.execute("uci -q commit wifidog_v3")
os.execute("printf '%s 192.168.77.41 %s\\n' '" .. tostring(os.time() + 600) .. "' '" .. api_mac .. "' >> /tmp/wifidog_v3_ip_sessions")
local fallback_api = read_cmd("REQUEST_METHOD=GET REQUEST_URI=/captive-portal/api REMOTE_ADDR=192.168.77.41 /www/wifidog_v3/cgi-bin/wifidog_v3/portal")
expect("short ip session api fallback reports not captive", fallback_api:find('"captive":false', 1, true) ~= nil, fallback_api)

if failed > 0 then
	print("UTM_SMOKE_FAILED " .. failed)
	os.exit(1)
end

print("UTM_SMOKE_OK")
