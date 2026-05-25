#!/bin/bash
# Comprehensive multi-container test setup for WiFiDog V3
set -e

echo "=== WiFiDog V3 Multi-Container Test Setup ==="

# Clean up any old containers
docker rm -f openwrt-test-v3 test-client 2>/dev/null || true

# Ensure test network exists
docker network inspect test-net >/dev/null 2>&1 || \
  docker network create --subnet=10.99.0.0/24 --gateway=10.99.0.1 test-net

# Step 1: Create router container
echo "Creating router container..."
docker run -d \
  --name openwrt-test-v3 \
  --platform linux/amd64 \
  --network test-net \
  --ip 10.99.0.2 \
  --cap-add NET_ADMIN \
  --cap-add NET_RAW \
  --sysctl net.ipv4.ip_forward=1 \
  --sysctl net.ipv4.conf.all.route_localnet=1 \
  -p 8880:80 \
  -p 8888:8080 \
  debian:bookworm-slim \
  sleep infinity

# Step 2: Create client container
echo "Creating client container..."
docker run -d \
  --name test-client \
  --platform linux/amd64 \
  --network test-net \
  --ip 10.99.0.10 \
  debian:bookworm-slim \
  sleep infinity

echo "=== Containers created ==="
docker ps --filter name=openwrt-test-v3 --filter name=test-client

# Step 3: Install tools in router
echo "Installing tools in router container..."
docker exec openwrt-test-v3 bash -c '
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq lighttpd iptables ipset curl lua5.1 liblua5.1-0 procps net-tools iproute2 python3 python3-pip 2>&1 | tail -3
# Install Lua socket
apt-get install -y -qq luarocks 2>&1 | tail -1
luarocks install luasocket 2>&1 | tail -1
echo "Router tools installed"
'

# Step 4: Install tools in client
echo "Installing tools in client container..."
docker exec test-client bash -c '
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq curl python3 python3-pip net-tools iproute2 2>&1 | tail -3
pip3 install requests beautifulsoup4 --break-system-packages 2>&1 | tail -3
echo "Client tools installed"
'

# Step 5: Copy app files and setup scripts
echo "Copying app files..."
docker exec openwrt-test-v3 mkdir -p /app
docker cp luci-app-wifidog-v3/. openwrt-test-v3:/app/luci-app-wifidog-v3/
docker cp test/uci_sim.sh openwrt-test-v3:/usr/local/bin/uci
docker cp test/setup_env.sh openwrt-test-v3:/tmp/
docker cp test/run_tests.sh openwrt-test-v3:/tmp/

# Step 6: Setup OpenWrt simulated environment
echo "Setting up simulated OpenWrt environment..."
docker exec openwrt-test-v3 bash /tmp/setup_env.sh 2>&1 | tail -5

# Step 7: Copy app files to OpenWrt paths
echo "Installing app files..."
docker exec openwrt-test-v3 bash -c '
chmod 755 /usr/local/bin/uci

# Copy all app files to correct locations
cp -r /app/luci-app-wifidog-v3/root/etc/config/wifidog_v3 /etc/config/wifidog_v3.app 2>/dev/null || true
cp /app/luci-app-wifidog-v3/root/etc/init.d/wifidog_v3 /etc/init.d/wifidog_v3
cp /app/luci-app-wifidog-v3/root/etc/uci-defaults/40_luci-wifidog-v3 /etc/uci-defaults/40_luci-wifidog-v3
cp /app/luci-app-wifidog-v3/root/www/cgi-bin/wifidog_v3/portal /www/cgi-bin/wifidog_v3/portal
cp /app/luci-app-wifidog-v3/root/www/wifidog_v3/index.html /www/wifidog_v3/index.html

# Copy Lua files
cp /app/luci-app-wifidog-v3/luasrc/controller/wifidog_v3.lua /usr/lib/lua/luci/controller/wifidog_v3.lua
cp /app/luci-app-wifidog-v3/luasrc/model/cbi/wifidog_v3/*.lua /usr/lib/lua/luci/model/cbi/wifidog_v3/
cp /app/luci-app-wifidog-v3/luasrc/view/wifidog_v3/*.htm /usr/lib/lua/luci/view/wifidog_v3/

chmod 755 /www/cgi-bin/wifidog_v3/portal
chmod 755 /etc/init.d/wifidog_v3

echo "App files installed"
'

# Step 8: Setup lighttpd
echo "Configuring lighttpd..."
docker exec openwrt-test-v3 bash -c '
cat > /etc/lighttpd/lighttpd.conf << '\''EOF'\''
server.modules = ("mod_access", "mod_alias", "mod_cgi", "mod_indexfile")
server.document-root = "/www"
server.errorlog = "/var/log/lighttpd/error.log"
server.pid-file = "/var/run/lighttpd.pid"
server.port = 80
index-file.names = ("index.html")

cgi.assign = (".cgi" => "")
$HTTP["url"] =~ "^/cgi-bin/" { cgi.assign = ("" => "") }
$SERVER["socket"] == ":8080" { server.document-root = "/www" }
EOF

mkdir -p /var/log/lighttpd /var/cache/lighttpd
killall lighttpd 2>/dev/null || true
sleep 1
lighttpd -f /etc/lighttpd/lighttpd.conf
sleep 2
pgrep lighttpd >/dev/null && echo "Lighttpd running" || echo "Lighttpd not running"
'

# Step 9: Setup iptables rules
echo "Setting up iptables NAT rules for testing..."
docker exec openwrt-test-v3 bash -c '
# Enable IP forwarding
echo 1 > /proc/sys/net/ipv4/ip_forward

# Setup NAT for client internet access
iptables -t nat -A POSTROUTING -s 10.99.0.0/24 -o eth0 -j MASQUERADE

# Forward traffic from LAN
iptables -A FORWARD -i eth0 -o eth0 -j ACCEPT
iptables -A FORWARD -i eth0 -o eth0 -j ACCEPT 2>/dev/null || true

# Setup ipset
ipset create wifidog_whitelist hash:mac -exist
ipset create wifidog_blacklist hash:mac -exist
ipset create wifidog_authorized hash:mac -exist
ipset create wifidog_pending hash:mac -exist

echo "Network configuration done"
'

# Step 10: Test accessibility
echo "=== Testing connectivity ==="
echo "Router to client:"
docker exec openwrt-test-v3 ping -c 1 10.99.0.10 2>&1 | grep "1 received" && echo "OK" || echo "FAIL"
echo "Client to router:"
docker exec test-client ping -c 1 10.99.0.2 2>&1 | grep "1 received" && echo "OK" || echo "FAIL"
echo "Portal page from client:"
docker exec test-client curl -s http://10.99.0.2/wifidog_v3/index.html 2>&1 | head -3
echo "Portal page from router (localhost):"
docker exec openwrt-test-v3 curl -s http://localhost/wifidog_v3/index.html 2>&1 | head -3

echo "=== Test environment ready ==="
