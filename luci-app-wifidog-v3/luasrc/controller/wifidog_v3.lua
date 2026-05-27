module("luci.controller.wifidog_v3", package.seeall)

local sys = require "luci.sys"
local http = require "luci.http"
local jsonc = require "luci.jsonc"
local LOG_FILE = "/var/log/wifidog_v3.log"

function index()
	if not nixio.fs.access("/etc/config/wifidog_v3") then
		return
	end

	local appname = "wifidog_v3"

	-- Top-level menu entry under Services
	entry({"admin", "services", appname}, alias("admin", "services", appname, "devices"), _("WiFiDog V3 认证系统"), 50).dependent = false

	-- Page 1: Device Scanning (网络设备扫描)
	entry({"admin", "services", appname, "devices"}, form(appname .. "/devices"), _("网络设备扫描"), 1)

	-- Page 2: Whitelist (白名单)
	entry({"admin", "services", appname, "whitelist"}, form(appname .. "/whitelist"), _("白名单管理"), 2)

	-- Page 3: Blacklist (黑名单)
	entry({"admin", "services", appname, "blacklist"}, form(appname .. "/blacklist"), _("黑名单管理"), 3)

	-- Page 4: Auth Code Management (授权码管理)
	entry({"admin", "services", appname, "auth_codes"}, form(appname .. "/auth_codes"), _("授权码管理"), 4)

	-- Page 5: Backup / Restore (配置备份)
	entry({"admin", "services", appname, "backup"}, form(appname .. "/backup"), _("配置备份"), 5)

	-- Page 6: Runtime logs (运行日志)
	entry({"admin", "services", appname, "logs"}, form(appname .. "/logs"), _("运行日志"), 6)

	-- Page 7: Settings (设置)
	entry({"admin", "services", appname, "settings"}, cbi(appname .. "/settings"), _("系统设置"), 7)

	-- AJAX endpoints for device management
	entry({"admin", "services", appname, "add_whitelist"}, call("action_add_whitelist")).leaf = true
	entry({"admin", "services", appname, "add_blacklist"}, call("action_add_blacklist")).leaf = true
	entry({"admin", "services", appname, "add_authorize"}, call("action_add_authorize")).leaf = true
	entry({"admin", "services", appname, "remove_device"}, call("action_remove_device")).leaf = true
	entry({"admin", "services", appname, "update_note"}, call("action_update_note")).leaf = true

	-- AJAX endpoints for auth code management
	entry({"admin", "services", appname, "generate_code"}, call("action_generate_code")).leaf = true
	entry({"admin", "services", appname, "delete_code"}, call("action_delete_code")).leaf = true

	-- AJAX endpoint for device scanning data
	entry({"admin", "services", appname, "scan_devices"}, call("action_scan_devices")).leaf = true

	-- AJAX endpoint for list data
	entry({"admin", "services", appname, "list_whitelist"}, call("action_list_whitelist")).leaf = true
	entry({"admin", "services", appname, "list_blacklist"}, call("action_list_blacklist")).leaf = true
	entry({"admin", "services", appname, "list_authorized"}, call("action_list_authorized")).leaf = true
	entry({"admin", "services", appname, "list_auth_codes"}, call("action_list_auth_codes")).leaf = true

	-- AJAX endpoints for backup / restore
	entry({"admin", "services", appname, "export_config"}, call("action_export_config")).leaf = true
	entry({"admin", "services", appname, "import_config"}, call("action_import_config")).leaf = true

	-- AJAX endpoints for runtime logs
	entry({"admin", "services", appname, "runtime_logs"}, call("action_runtime_logs")).leaf = true
	entry({"admin", "services", appname, "clear_runtime_logs"}, call("action_clear_runtime_logs")).leaf = true

	-- AJAX endpoint for service status
	entry({"admin", "services", appname, "status"}, call("action_status")).leaf = true

	-- Public portal page (no admin auth required)
	entry({"wifidog_v3", "portal"}, call("action_portal")).sysauth = false
end

-- ============================================================
-- Utility Functions
-- ============================================================

local function get_appname()
	return "wifidog_v3"
end

-- Get router LAN IP
local function get_router_ip()
	local ip = sys.exec("uci -q get network.lan.ipaddr 2>/dev/null")
	if ip and ip ~= "" then
		return ip:match("^%s*(.-)%s*$")
	end
	return "192.168.1.1"
end

-- Get LAN subnet
local function get_lan_subnet()
	local subnet = sys.exec("uci -q get wifidog_v3.settings.lan_subnet 2>/dev/null")
	if subnet and subnet ~= "" then
		return subnet:match("^%s*(.-)%s*$")
	end
	return "192.168.1.0/24"
end

-- Get portal port
local function get_portal_port()
	local port = sys.exec("uci -q get wifidog_v3.settings.portal_port 2>/dev/null")
	if port and port ~= "" then
		return port:match("^%s*(.-)%s*$")
	end
	return "8080"
end

local function trim(s)
	return tostring(s or ""):match("^%s*(.-)%s*$")
end

local function get_lan_ifaces()
	local ifaces = {}
	local lan_iface = trim(sys.exec("uci -q get wifidog_v3.settings.lan_interface 2>/dev/null"))
	if lan_iface == "" then
		lan_iface = trim(sys.exec("uci -q get network.lan.device 2>/dev/null"))
	end
	if lan_iface == "" then
		lan_iface = "br-lan"
	end

	ifaces[lan_iface] = true
	if lan_iface:match("^[%w%._:-]+$") then
		local ports = sys.exec("for p in /sys/class/net/" .. lan_iface .. "/brif/*; do [ -e \"$p\" ] && basename \"$p\"; done 2>/dev/null") or ""
		for port in ports:gmatch("%S+") do
			ifaces[port] = true
		end
	end

	return ifaces
end

-- Parse ARP table to get active devices
local function get_arp_devices()
	local devices = {}
	local lan_ifaces = get_lan_ifaces()
	local arp_file = io.open("/proc/net/arp", "r")
	if arp_file then
		arp_file:read("*l")
		for line in arp_file:lines() do
			local ip, hw_type, flags, mac, mask, dev = line:match("^(%S+)%s+(%S+)%s+(%S+)%s+(%S+)%s+(%S+)%s+(%S+)")
			if ip and mac and mac ~= "00:00:00:00:00:00" and (not dev or dev == "" or lan_ifaces[dev]) then
				devices[mac:upper()] = {
					ip = ip,
					mac = mac:upper(),
					hostname = "",
					device = dev or ""
				}
			end
		end
		arp_file:close()
	end

	-- DHCP leases are the most reliable source right after a phone joins Wi-Fi;
	-- the device may have a lease before it has generated an ARP entry.
	local lease_file = io.open("/tmp/dhcp.leases", "r")
	if lease_file then
		for line in lease_file:lines() do
			local ts, lease_mac, lease_ip, hostname, client_id = line:match("^(%d+)%s+(%S+)%s+(%S+)%s+(%S+)%s+(.*)")
			if lease_mac and lease_ip and lease_mac ~= "00:00:00:00:00:00" then
				local mac_upper = lease_mac:upper()
				if not devices[mac_upper] then
					devices[mac_upper] = {
						ip = lease_ip,
						mac = mac_upper,
						hostname = "",
						device = "dhcp"
					}
				else
					devices[mac_upper].ip = lease_ip
				end
				if hostname and hostname ~= "*" then
					devices[mac_upper].hostname = hostname
				end
			end
		end
		lease_file:close()
	end

	return devices
