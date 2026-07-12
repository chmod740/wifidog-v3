-- Device Scanning Page - Shows pending/unmanaged devices from ARP table
local f = SimpleForm("wifidog_v3")
f.reset = false
f.submit = false

f:append(Template("wifidog_v3/devices"))

return f
