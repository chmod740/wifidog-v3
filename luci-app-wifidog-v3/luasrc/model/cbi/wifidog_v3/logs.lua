-- Runtime logs page
local f = SimpleForm("wifidog_v3", translate("运行日志"))
f.reset = false
f.submit = false

f:append(Template("wifidog_v3/logs"))

return f
