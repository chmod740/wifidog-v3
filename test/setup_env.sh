#!/bin/bash
# Setup simulated OpenWrt environment for testing

set -e

echo "=== Setting up simulated OpenWrt environment ==="

# Create directory structure
mkdir -p /etc/config
mkdir -p /etc/init.d
mkdir -p /etc/uci-defaults
mkdir -p /etc/rc.d
mkdir -p /usr/lib/lua/luci/controller
mkdir -p /usr/lib/lua/luci/model/cbi/wifidog_v3
mkdir -p /usr/lib/lua/luci/view/wifidog_v3
mkdir -p /www/wifidog_v3
mkdir -p /www/cgi-bin/wifidog_v3
mkdir -p /www/luci-static/resources/view/wifidog_v3
mkdir -p /var/run
mkdir -p /var/log
mkdir -p /tmp

# Create UCI simulator script
cat > /usr/local/bin/uci << 'UCIEOF'
#!/bin/bash
# UCI Simulator for testing - stores config in /etc/config/<name>
# Supports: get, set, delete, commit, show, foreach, add_list

CONFIG_DIR="/etc/config"

uci_get() {
    local config="$1"
    local section="$2"
    local option="$3"
    local file="${CONFIG_DIR}/${config}"

    if [ ! -f "$file" ]; then
        return 1
    fi

    # Parse config file looking for the section and option
    local in_section=0
    local found_section=""
    while IFS= read -r line; do
        # Match section start
        if echo "$line" | grep -qE "^(config|set) [^ ]+"; then
            local sec_name=$(echo "$line" | sed -n "s/^config [^ ]\+ '\(.*\)'\|^set [^ ]\+\.\([^=]*\)=.*/\1\2/p" | head -1)

            # For "config type 'name'"
            if echo "$line" | grep -q "^config"; then
                found_section=$(echo "$line" | sed -n "s/^config [^ ]\+ '\(.*\)'/\1/p")
            fi

            # For "set config.section.option=value"
            if echo "$line" | grep -q "^set"; then
                local full_key=$(echo "$line" | sed 's/^set //;s/=.*//')
                local cfg=$(echo "$full_key" | cut -d. -f1)
                local sec=$(echo "$full_key" | cut -d. -f2)
                if [ "$cfg" = "$config" ] && [ "$sec" = "$section" ]; then
                    local opt=$(echo "$full_key" | cut -d. -f3-)
                    if [ "$opt" = "$option" ]; then
                        echo "$line" | sed 's/^[^=]*=//'
                        return 0
                    fi
                fi
                continue
            fi

            if [ "$found_section" = "$section" ]; then
                in_section=1
            else
                in_section=0
            fi
            continue
        fi

        if [ "$in_section" -eq 1 ] && echo "$line" | grep -q "option ${option} "; then
            echo "$line" | sed "s/.*option ${option} '\(.*\)'/\1/"
            return 0
        fi
    done < "$file"
    return 1
}

uci_set() {
    local config="$1"
    local section="$2"
    local option="$3"
    local value="$4"
    local file="${CONFIG_DIR}/${config}"

    if [ "$option" = "$section" ] || [ -z "$option" ]; then
        # Adding a new section
        if [ ! -f "$file" ]; then
            mkdir -p "$CONFIG_DIR"
            touch "$file"
        fi
        echo "set ${config}.${section}=${section}" >> "${CONFIG_DIR}/${config}.pending"
        return 0
    fi

    # Store pending changes
    echo "set ${config}.${section}.${option}=${value}" >> "${CONFIG_DIR}/${config}.pending"
    return 0
}

uci_delete() {
    local full_key="$1"
    local config=$(echo "$full_key" | cut -d. -f1)
    local rest=$(echo "$full_key" | cut -d. -f2-)

    echo "delete ${full_key}" >> "${CONFIG_DIR}/${config}.pending"
    return 0
}

uci_commit() {
    local config="$1"
    local pending="${CONFIG_DIR}/${config}.pending"
    local file="${CONFIG_DIR}/${config}"

    if [ -f "$pending" ]; then
        while IFS= read -r cmd; do
            if echo "$cmd" | grep -q "^set "; then
                # Apply set command to config file
                local key=$(echo "$cmd" | sed 's/^set //;s/=.*//')
                local val=$(echo "$cmd" | sed 's/^[^=]*=//')

                # Check if this key already exists in the file
                if [ -f "$file" ] && grep -q "^set ${key}=" "$file" 2>/dev/null; then
                    sed -i "s|^set ${key}=.*|set ${key}=${val}|" "$file"
                else
                    echo "set ${key}=${val}" >> "$file"
                fi
            elif echo "$cmd" | grep -q "^delete "; then
                local del_key=$(echo "$cmd" | sed 's/^delete //')
                if [ -f "$file" ]; then
                    sed -i "/^set ${del_key}=/d; /^set ${del_key}\./d" "$file"
                fi
            fi
        done < "$pending"
        rm -f "$pending"
    fi
}

uci_show() {
    local config="$1"
    local file="${CONFIG_DIR}/${config}"
    if [ -f "$file" ]; then
        cat "$file"
    fi
}

