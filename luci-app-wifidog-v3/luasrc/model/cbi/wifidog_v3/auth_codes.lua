-- Auth Code Management Page
local f = SimpleForm("wifidog_v3")
f.reset = false
f.submit = false

f:append(Template("wifidog_v3/auth_codes"))

return f