end

local function get_mac_for_ip(client_ip)
	if not client_ip or client_ip == "" then
		return ""
	end

	local arp_file = io.open("/proc/net/arp", "r")
	if arp_file then
		arp_file:read("*l")
		for line in arp_file:lines() do
			local ip, _, _, mac = line:match("^(%S+)%s+(%S+)%s+(%S+)%s+(%S+)")
			if ip == client_ip and mac and mac ~= "00:00:00:00:00:00" then
				arp_file:close()
				return mac:upper()
			end
		end
		arp_file:close()
	end

	local lease_file = io.open("/tmp/dhcp.leases", "r")
	if lease_file then
		for line in lease_file:lines() do
			local _, lease_mac, lease_ip = line:match("^(%d+)%s+(%S+)%s+(%S+)")
			if lease_ip == client_ip and lease_mac then
				lease_file:close()
				return lease_mac:upper()
			end
		end
		lease_file:close()
	end

	return ""
end

-- Get router's own MACs to exclude
local function get_router_macs()
	local macs = {}
	local interfaces = sys.exec("ls /sys/class/net/ 2>/dev/null")
	for iface in interfaces:gmatch("%S+") do
		local mac_file = io.open("/sys/class/net/" .. iface .. "/address", "r")
		if mac_file then
			local mac = mac_file:read("*l")
			mac_file:close()
			if mac then
				mac = mac:gsub("%s+", ""):upper()
				if mac ~= "" and mac ~= "00:00:00:00:00:00" then
					macs[mac] = true
				end
			end
		end
	end
	return macs
end

-- Convert MAC to UCI-safe section name (replace colons with underscores)
local function mac_to_section(mac)
	return mac:gsub(":", "_"):lower()
end

-- Check if device is already managed
local function find_device_by_mac(mac)
	local uci = require("luci.model.uci").cursor()
	local found_cfg = nil
	uci:foreach("wifidog_v3", "device", function(s)
		if s.mac and s.mac:upper() == mac:upper() then
			found_cfg = s
		end
	end)
	return found_cfg
end

local function delete_devices_by_mac(mac, uci)
	local deleted = false
	uci = uci or require("luci.model.uci").cursor()
	uci:foreach("wifidog_v3", "device", function(s)
		if s.mac and s.mac:upper() == mac:upper() then
			uci:delete("wifidog_v3", s[".name"])
			deleted = true
		end
	end)
	return deleted
end

-- Reload firewall rules
local function reload_firewall()
	sys.call("/etc/init.d/wifidog_v3 reload >/dev/null 2>&1 &")
end

-- Create uci cursor
local function get_uci()
	return require("luci.model.uci").cursor()
end

local function shell_quote(s)
	s = tostring(s or "")
	return "'" .. s:gsub("'", "'\\''") .. "'"
end

local function clean_log_message(message)
	message = tostring(message or ""):gsub("[\r\n]", " ")
	return message:sub(1, 512)
end

local function append_runtime_log(message)
	message = clean_log_message(message)
	if message == "" then
		return
	end
	sys.call("mkdir -p /var/log >/dev/null 2>&1")
	local fp = io.open(LOG_FILE, "a")
	if fp then
		fp:write(os.date("%Y-%m-%d %H:%M:%S"), " [admin] ", message, "\n")
		fp:close()
	end
	sys.call("logger -t wifidog_v3 " .. shell_quote(message) .. " >/dev/null 2>&1")
end

