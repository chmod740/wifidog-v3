-- Auth Code Management Page
local f = SimpleForm("wifidog_v3", translate("授权码管理"))
f.reset = false
f.submit = false

f:append(Template("wifidog_v3/auth_codes"))

return f
