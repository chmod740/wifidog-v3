#!/bin/sh
set -eu

mac="AA:BB:CC:DD:EE:55"
sec="aa_bb_cc_dd_ee_55"
ip="192.168.77.55"
body="action=auth&auth_method=radius&radius_username=raduser&radius_password=radpass"

killall wifidog_v3 2>/dev/null || true
uci set wifidog_v3.settings.enabled=1
uci set wifidog_v3.settings.radius_enabled=1
uci set wifidog_v3.settings.radius_server=192.168.64.1
uci set wifidog_v3.settings.radius_port=1812
uci set wifidog_v3.settings.radius_secret=testing123
uci set wifidog_v3.settings.radius_timeout=3
uci set wifidog_v3.settings.radius_retries=1
uci commit wifidog_v3

uci -q delete "wifidog_v3.$sec" 2>/dev/null || true
uci commit wifidog_v3
printf "%s %s %s %s *\n" "$(($(date +%s) + 600))" "$mac" "$ip" "radius-phone" >> /tmp/dhcp.leases

out=$(
	printf "%s" "$body" | \
		REQUEST_METHOD=POST \
		CONTENT_LENGTH=${#body} \
		CONTENT_TYPE=application/x-www-form-urlencoded \
		REMOTE_ADDR="$ip" \
		/www/wifidog_v3/cgi-bin/wifidog_v3/portal
)

source="$(uci -q get "wifidog_v3.$sec.auth_source")"
user="$(uci -q get "wifidog_v3.$sec.radius_user")"
left="$(($(uci -q get "wifidog_v3.$sec.auth_expiry") - $(date +%s)))"

echo "$out"
echo "SOURCE:$source"
echo "RUSER:$user"
echo "LEFT:$left"

case "$out:$source:$user:$left" in
	*'"success":true'*:radius:raduser:*)
		if [ "$left" -ge 240 ] && [ "$left" -le 360 ]; then
			echo "UTM_RADIUS_OK"
			exit 0
		fi
		;;
esac

echo "UTM_RADIUS_FAILED"
exit 1
