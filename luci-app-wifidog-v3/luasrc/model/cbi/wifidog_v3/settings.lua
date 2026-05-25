-- Settings page using standard CBI Map
local sys = require "luci.sys"

local m = Map("wifidog_v3", translate("WiFiDog V3 系统设置"))

local s = m:section(NamedSection, "settings", "wifidog_v3", translate("基本设置"))

-- Enable/Disable
s:tab("general", translate("基本设置"))

local enabled = s:taboption("general", Flag, "enabled", translate("启用系统"), translate("开启或关闭 WiFiDog V3 认证系统"))
enabled.default = "0"
enabled.rmempty = false

-- WAN Interface auto-detect display
local wan_info = s:taboption("general", DummyValue, "_wan_info", translate("WAN接口自动检测"))
wan_info.rawhtml = true
wan_info.default = [[<script>
(function() {
	var xhr = new XMLHttpRequest();
	xhr.open('GET', ']] .. luci.dispatcher.build_url("admin/services/wifidog_v3/status") .. [[', true);
	xhr.onload = function() {
		// This is handled by status endpoint
	};
	xhr.send();
})();
</script>
<p><em>]] .. translate("系统将自动检测WAN接口，也可在下方手动指定") .. [[</em></p>]]

-- WAN Interface (optional manual override)
local wan_iface = s:taboption("general", Value, "wan_interface", translate("WAN接口"),
	translate("手动指定WAN接口名称，留空则自动检测。常见值：eth0, eth1, wan"))
wan_iface.placeholder = translate("自动检测")
wan_iface.rmempty = true

-- LAN Interface
local lan_iface = s:taboption("general", Value, "lan_interface", translate("LAN接口"),
	translate("内网接口名称，留空则自动检测。可填写物理接口如 br-lan/eth0，或网络名称如 lan"))
lan_iface.placeholder = translate("自动检测")
lan_iface.rmempty = true

-- Portal Port
local portal_port = s:taboption("general", Value, "portal_port", translate("Portal端口"),
	translate("认证页面服务端口，默认 8080"))
portal_port.default = "8080"
portal_port.rmempty = false
portal_port.datatype = "port"

-- LAN Subnet
local lan_subnet = s:taboption("general", Value, "lan_subnet", translate("内网子网"),
	translate("内网子网地址，用于设备扫描时过滤，留空则根据 LAN 地址自动检测"))
lan_subnet.placeholder = translate("自动检测")
lan_subnet.rmempty = true

-- Auth timeout
s:tab("auth", translate("认证设置"))

local auth_timeout = s:taboption("auth", Value, "auth_timeout", translate("授权时长（分钟）"),
	translate("设备授权后的有效时长，默认1440分钟（24小时）"))
auth_timeout.default = "1440"
auth_timeout.rmempty = false
auth_timeout.datatype = "uinteger"

-- Auto-detect WAN
local auto_detect = s:taboption("auth", Flag, "auto_detect_wan", translate("自动检测WAN接口"),
	translate("启用后系统将自动检测WAN接口变化并在设置页面上可选"))
auto_detect.default = "1"
auto_detect.rmempty = false

-- Portal page
s:tab("portal", translate("Portal页面"))

local portal_theme = s:taboption("portal", ListValue, "portal_theme", translate("页面主题"),
	translate("切换 Captive Portal 认证页面的视觉风格"))
portal_theme:value("classic", translate("清爽蓝"))
portal_theme:value("dark", translate("深色"))
portal_theme:value("emerald", translate("森林绿"))
portal_theme:value("warm", translate("暖色"))
portal_theme.default = "classic"
portal_theme.rmempty = false

local portal_title = s:taboption("portal", Value, "portal_title", translate("页面标题"),
	translate("显示在认证页面顶部的标题"))
portal_title.default = translate("网络认证")
portal_title.placeholder = translate("网络认证")
portal_title.rmempty = false

local portal_prompt = s:taboption("portal", TextValue, "portal_prompt", translate("主提示词"),
	translate("显示在标题下方，用于提示用户输入授权码"))
portal_prompt.default = translate("请输入授权码以访问互联网")
portal_prompt.placeholder = translate("请输入授权码以访问互联网")
portal_prompt.rows = 2
portal_prompt.rmempty = false

local portal_hint = s:taboption("portal", TextValue, "portal_hint", translate("底部提示词"),
	translate("显示在表单底部，可填写联系方式或使用说明"))
portal_hint.default = translate("如需获取授权码，请联系网络管理员。认证成功后会自动确认网络状态并尝试关闭认证窗口。")
portal_hint.placeholder = translate("如需获取授权码，请联系网络管理员。")
portal_hint.rows = 3
portal_hint.rmempty = false

local portal_button = s:taboption("portal", Value, "portal_button_text", translate("按钮文字"),
	translate("认证提交按钮上的文字"))
portal_button.default = translate("认证上网")
portal_button.placeholder = translate("认证上网")
portal_button.rmempty = false

local portal_label = s:taboption("portal", Value, "portal_code_label", translate("授权码标签"),
	translate("授权码输入框上方的标签"))
portal_label.default = translate("授权码")
portal_label.placeholder = translate("授权码")
portal_label.rmempty = false

local portal_placeholder = s:taboption("portal", Value, "portal_code_placeholder", translate("输入框占位提示"),
	translate("授权码输入框内的提示文字"))
portal_placeholder.default = translate("请输入授权码")
portal_placeholder.placeholder = translate("请输入授权码")
portal_placeholder.rmempty = false

-- Status section
s:tab("status", translate("系统状态"))

-- Service status
local status = s:taboption("status", DummyValue, "_status", translate("服务状态"))
status.rawhtml = true
status.template = "wifidog_v3/status"

function m.on_after_commit(self)
	local enabled = sys.exec("uci -q get wifidog_v3.settings.enabled 2>/dev/null"):match("^(%d)")
	if enabled == "1" then
		sys.call("/etc/init.d/wifidog_v3 restart >/dev/null 2>&1")
	else
		sys.call("/etc/init.d/wifidog_v3 stop >/dev/null 2>&1")
	end
end

return m
