-- Backup and restore page
local f = SimpleForm("wifidog_v3", translate("配置备份"))
f.reset = false
f.submit = false

f:append(Template("wifidog_v3/backup"))

return f