uci_foreach() {
    local config="$1"
    local type="$2"
    local handler="$3"
    local file="${CONFIG_DIR}/${config}"

    if [ ! -f "$file" ]; then
        return 0
    fi

    # Extract sections of the given type and call the handler
    local sections=$(grep "^set ${config}\.[^.]*=${type}$" "$file" 2>/dev/null | sed "s/set ${config}\.\([^=]*\)=${type}/\1/")

    for sec in $sections; do
        # Create a temp file with the section's options
        local tmpfile=$(mktemp)
        grep "^set ${config}\.${sec}\." "$file" > "$tmpfile" 2>/dev/null || true
        # Call handler with section name
        if [ -n "$handler" ]; then
            $handler "$sec" "$tmpfile"
        fi
        rm -f "$tmpfile"
    done
}

# Main command parsing
case "$1" in
    get)
        uci_get "$2" "$3" "$4"
        ;;
    set)
        uci_set "$2" "$3" "$4" "$5"
        ;;
    delete)
        uci_delete "$2"
        ;;
    commit)
        uci_commit "$2"
        ;;
    show)
        uci_show "$2"
        ;;
    foreach)
        uci_foreach "$2" "$3" "$4"
        ;;
    -q)
        shift
        case "$1" in
            get) uci_get "$2" "$3" "$4" ;;
            set) uci_set "$2" "$3" "$4" "$5" ;;
            delete) uci_delete "$2" ;;
            commit) uci_commit "$2" ;;
            show) uci_show "$2" ;;
            *) echo "Unknown -q command: $1" ;;
        esac
        ;;
    *)
        echo "Usage: uci [get|set|delete|commit|show|foreach] <args>"
        ;;
esac
UCIEOF

chmod 755 /usr/local/bin/uci
echo "UCI simulator installed at /usr/local/bin/uci"

# Create logger simulator
cat > /usr/local/bin/logger << 'LOGEOF'
#!/bin/bash
echo "[$(date)] $*" >> /var/log/test.log
LOGEOF
chmod 755 /usr/local/bin/logger
echo "Logger simulator installed"

# Create proc/net/arp for testing
mkdir -p /proc/net
cat > /proc/net/arp << 'ARPEOF'
IP address       HW type     Flags       HW address            Mask     Device
192.168.1.100    0x1         0x2         aa:bb:cc:dd:ee:01     *        br-lan
192.168.1.101    0x1         0x2         aa:bb:cc:dd:ee:02     *        br-lan
192.168.1.1      0x1         0x2         00:11:22:33:44:55     *        br-lan
ARPEOF
echo "Simulated ARP table created"

# Create simulated DHCP leases
mkdir -p /tmp
cat > /tmp/dhcp.leases << 'LEASEOF'
1234567890 aa:bb:cc:dd:ee:01 192.168.1.100 test-phone-01 *
1234567890 aa:bb:cc:dd:ee:02 192.168.1.101 test-laptop-02 *
LEASEOF
echo "Simulated DHCP leases created"

# Create minimal network config
mkdir -p /etc/config
cat > /etc/config/network << 'NETEOF'
config interface 'lan'
	option device 'br-lan'
	option ipaddr '192.168.1.1'
	option netmask '255.255.255.0'

config interface 'wan'
	option device 'eth0'
	option proto 'dhcp'
NETEOF

# Create firewall config
cat > /etc/config/firewall << 'FWEOF'
config include
	option name 'wifidog-v3'
	option path '/etc/init.d/wifidog_v3'
	option reload '1'
FWEOF

# Create simulated sysfs for MAC addresses
mkdir -p /sys/class/net/eth0
echo "00:11:22:33:44:55" > /sys/class/net/eth0/address
mkdir -p /sys/class/net/br-lan
echo "00:11:22:33:44:55" > /sys/class/net/br-lan/address

# Create the wifidog_v3 config directory for the app
mkdir -p /etc/config
cat > /etc/config/wifidog_v3 << 'WCEOF'
config wifidog_v3 'settings'
	option enabled '0'
	option wan_interface ''
	option lan_interface 'lan'
	option portal_port '8080'
	option lan_subnet '192.168.1.0/24'
	option auth_timeout '1440'
	option auto_detect_wan '1'

config authcode 'auth_VIP2024'
	option code 'VIP2024'
	option max_uses '10'
	option used_count '0'
	option expiry_days '30'
	option auth_minutes '5'
	option created_date '2026-01-01'
	option enabled '1'

config authcode 'auth_TEST123'
	option code 'TEST123'
	option max_uses '1'
	option used_count '1'
	option expiry_days '30'
	option created_date '2026-01-01'
	option enabled '1'

config device 'aa_bb_cc_dd_ee_03'
	option mac 'AA:BB:CC:DD:EE:03'
	option ip '192.168.1.200'
	option hostname 'test-whitelist-device'
	option type 'whitelist'
	option auth_expiry '0'
	option created '1700000000'

config device 'aa_bb_cc_dd_ee_04'
	option mac 'AA:BB:CC:DD:EE:04'
	option ip '192.168.1.201'
	option hostname 'test-blacklist-device'
	option type 'blacklist'
	option auth_expiry '0'
	option created '1700000000'

config device 'aa_bb_cc_dd_ee_05'
	option mac 'AA:BB:CC:DD:EE:05'
	option ip '192.168.1.202'
	option hostname 'test-authorized-device'
	option type 'authorized'
	option auth_expiry '2000000000'
	option created '1700000000'
WCEEOF

echo "Environment setup complete!"
