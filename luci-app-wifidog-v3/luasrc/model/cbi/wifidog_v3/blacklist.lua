-- Blacklist Management Page
local f = SimpleForm("wifidog_v3", translate("黑名单管理"))
f.reset = false
f.submit = false

f:append(Template("wifidog_v3/blacklist"))

return f