local function mask_secret(value)
	value = tostring(value or "")
	if #value <= 4 then
		return "****"
	end
	return value:sub(1, 4) .. string.rep("*", math.min(8, #value - 4))
end

local function uci_cli_set(expr)
	return sys.call("uci -q set " .. shell_quote(expr) .. " >/dev/null 2>&1") == 0
end

local function uci_cli_set_nonempty(path, value)
	value = tostring(value or "")
	if value == "" then
		return true
	end
	return uci_cli_set(path .. "=" .. value)
end

local function uci_cli_delete(path)
	return sys.call("uci -q delete " .. shell_quote(path) .. " >/dev/null 2>&1") == 0
end

local function uci_cli_commit(config)
	return sys.call("uci -q commit " .. shell_quote(config) .. " >/dev/null 2>&1") == 0
end

local function normalize_auth_minutes(value)
	value = tostring(value or ""):match("^%s*(.-)%s*$")
	if value == "" then
		return "", nil
	end
	if not value:match("^%d+$") then
		return nil, "授权后有效时长必须是正整数分钟"
	end
	local minutes = tonumber(value)
	if not minutes or minutes < 1 or minutes > 525600 then
		return nil, "授权后有效时长必须在 1 到 525600 分钟之间"
	end
	return tostring(minutes), nil
end

local function auth_code_exists(code)
	local target = tostring(code or ""):upper()
	local out = sys.exec("uci -q show wifidog_v3 2>/dev/null") or ""
	for line in out:gmatch("[^\n]+") do
		local value = line:match("^wifidog_v3%.[^%.=]+%.code='?(.-)'?$")
		if value then
			value = value:gsub("'$", "")
			if value:upper() == target then
				return true
			end
		end
	end
	return false
end

local function find_device_section_cli(mac)
	local target = tostring(mac or ""):upper()
	local out = sys.exec("uci -q show wifidog_v3 2>/dev/null") or ""
	local sections = {}
	for line in out:gmatch("[^\n]+") do
		local section, opt, value = line:match("^wifidog_v3%.([^%.=]+)%.([^=]+)='?(.-)'?$")
		if section and opt then
			value = value:gsub("'$", "")
			sections[section] = sections[section] or {}
			sections[section][opt] = value
		end
	end
	for section, values in pairs(sections) do
		if values.mac and values.mac:upper() == target then
			return section
		end
	end
	return nil
end

local function uci_sections_cli()
	local sections = {}
	local out = sys.exec("uci -q show wifidog_v3 2>/dev/null") or ""

	for line in out:gmatch("[^\n]+") do
		local section, opt, value = line:match("^wifidog_v3%.([^%.=]+)%.([^=]+)='?(.-)'?$")
		if section and opt then
			value = value:gsub("'$", "")
			sections[section] = sections[section] or { [".name"] = section }
			sections[section][opt] = value
		else
			local type_section, stype = line:match("^wifidog_v3%.([^=]+)='?(.-)'?$")
			if type_section and stype then
				stype = stype:gsub("'$", "")
				sections[type_section] = sections[type_section] or { [".name"] = type_section }
				sections[type_section][".type"] = stype
			end
		end
	end

	return sections
end

local function device_note_for_mac(mac)
	local target = tostring(mac or ""):upper()
	if target == "" then
		return ""
	end

	for _, s in pairs(uci_sections_cli()) do
		if s[".type"] == "device" and s.mac and s.mac:upper() == target then
			return s.note or ""
		end
	end

	return ""
end

local function note_for_transition(mac, posted_note)
	posted_note = tostring(posted_note or ""):sub(1, 256)
	if posted_note ~= "" then
		return posted_note
	end
	return device_note_for_mac(mac)
end

local function clean_import_value(value, max_len)
	if value == nil then
		return nil
	end
	if type(value) == "boolean" then
		value = value and "1" or "0"
	end
	local s = tostring(value)
	s = s:gsub("[%z\001-\008\011\012\014-\031\127]", " ")
	if max_len then
		s = s:sub(1, max_len)
	end
	return s
end

local function normalize_mac(mac)
	local compact = tostring(mac or ""):upper():gsub("[^0-9A-F]", "")
	if #compact ~= 12 then
		return nil
	end
	return compact:gsub("(%x%x)(%x%x)(%x%x)(%x%x)(%x%x)(%x%x)", "%1:%2:%3:%4:%5:%6")
end

local function delete_devices_by_mac_cli(mac)
	local target = tostring(mac or ""):upper()
	local deleted = false
	if target == "" then
		return false
	end

	for section, s in pairs(uci_sections_cli()) do
		if s[".type"] == "device" and s.mac and s.mac:upper() == target then
			if uci_cli_delete("wifidog_v3." .. section) then
				deleted = true
			end
		end
	end

	return deleted
end

local function move_device_to_pending_cli(mac)
	local target = normalize_mac(mac)
	if not target then
		return false
	end

	local saved = {
		mac = target,
		ip = "",
		hostname = "",
		note = "",
		created = tostring(os.time())
	}
	local found = false

	for section, s in pairs(uci_sections_cli()) do
		if s[".type"] == "device" and s.mac and normalize_mac(s.mac) == target then
			found = true
			if saved.ip == "" then saved.ip = s.ip or "" end
			if saved.hostname == "" then saved.hostname = s.hostname or "" end
			if saved.note == "" then saved.note = s.note or "" end
			if s.created and s.created ~= "" then saved.created = s.created end
			uci_cli_delete("wifidog_v3." .. section)
		end
	end

	if not found then
		return false
	end

	local section = mac_to_section(target)
	return uci_cli_set("wifidog_v3." .. section .. "=device")
		and uci_cli_set("wifidog_v3." .. section .. ".mac=" .. target)
		and uci_cli_set("wifidog_v3." .. section .. ".ip=" .. clean_import_value(saved.ip, 64))
		and uci_cli_set("wifidog_v3." .. section .. ".hostname=" .. clean_import_value(saved.hostname, 128))
		and uci_cli_set("wifidog_v3." .. section .. ".note=" .. clean_import_value(saved.note, 256))
		and uci_cli_set("wifidog_v3." .. section .. ".type=pending")
		and uci_cli_set("wifidog_v3." .. section .. ".auth_expiry=0")
		and uci_cli_set("wifidog_v3." .. section .. ".created=" .. clean_import_value(saved.created, 32))
end

local settings_keys = {
	"enabled",
	"wan_interface",
	"lan_interface",
	"portal_port",
	"lan_subnet",
	"auth_code_enabled",
	"auth_timeout",
	"radius_enabled",
	"radius_server",
	"radius_port",
	"radius_secret",
	"radius_nas_id",
	"radius_timeout",
	"radius_retries",
	"auto_detect_wan",
	"portal_theme",
	"portal_title",
	"portal_prompt",
	"portal_hint",
	"portal_button_text",
	"portal_code_label",
	"portal_code_placeholder"
}

local settings_defaults = {
	enabled = "0",
	wan_interface = "",
	lan_interface = "",
	portal_port = "8080",
	lan_subnet = "",
	auth_code_enabled = "1",
	auth_timeout = "1440",
	radius_enabled = "0",
	radius_server = "",
	radius_port = "1812",
	radius_secret = "",
	radius_nas_id = "wifidog-v3",
	radius_timeout = "3",
	radius_retries = "1",
	auto_detect_wan = "1",
	portal_theme = "classic",
	portal_title = "网络认证",
	portal_prompt = "请输入授权码以访问互联网",
	portal_hint = "如需获取授权码，请联系网络管理员。认证成功后会自动确认网络状态并尝试关闭认证窗口。",
	portal_button_text = "认证上网",
	portal_code_label = "授权码",
	portal_code_placeholder = "请输入授权码"
}

local settings_key_allowed = {}
for _, key in ipairs(settings_keys) do
	settings_key_allowed[key] = true
end

local settings_value_maxlen = {
	portal_title = 80,
	portal_prompt = 256,
	portal_hint = 512,
	portal_button_text = 40,
	portal_code_label = 40,
	portal_code_placeholder = 80,
	radius_server = 128,
	radius_secret = 128,
	radius_nas_id = 80
}

local device_types_allowed = {
	pending = true,
	whitelist = true,
	blacklist = true,
	authorized = true
}

local function section_options(s)
	local out = {}
	for k, v in pairs(s or {}) do
		if type(k) == "string" and k:sub(1, 1) ~= "." then
			out[k] = tostring(v or "")
		end
	end
	return out
end

local function backup_payload()
	local payload = {
		app = "wifidog_v3",
		format_version = 1,
		exported_at = os.date("%Y-%m-%d %H:%M:%S"),
		exported_unix = os.time(),
		settings = {},
		devices = {},
		auth_codes = {}
	}

	for _, s in pairs(uci_sections_cli()) do
		if s[".name"] == "settings" and s[".type"] == "wifidog_v3" then
			for _, key in ipairs(settings_keys) do
				if s[key] ~= nil then
					payload.settings[key] = tostring(s[key] or "")
				end
			end
		elseif s[".type"] == "device" then
			local dev = section_options(s)
			if dev.mac and dev.mac ~= "" then
				dev.mac = normalize_mac(dev.mac) or dev.mac:upper()
			end
			payload.devices[#payload.devices + 1] = dev
		elseif s[".type"] == "authcode" then
			payload.auth_codes[#payload.auth_codes + 1] = section_options(s)
		end
	end

	table.sort(payload.devices, function(a, b) return tostring(a.mac or "") < tostring(b.mac or "") end)
	table.sort(payload.auth_codes, function(a, b) return tostring(a.code or "") < tostring(b.code or "") end)
	return payload
end

local function normalize_backup_payload(payload)
	if type(payload) ~= "table" then
		return nil, "备份内容格式不正确"
	end
	if payload.app and payload.app ~= "wifidog_v3" then
		return nil, "备份文件不是 WiFiDog V3 配置"
	end

	local normalized = {
		settings = {},
		devices = {},
		auth_codes = {}
	}

	if payload.settings ~= nil and type(payload.settings) ~= "table" then
		return nil, "系统设置格式不正确"
	end
	for key, value in pairs(payload.settings or {}) do
		if settings_key_allowed[key] then
			normalized.settings[key] = clean_import_value(value, settings_value_maxlen[key] or 128)
		end
	end
	for _, key in ipairs(settings_keys) do
		if normalized.settings[key] == nil then
			normalized.settings[key] = settings_defaults[key] or ""
		end
	end

	if payload.devices ~= nil and type(payload.devices) ~= "table" then
		return nil, "设备列表格式不正确"
	end
	for _, dev in ipairs(payload.devices or {}) do
		if type(dev) ~= "table" then
			return nil, "设备列表中存在无效条目"
		end
		local mac = normalize_mac(dev.mac)
		if not mac then
			return nil, "设备列表中存在无效 MAC 地址"
		end
		local dev_type = clean_import_value(dev.type, 32) or "pending"
		if not device_types_allowed[dev_type] then
			return nil, "设备 " .. mac .. " 的名单类型无效"
		end
		normalized.devices[#normalized.devices + 1] = {
			mac = mac,
			ip = clean_import_value(dev.ip, 64) or "",
			hostname = clean_import_value(dev.hostname, 128) or "",
			note = clean_import_value(dev.note, 256) or "",
			type = dev_type,
			auth_expiry = clean_import_value(dev.auth_expiry, 32) or "0",
			auth_source = clean_import_value(dev.auth_source, 32) or "",
			auth_code = clean_import_value(dev.auth_code, 128) or "",
			radius_user = clean_import_value(dev.radius_user, 128) or "",
			created = clean_import_value(dev.created, 32) or tostring(os.time())
		}
	end

	if payload.auth_codes ~= nil and type(payload.auth_codes) ~= "table" then
		return nil, "授权码列表格式不正确"
	end
	for _, code in ipairs(payload.auth_codes or {}) do
		if type(code) ~= "table" then
			return nil, "授权码列表中存在无效条目"
		end
		local value = clean_import_value(code.code, 128)
		if not value or value == "" then
			return nil, "授权码不能为空"
		end
		local auth_minutes, auth_minutes_err = normalize_auth_minutes(clean_import_value(code.auth_minutes, 16) or "")
		if not auth_minutes then
			return nil, "授权码 " .. value:upper() .. " 的" .. (auth_minutes_err or "授权后有效时长无效")
		end
		normalized.auth_codes[#normalized.auth_codes + 1] = {
			code = value:upper(),
			max_uses = clean_import_value(code.max_uses, 16) or "1",
			used_count = clean_import_value(code.used_count, 16) or "0",
			expiry_days = clean_import_value(code.expiry_days, 16) or "30",
			created_date = clean_import_value(code.created_date, 16) or os.date("%Y-%m-%d"),
			enabled = clean_import_value(code.enabled, 8) or "1",
			auth_minutes = auth_minutes
		}
	end

	return normalized
end

local function apply_runtime_after_config()
	local enabled = trim(sys.exec("uci -q get wifidog_v3.settings.enabled 2>/dev/null"))
	if enabled == "1" then
		sys.call("/etc/init.d/wifidog_v3 restart >/dev/null 2>&1")
	else
		sys.call("/etc/init.d/wifidog_v3 stop >/dev/null 2>&1")
	end
end

local function restore_backup_payload(payload)
	local ok, err = pcall(function()
		local function must(result, message)
			if not result then
				error(message or "uci operation failed")
			end
		end
		local function set_nonempty(section, option, value)
			value = tostring(value or "")
			if value ~= "" then
				must(uci_cli_set("wifidog_v3." .. section .. "." .. option .. "=" .. value), "failed to set " .. section .. "." .. option)
			end
		end
		local function set_required(section, option, value)
			must(uci_cli_set("wifidog_v3." .. section .. "." .. option .. "=" .. tostring(value or "")), "failed to set " .. section .. "." .. option)
		end
		local function create_section(section, stype)
			must(uci_cli_set("wifidog_v3." .. section .. "=" .. stype), "failed to create section " .. section)
		end

		sys.call("uci -q revert wifidog_v3 >/dev/null 2>&1")
		for section, s in pairs(uci_sections_cli()) do
			if s[".name"] == "settings" or s[".type"] == "device" or s[".type"] == "authcode" then
				uci_cli_delete("wifidog_v3." .. section)
			end
		end

		create_section("settings", "wifidog_v3")
		for _, key in ipairs(settings_keys) do
			if payload.settings[key] ~= nil then
				set_nonempty("settings", key, payload.settings[key])
			end
		end

		for _, dev in ipairs(payload.devices) do
			local section = mac_to_section(dev.mac)
			create_section(section, "device")
			set_required(section, "mac", dev.mac)
			set_nonempty(section, "ip", dev.ip)
			set_nonempty(section, "hostname", dev.hostname)
			set_nonempty(section, "note", dev.note)
			set_required(section, "type", dev.type)
			set_required(section, "auth_expiry", dev.auth_expiry)
			set_nonempty(section, "auth_source", dev.auth_source)
			set_nonempty(section, "auth_code", dev.auth_code)
			set_nonempty(section, "radius_user", dev.radius_user)
			set_nonempty(section, "created", dev.created)
		end

		for idx, code in ipairs(payload.auth_codes) do
			local safe_code = code.code:gsub("[^%w_]", "_"):sub(1, 32)
			local section = string.format("auth_%s_%02d", safe_code, idx)
			create_section(section, "authcode")
			set_required(section, "code", code.code)
			set_required(section, "max_uses", code.max_uses)
			set_required(section, "used_count", code.used_count)
			set_required(section, "expiry_days", code.expiry_days)
			set_required(section, "created_date", code.created_date)
			set_required(section, "enabled", code.enabled)
			set_nonempty(section, "auth_minutes", code.auth_minutes)
		end

		if not uci_cli_commit("wifidog_v3") then
			error("uci commit failed")
		end
	end)

	if ok then
		apply_runtime_after_config()
		return true
	end

	sys.call("logger -t wifidog_v3 " .. shell_quote("restore failed: " .. tostring(err)))
	sys.call("uci -q revert wifidog_v3 >/dev/null 2>&1")
	return false, err
end

local function auth_remaining(auth_expiry)
	local expiry = tonumber(auth_expiry or "0") or 0
	local remaining = expiry - os.time()
	if remaining < 0 then remaining = 0 end
	local hours = math.floor(remaining / 3600)
	local minutes = math.floor((remaining % 3600) / 60)
	return remaining, string.format("%d小时%d分钟", hours, minutes)
end

local function auth_source_text(source)
	if source == "manual" then
		return "管理页面手动授权"
	elseif source == "code" then
		return "授权码自助授权"
	elseif source == "radius" then
		return "RADIUS账号认证"
	end
	return "未知"
end

-- ============================================================
-- AJAX Action Handlers
-- ============================================================

-- Add device to whitelist
function action_add_whitelist()
	local mac = http.formvalue("mac")
	local ip = http.formvalue("ip")
	local hostname = http.formvalue("hostname") or ""
	local note = http.formvalue("note") or ""

	if not mac or mac == "" then
		http.prepare_content("application/json")
		http.write_json({ success = false, message = "MAC地址不能为空" })
		return
	end

	mac = mac:upper()
	note = note_for_transition(mac, note)

	delete_devices_by_mac_cli(mac)

	-- Add new whitelist entry
	local section = mac_to_section(mac)
	local ok = uci_cli_set("wifidog_v3." .. section .. "=device")
		and uci_cli_set("wifidog_v3." .. section .. ".mac=" .. mac)
		and uci_cli_set("wifidog_v3." .. section .. ".ip=" .. (ip or ""))
		and uci_cli_set("wifidog_v3." .. section .. ".hostname=" .. hostname)
		and uci_cli_set("wifidog_v3." .. section .. ".note=" .. note)
		and uci_cli_set("wifidog_v3." .. section .. ".type=whitelist")
		and uci_cli_set("wifidog_v3." .. section .. ".auth_expiry=0")
		and uci_cli_set("wifidog_v3." .. section .. ".created=" .. tostring(os.time()))
		and uci_cli_commit("wifidog_v3")

	if ok then
		append_runtime_log("设备已加入白名单 MAC=" .. mac .. " IP=" .. tostring(ip or ""))
		reload_firewall()
	end

	http.prepare_content("application/json")
	http.write_json({ success = ok, message = ok and "已添加到白名单" or "添加白名单失败" })
end

-- Add device to blacklist
function action_add_blacklist()
	local mac = http.formvalue("mac")
	local ip = http.formvalue("ip")
	local hostname = http.formvalue("hostname") or ""
	local note = http.formvalue("note") or ""

	if not mac or mac == "" then
		http.prepare_content("application/json")
		http.write_json({ success = false, message = "MAC地址不能为空" })
		return
	end

	mac = mac:upper()
	note = note_for_transition(mac, note)

	delete_devices_by_mac_cli(mac)

	local section = mac_to_section(mac)
	local ok = uci_cli_set("wifidog_v3." .. section .. "=device")
		and uci_cli_set("wifidog_v3." .. section .. ".mac=" .. mac)
		and uci_cli_set("wifidog_v3." .. section .. ".ip=" .. (ip or ""))
		and uci_cli_set("wifidog_v3." .. section .. ".hostname=" .. hostname)
		and uci_cli_set("wifidog_v3." .. section .. ".note=" .. note)
		and uci_cli_set("wifidog_v3." .. section .. ".type=blacklist")
		and uci_cli_set("wifidog_v3." .. section .. ".auth_expiry=0")
		and uci_cli_set("wifidog_v3." .. section .. ".created=" .. tostring(os.time()))
		and uci_cli_commit("wifidog_v3")

	if ok then
		append_runtime_log("设备已加入黑名单 MAC=" .. mac .. " IP=" .. tostring(ip or ""))
		reload_firewall()
	end

	http.prepare_content("application/json")
	http.write_json({ success = ok, message = ok and "已添加到黑名单" or "添加黑名单失败" })
end

-- Authorize device (24 hours)
function action_add_authorize()
	local mac = http.formvalue("mac")
	local ip = http.formvalue("ip")
	local hostname = http.formvalue("hostname") or ""
	local note = http.formvalue("note") or ""

	if not mac or mac == "" then
		http.prepare_content("application/json")
		http.write_json({ success = false, message = "MAC地址不能为空" })
		return
	end

	mac = mac:upper()
	note = note_for_transition(mac, note)

	local auth_timeout = tonumber(sys.exec("uci -q get wifidog_v3.settings.auth_timeout 2>/dev/null") or "1440")
	local expiry = os.time() + (auth_timeout * 60)

	delete_devices_by_mac_cli(mac)

	local section = mac_to_section(mac)
	local ok = uci_cli_set("wifidog_v3." .. section .. "=device")
		and uci_cli_set("wifidog_v3." .. section .. ".mac=" .. mac)
		and uci_cli_set("wifidog_v3." .. section .. ".ip=" .. (ip or ""))
		and uci_cli_set("wifidog_v3." .. section .. ".hostname=" .. hostname)
		and uci_cli_set("wifidog_v3." .. section .. ".note=" .. note)
		and uci_cli_set("wifidog_v3." .. section .. ".type=authorized")
		and uci_cli_set("wifidog_v3." .. section .. ".auth_expiry=" .. tostring(expiry))
		and uci_cli_set("wifidog_v3." .. section .. ".auth_source=manual")
		and uci_cli_set("wifidog_v3." .. section .. ".auth_code=")
		and uci_cli_set("wifidog_v3." .. section .. ".created=" .. tostring(os.time()))
		and uci_cli_commit("wifidog_v3")

	if ok then
		append_runtime_log("管理员手动授权设备 MAC=" .. mac .. " IP=" .. tostring(ip or "") .. " 到期=" .. os.date("%Y-%m-%d %H:%M:%S", expiry))
		reload_firewall()
	end

	http.prepare_content("application/json")
	http.write_json({ success = ok, message = ok and string.format("已授权，有效期至 %s", os.date("%Y-%m-%d %H:%M:%S", expiry)) or "授权失败" })
end

function action_update_note()
	local mac = http.formvalue("mac")
	local ip = http.formvalue("ip") or ""
	local hostname = http.formvalue("hostname") or ""
	local note = http.formvalue("note") or ""

	if not mac or mac == "" then
		http.prepare_content("application/json")
		http.write_json({ success = false, message = "MAC地址不能为空" })
		return
	end

	mac = mac:upper()
	note = note:sub(1, 256)
	local section = find_device_section_cli(mac)
	local ok = false
	if not section then
		if ip == "" and hostname == "" then
			http.prepare_content("application/json")
			http.write_json({ success = false, message = "未找到设备" })
			return
		end

		section = mac_to_section(mac)
		ok = uci_cli_set("wifidog_v3." .. section .. "=device")
			and uci_cli_set("wifidog_v3." .. section .. ".mac=" .. mac)
			and uci_cli_set("wifidog_v3." .. section .. ".ip=" .. ip)
			and uci_cli_set("wifidog_v3." .. section .. ".hostname=" .. hostname)
			and uci_cli_set("wifidog_v3." .. section .. ".note=" .. note)
			and uci_cli_set("wifidog_v3." .. section .. ".type=pending")
			and uci_cli_set("wifidog_v3." .. section .. ".auth_expiry=0")
			and uci_cli_set("wifidog_v3." .. section .. ".created=" .. tostring(os.time()))
	else
		ok = uci_cli_set("wifidog_v3." .. section .. ".note=" .. note)
		if ip ~= "" then
			ok = ok and uci_cli_set("wifidog_v3." .. section .. ".ip=" .. ip)
		end
		if hostname ~= "" then
			ok = ok and uci_cli_set("wifidog_v3." .. section .. ".hostname=" .. hostname)
		end
	end

	ok = ok and uci_cli_commit("wifidog_v3")
	if ok then
		append_runtime_log("设备备注已更新 MAC=" .. mac)
	end
	http.prepare_content("application/json")
	http.write_json({ success = ok, message = ok and "备注已保存" or "备注保存失败" })
end

-- Remove device from any list
function action_remove_device()
	local mac = http.formvalue("mac")

	if not mac or mac == "" then
		http.prepare_content("application/json")
		http.write_json({ success = false, message = "MAC地址不能为空" })
		return
	end

	mac = mac:upper()

	local ok = move_device_to_pending_cli(mac)
	if ok then
		uci_cli_commit("wifidog_v3")
		append_runtime_log("设备已移回待授权 MAC=" .. mac)
		reload_firewall()
	end

	http.prepare_content("application/json")
	http.write_json({ success = ok, message = ok and "已移回待授权，备注已保留" or "未找到设备" })
end

-- Scan network devices
function action_scan_devices()
	local arp_devices = get_arp_devices()
	local router_macs = get_router_macs()
	local managed = {}
	local pending = {}

	-- Get all managed devices
	for _, s in pairs(uci_sections_cli()) do
		if s[".type"] == "device" and s.mac then
			local mac = s.mac:upper()
			if s.type == "pending" then
				pending[mac] = s
			else
				local expired_auth = (s.type == "authorized" and (tonumber(s.auth_expiry) or 0) <= os.time())
				if not expired_auth then
					managed[mac] = s
				end
			end
		end
	end

	local devices = {}
	for mac, info in pairs(arp_devices) do
		-- Skip router's own MACs
		if not router_macs[mac] then
			-- Only show unmanaged devices (pending)
			if not managed[mac] then
				local saved = pending[mac] or {}
				devices[#devices + 1] = {
					mac = mac,
					ip = info.ip,
					hostname = (info.hostname and info.hostname ~= "" and info.hostname) or saved.hostname or "",
					note = saved.note or ""
				}
			end
		end
	end

	-- Sort by IP
	table.sort(devices, function(a, b)
		return a.ip < b.ip
	end)

	http.prepare_content("application/json")
	if #devices > 0 then
	http.write_json({ success = true, devices = devices })
	else
		http.write('{"success":true,"devices":[]}')
	end
end

-- List whitelist devices
function action_list_whitelist()
	local devices = {}
	for _, s in pairs(uci_sections_cli()) do
		if s[".type"] == "device" and s.type == "whitelist" then
			devices[#devices + 1] = {
				mac = s.mac or "",
				ip = s.ip or "",
				hostname = s.hostname or "",
				note = s.note or "",
				created = s.created or "0"
			}
		end
	end

	table.sort(devices, function(a, b) return a.ip < b.ip end)

	http.prepare_content("application/json")
	if #devices > 0 then
	http.write_json({ success = true, devices = devices })
	else
		http.write('{"success":true,"devices":[]}')
	end
end

-- List blacklist devices
function action_list_blacklist()
	local devices = {}
	for _, s in pairs(uci_sections_cli()) do
		if s[".type"] == "device" and s.type == "blacklist" then
			devices[#devices + 1] = {
				mac = s.mac or "",
				ip = s.ip or "",
				hostname = s.hostname or "",
				note = s.note or "",
				created = s.created or "0"
			}
		end
	end

	table.sort(devices, function(a, b) return a.ip < b.ip end)

	http.prepare_content("application/json")
	if #devices > 0 then
	http.write_json({ success = true, devices = devices })
	else
		http.write('{"success":true,"devices":[]}')
	end
end

function action_list_authorized()
	local devices = {}
	for _, s in pairs(uci_sections_cli()) do
		if s[".type"] == "device" and s.type == "authorized" then
			local remaining, remaining_text = auth_remaining(s.auth_expiry)
			if remaining > 0 then
				devices[#devices + 1] = {
					mac = s.mac or "",
					ip = s.ip or "",
					hostname = s.hostname or "",
					note = s.note or "",
					created = s.created or "0",
					auth_expiry = s.auth_expiry or "0",
					remaining = remaining,
					remaining_text = remaining_text,
					auth_source = s.auth_source or "",
					auth_source_text = auth_source_text(s.auth_source),
					auth_code = s.auth_code or "",
					radius_user = s.radius_user or ""
				}
			end
		end
	end

	table.sort(devices, function(a, b) return a.ip < b.ip end)

	http.prepare_content("application/json")
	if #devices > 0 then
		http.write_json({ success = true, devices = devices })
	else
		http.write('{"success":true,"devices":[]}')
	end
end

-- List auth codes
function action_list_auth_codes()
	local codes = {}
	for _, s in pairs(uci_sections_cli()) do
		if s[".type"] == "authcode" then
		codes[#codes + 1] = {
			code = s.code or "",
			max_uses = s.max_uses or "0",
			used_count = s.used_count or "0",
			expiry_days = s.expiry_days or "0",
			auth_minutes = s.auth_minutes or "",
			created_date = s.created_date or "",
			enabled = s.enabled or "0"
		}
		end
	end

	http.prepare_content("application/json")
	if #codes > 0 then
	http.write_json({ success = true, codes = codes })
	else
		http.write('{"success":true,"codes":[]}')
	end
end

-- Generate auth code
function action_generate_code()
	local code = http.formvalue("code")
	local max_uses = http.formvalue("max_uses") or "1"
	local expiry_days = http.formvalue("expiry_days") or "30"
	local auth_minutes = http.formvalue("auth_minutes") or ""

	code = code and code:match("^%s*(.-)%s*$") or ""
	max_uses = tostring(tonumber(max_uses) or 1)
	expiry_days = tostring(tonumber(expiry_days) or 30)
	local auth_minutes_err
	auth_minutes, auth_minutes_err = normalize_auth_minutes(auth_minutes)

	if not code or code == "" then
		http.prepare_content("application/json")
		http.write_json({ success = false, message = "授权码不能为空" })
		return
	end
	if not auth_minutes then
		http.prepare_content("application/json")
		http.write_json({ success = false, message = auth_minutes_err or "授权后有效时长无效" })
		return
	end

	if auth_code_exists(code) then
		http.prepare_content("application/json")
		http.write_json({ success = false, message = "授权码已存在" })
		return
	end

	local safe_code = code:upper():gsub("[^%w_]", "_"):sub(1, 32)
	local section = string.format("auth_%s_%d", safe_code, os.time())
	for i = 1, 99 do
		if sys.call("uci -q get " .. shell_quote("wifidog_v3." .. section) .. " >/dev/null 2>&1") ~= 0 then
			break
		end
		section = string.format("auth_%s_%d_%02d", safe_code, os.time(), i)
	end
	local ok = uci_cli_set("wifidog_v3." .. section .. "=authcode")
		and uci_cli_set("wifidog_v3." .. section .. ".code=" .. code:upper():sub(1, 128))
		and uci_cli_set("wifidog_v3." .. section .. ".max_uses=" .. max_uses)
		and uci_cli_set("wifidog_v3." .. section .. ".used_count=0")
		and uci_cli_set("wifidog_v3." .. section .. ".expiry_days=" .. expiry_days)
		and uci_cli_set_nonempty("wifidog_v3." .. section .. ".auth_minutes", auth_minutes)
		and uci_cli_set("wifidog_v3." .. section .. ".created_date=" .. os.date("%Y-%m-%d"))
		and uci_cli_set("wifidog_v3." .. section .. ".enabled=1")
	local committed = ok and uci_cli_commit("wifidog_v3")
	if not committed then
		uci_cli_delete("wifidog_v3." .. section)
		uci_cli_commit("wifidog_v3")
		http.prepare_content("application/json")
		http.write_json({ success = false, message = "授权码保存失败，请检查 /etc/config/wifidog_v3 是否可写" })
		return
	end

	append_runtime_log("授权码已生成 CODE=" .. mask_secret(code:upper()) .. " 次数=" .. max_uses .. " 有效期天数=" .. expiry_days .. " 授权分钟=" .. (auth_minutes ~= "" and auth_minutes or "默认"))
	http.prepare_content("application/json")
	http.write_json({ success = true, message = "授权码已生成" })
end

-- Delete auth code
function action_delete_code()
	local code = http.formvalue("code")

	if not code or code == "" then
		http.prepare_content("application/json")
		http.write_json({ success = false, message = "授权码不能为空" })
		return
	end

	local uci = get_uci()
	uci:foreach("wifidog_v3", "authcode", function(s)
		if s.code and s.code:upper() == code:upper() then
			uci:delete("wifidog_v3", s[".name"])
		end
	end)
	uci:commit("wifidog_v3")
	append_runtime_log("授权码已删除 CODE=" .. mask_secret(code:upper()))

	http.prepare_content("application/json")
	http.write_json({ success = true, message = "授权码已删除" })
end

function action_export_config()
	local content = jsonc.stringify(backup_payload()) or "{}"
	local filename = "wifidog-v3-backup-" .. os.date("%Y%m%d-%H%M%S") .. ".json"

	http.header("Content-Disposition", "attachment; filename=" .. filename)
	http.header("X-Backup-Filename", filename)
	http.prepare_content("application/json; charset=utf-8")
	http.write(content)
end

function action_import_config()
	local raw = http.formvalue("config_json") or http.formvalue("config") or ""
	raw = tostring(raw or "")

	http.prepare_content("application/json")
	if raw == "" then
		http.write_json({ success = false, message = "请先选择或粘贴备份文件内容" })
		return
	end
	if #raw > 512 * 1024 then
		http.write_json({ success = false, message = "备份文件过大" })
		return
	end

	local ok, parsed = pcall(jsonc.parse, raw)
	if not ok or type(parsed) ~= "table" then
		http.write_json({ success = false, message = "备份 JSON 解析失败" })
		return
	end

	local normalized, err = normalize_backup_payload(parsed)
	if not normalized then
		http.write_json({ success = false, message = err or "备份内容无效" })
		return
	end

	local restored, restore_err = restore_backup_payload(normalized)
	if restored then
		append_runtime_log(string.format("配置已恢复：设备 %d 个，授权码 %d 个", #normalized.devices, #normalized.auth_codes))
		http.write_json({
			success = true,
			message = string.format(
				"配置已恢复：设备 %d 个，授权码 %d 个",
				#normalized.devices,
				#normalized.auth_codes
			)
		})
	else
		local message = "配置恢复失败，已回滚未提交的修改"
		if restore_err and tostring(restore_err) ~= "" then
			message = message .. "：" .. tostring(restore_err)
		end
		http.write_json({ success = false, message = message })
	end
end

-- Service status
local function get_runtime_status()
	local nft_ok = (sys.call("nft list table inet wifidog_v3 >/dev/null 2>&1") == 0)
	local portal_ok = (sys.call([[pid="$(cat /var/run/wifidog_v3_portal.pid 2>/dev/null)"; [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null && ps w 2>/dev/null | awk -v p="$pid" '$1 == p && /[u]httpd/ && /\/www\/wifidog_v3/ { found=1 } END { exit found ? 0 : 1 }']]) == 0)
	return nft_ok, portal_ok
end

function action_status()
	local enabled = sys.exec("uci -q get wifidog_v3.settings.enabled 2>/dev/null"):match("^(%d)")
	local nft_ok = false
	local portal_ok = false

	if enabled == "1" then
		nft_ok, portal_ok = get_runtime_status()
		if not (nft_ok and portal_ok) then
			sys.call("/etc/init.d/wifidog_v3 reload >/dev/null 2>&1")
			nft_ok, portal_ok = get_runtime_status()
		end
	else
		nft_ok, portal_ok = get_runtime_status()
		if nft_ok or portal_ok then
			sys.call("/etc/init.d/wifidog_v3 stop >/dev/null 2>&1")
		end
		nft_ok, portal_ok = get_runtime_status()
	end

	http.prepare_content("application/json")
	http.write_json({ running = (nft_ok and portal_ok), nft = nft_ok, portal = portal_ok, enabled = (enabled == "1") })
end

local function parse_log_lines(text, source, limit, query, out)
	local lowered_query = query ~= "" and query:lower() or ""
	for line in tostring(text or ""):gmatch("[^\r\n]+") do
		if lowered_query == "" or line:lower():find(lowered_query, 1, true) then
			out[#out + 1] = { source = source, line = line }
		end
	end
	while #out > limit do
		table.remove(out, 1)
	end
end

local function runtime_log_stat()
	local size = tonumber(trim(sys.exec("wc -c < " .. shell_quote(LOG_FILE) .. " 2>/dev/null"))) or 0
	return { path = LOG_FILE, size = size }
end

function action_runtime_logs()
	local source = http.formvalue("source") or "app"
	local query = trim(http.formvalue("query") or ""):sub(1, 80)
	local limit = tonumber(http.formvalue("lines") or "200") or 200
	if limit < 50 then
		limit = 50
	elseif limit > 1000 then
		limit = 1000
	end

	local logs = {}
	if source == "app" or source == "all" then
		local app_logs = sys.exec("tail -n " .. tostring(limit) .. " " .. shell_quote(LOG_FILE) .. " 2>/dev/null") or ""
		parse_log_lines(app_logs, "app", limit, query, logs)
	end
	if source == "syslog" or source == "all" then
		local sys_logs = sys.exec("logread 2>/dev/null | grep -E 'wifidog_v3|wifidog-v3|/www/wifidog_v3' | tail -n " .. tostring(limit)) or ""
		parse_log_lines(sys_logs, "syslog", limit, query, logs)
	end

	http.prepare_content("application/json")
	http.write_json({ success = true, lines = logs, stat = runtime_log_stat(), source = source, query = query })
end

function action_clear_runtime_logs()
	sys.call("mkdir -p /var/log >/dev/null 2>&1")
	local ok = false
	local fp = io.open(LOG_FILE, "w")
	if fp then
		ok = true
		fp:close()
	end
	if ok then
		append_runtime_log("运行日志已由管理后台清空")
	end
	http.prepare_content("application/json")
	http.write_json({ success = ok, message = ok and "运行日志已清空" or "运行日志清空失败" })
end

-- ============================================================
-- Captive Portal Handler
-- ============================================================

function action_portal()
	local client_ip = http.getenv("REMOTE_ADDR") or ""
	local client_mac = get_mac_for_ip(client_ip)
	local redirect_url = http.formvalue("redirect_url") or http.formvalue("url") or ""
	local auth_code = http.formvalue("auth_code") or ""
	local action = http.formvalue("action") or ""

	if action == "auth" and auth_code ~= "" then
		-- Validate auth code
		local valid, message, used_code, auth_minutes = validate_auth_code(auth_code, client_mac)
		if valid then
			-- Authorize the device
			authorize_client(client_mac, client_ip, used_code, auth_minutes)
			reload_firewall()

			http.prepare_content("text/html; charset=utf-8")
			http.write([[
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>认证成功</title></head>
<body>
<h2>认证成功！</h2>
<p>您现在可以正常访问网络了，本页面将在 3 秒后尝试自动关闭。</p>
<script>setTimeout(function(){ try { window.open('', '_self'); window.close(); } catch (e) {} }, 3000);</script>
</body>
</html>
			]])
			return
		else
			-- Show error
			http.prepare_content("text/html; charset=utf-8")
			http.write(render_portal_page(redirect_url, message))
			return
		end
	end

	-- Show portal page
	http.prepare_content("text/html; charset=utf-8")
	http.write(render_portal_page(redirect_url, nil))
end

function render_portal_page(redirect_url, error_msg)
	local router_ip = get_router_ip()
	local error_html = ""
	if error_msg then
		error_html = '<div style="color:red;margin:10px 0;padding:10px;background:#ffe0e0;border-radius:4px;">' .. error_msg .. '</div>'
	end

	return [[
<!DOCTYPE html>
<html>
<head>
	<meta charset="utf-8">
	<meta name="viewport" content="width=device-width, initial-scale=1.0">
	<title>网络认证 - WiFiDog V3</title>
	<style>
		* { margin: 0; padding: 0; box-sizing: border-box; }
		body {
			font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
			background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
			min-height: 100vh;
			display: flex;
			justify-content: center;
			align-items: center;
		}
		.container {
			background: white;
			border-radius: 12px;
			padding: 40px;
			box-shadow: 0 20px 60px rgba(0,0,0,0.3);
			max-width: 400px;
			width: 90%;
		}
		h1 {
			text-align: center;
			color: #333;
			margin-bottom: 8px;
			font-size: 24px;
		}
		.subtitle {
			text-align: center;
			color: #888;
			margin-bottom: 24px;
			font-size: 14px;
		}
		.form-group {
			margin-bottom: 16px;
		}
		label {
			display: block;
			margin-bottom: 6px;
			color: #555;
			font-weight: 500;
		}
		input[type="text"] {
			width: 100%;
			padding: 12px;
			border: 2px solid #ddd;
			border-radius: 6px;
			font-size: 16px;
			transition: border-color 0.3s;
		}
		input[type="text"]:focus {
			outline: none;
			border-color: #667eea;
		}
		button {
			width: 100%;
			padding: 12px;
			background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
			color: white;
			border: none;
			border-radius: 6px;
			font-size: 16px;
			font-weight: 500;
			cursor: pointer;
			transition: transform 0.1s;
		}
		button:hover { transform: translateY(-1px); }
		button:active { transform: translateY(0); }
		.info {
			margin-top: 16px;
			padding: 12px;
			background: #f0f4ff;
			border-radius: 6px;
			font-size: 13px;
			color: #666;
			text-align: center;
		}
	]] .. error_html .. [[
	</style>
</head>
<body>
	<div class="container">
		<h1>🌐 网络认证</h1>
		<p class="subtitle">请输入授权码以访问互联网</p>
		<form method="POST" action="">
			<input type="hidden" name="action" value="auth">
			<input type="hidden" name="redirect_url" value="]] .. (redirect_url or "") .. [[">
			<div class="form-group">
				<label>授权码</label>
				<input type="text" name="auth_code" placeholder="请输入授权码" required autofocus>
			</div>
			<button type="submit">认证上网</button>
		</form>
		<div class="info">
			如需获取授权码，请联系网络管理员
		</div>
	</div>
</body>
</html>
]]
end

function validate_auth_code(code, client_mac)
	if not code or code == "" then
		return false, "请输入授权码"
	end

	code = code:upper()
	local uci = get_uci()
	local found = nil

	uci:foreach("wifidog_v3", "authcode", function(s)
		if s.code and s.code:upper() == code then
			found = s
		end
	end)

	if not found then
		return false, "授权码无效"
	end

	if found.enabled == "0" then
		return false, "授权码已禁用"
	end

	-- Check usage count
	local max_uses = tonumber(found.max_uses) or 1
	local used_count = tonumber(found.used_count) or 0

	if used_count >= max_uses then
		return false, "授权码使用次数已用完"
	end

	-- Check expiry days
	local expiry_days = tonumber(found.expiry_days) or 30
	local created_date = found.created_date or ""
	if created_date ~= "" then
		local year, month, day = created_date:match("^(%d+)-(%d+)-(%d+)$")
		if year and month and day then
			local created_time = os.time({ year = tonumber(year), month = tonumber(month), day = tonumber(day) })
			local expiry_time = created_time + (expiry_days * 86400)
			if os.time() > expiry_time then
				return false, "授权码已过期"
			end
		end
	end

	-- Update usage count
	uci:set("wifidog_v3", found[".name"], "used_count", tostring(used_count + 1))
	uci:commit("wifidog_v3")

	return true, "ok", code, found.auth_minutes or ""
end

function authorize_client(mac, ip, auth_code, auth_minutes)
	if not mac or mac == "" then
		return
	end

	mac = mac:upper()
	local normalized_auth_minutes = normalize_auth_minutes(auth_minutes)
	local auth_timeout = tonumber(normalized_auth_minutes or "")
	if not auth_timeout then
		auth_timeout = tonumber(sys.exec("uci -q get wifidog_v3.settings.auth_timeout 2>/dev/null") or "1440")
	end
	auth_timeout = auth_timeout or 1440
	local expiry = os.time() + (auth_timeout * 60)

	local uci = get_uci()
	delete_devices_by_mac(mac, uci)

	local section = mac_to_section(mac)
	uci:section("wifidog_v3", "device", section, {
		mac = mac,
		ip = ip or "",
		hostname = "",
		note = "",
		type = "authorized",
		auth_expiry = tostring(expiry),
		auth_source = "code",
		auth_code = auth_code or "",
		created = tostring(os.time())
	})
	uci:commit("wifidog_v3")
end
