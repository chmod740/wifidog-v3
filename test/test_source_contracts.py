#!/usr/bin/env python3
"""Fast source-level regression contracts for WiFiDog V3.

These checks complement the Docker/UTM suites. They catch packaging drift and
security-sensitive control-flow regressions without requiring an OpenWrt VM.
Known design gaps are kept as expected failures so they remain visible until
the corresponding production behavior is fixed.
"""

from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "luci-app-wifidog-v3"
CONTROLLER = (APP / "luasrc/controller/wifidog_v3.lua").read_text()
INIT = (APP / "root/etc/init.d/wifidog_v3").read_text()
PORTAL = (APP / "root/www/wifidog_v3/cgi-bin/wifidog_v3/portal").read_text()
MAKEFILE = (APP / "Makefile").read_text()
BUILD_IPK = (ROOT / "build_ipk.sh").read_text()


def block(source: str, start: str, end: str) -> str:
    begin = source.index(start)
    finish = source.index(end, begin + len(start))
    return source[begin:finish]


def config_options(source: str) -> set[str]:
    return set(re.findall(r"^\s*option\s+([a-zA-Z0-9_]+)\s+", source, re.MULTILINE))


class PackagingContracts(unittest.TestCase):
    def test_ipk_version_matches_openwrt_makefile(self) -> None:
        make_version = re.search(r"^PKG_VERSION:=(.+)$", MAKEFILE, re.MULTILINE).group(1)
        make_release = re.search(r"^PKG_RELEASE:=(.+)$", MAKEFILE, re.MULTILINE).group(1)
        script_version = re.search(r'^PKG_VERSION="(.+)"$', BUILD_IPK, re.MULTILINE).group(1)
        script_release = re.search(r'^PKG_RELEASE="(.+)"$', BUILD_IPK, re.MULTILINE).group(1)
        self.assertEqual((script_version, script_release), (make_version, make_release))

    def test_manual_and_sdk_dependency_sets_match(self) -> None:
        sdk_raw = re.search(r"DEPENDS:=(.+)$", MAKEFILE, re.MULTILINE).group(1)
        manual_raw = re.search(r'^PKG_DEPENDS="(.+)"$', BUILD_IPK, re.MULTILINE).group(1)
        sdk = {item.strip().lstrip("+") for item in sdk_raw.split()}
        manual = {item.strip() for item in manual_raw.split(",")}
        self.assertEqual(manual, sdk)

    def test_uci_config_is_protected_during_package_upgrade(self) -> None:
        sdk_conffiles = block(MAKEFILE, "define Package/$(PKG_NAME)/conffiles", "endef")
        self.assertIn("/etc/config/wifidog_v3", sdk_conffiles)
        manual_conffiles = block(
            BUILD_IPK,
            'cat > "$BUILD_DIR/control/conffiles"',
            "# ============================================\n# Step 2",
        )
        self.assertIn("/etc/config/wifidog_v3", manual_conffiles)
        self.assertIn("/etc/config/wifidog_v3-opkg", MAKEFILE)
        self.assertIn("/etc/config/wifidog_v3-opkg", BUILD_IPK)
        self.assertIn("/etc/config/wifidog_v3.apk-new", MAKEFILE)
        self.assertIn("/etc/config/wifidog_v3.apk-new", BUILD_IPK)

    def test_forbidden_legacy_nat_packages_are_not_dependencies(self) -> None:
        dependencies = MAKEFILE + BUILD_IPK
        self.assertNotIn("iptables-mod-nat-extra", dependencies)
        self.assertNotIn("kmod-ipt-nat-extra", dependencies)

    def test_portal_wrapper_targets_packaged_cgi(self) -> None:
        wrapper = (APP / "root/www/cgi-bin/wifidog_v3/portal").read_text()
        self.assertIn("exec /www/wifidog_v3/cgi-bin/wifidog_v3/portal", wrapper)

    def test_lifecycle_scripts_cover_owned_runtime_state(self) -> None:
        required = {
            "nft delete table inet wifidog_v3",
            "/var/run/wifidog_v3_portal.pid",
            "/var/run/wifidog_v3_expiry.pid",
            "/tmp/dnsmasq.d/wifidog_v3.conf",
            "/tmp/wifidog_v3_ip_sessions",
            "/www/wifidog_v3",
        }
        for source in (MAKEFILE, BUILD_IPK):
            for marker in required:
                self.assertIn(marker, source)


class ConfigurationContracts(unittest.TestCase):
    def test_default_config_and_uci_defaults_have_same_settings(self) -> None:
        config = (APP / "root/etc/config/wifidog_v3").read_text()
        defaults = (APP / "root/etc/uci-defaults/40_luci-wifidog-v3").read_text()
        self.assertEqual(config_options(config), config_options(defaults))

    def test_all_default_settings_are_backed_up(self) -> None:
        config = (APP / "root/etc/config/wifidog_v3").read_text()
        settings_block = block(CONTROLLER, "local settings_keys = {", "local settings_defaults = {")
        backed_up = set(re.findall(r'"([a-zA-Z0-9_]+)"', settings_block))
        self.assertEqual(config_options(config), backed_up)

    def test_settings_model_exposes_every_default_setting(self) -> None:
        settings = (APP / "luasrc/model/cbi/wifidog_v3/settings.lua").read_text()
        missing = {key for key in config_options((APP / "root/etc/config/wifidog_v3").read_text()) if f'"{key}"' not in settings}
        self.assertEqual(missing, set())


class PortalContracts(unittest.TestCase):
    def test_portal_has_rfc8908_and_legacy_probe_support(self) -> None:
        for marker in (
            "application/captive+json",
            "/.well-known/captive-portal",
            "/generate_204",
            "/hotspot-detect.html",
            "/ncsi.txt",
            "/connecttest.txt",
        ):
            self.assertIn(marker, PORTAL)

    def test_portal_escapes_html_and_json_dynamic_values(self) -> None:
        self.assertIn("local function html_escape", PORTAL)
        self.assertIn("local function json_escape", PORTAL)
        self.assertIn("html_escape(redirect_url)", PORTAL)
        self.assertIn("json_escape(redirect_url or \"\")", PORTAL)

    def test_blacklist_branch_precedes_post_authentication(self) -> None:
        blacklist = PORTAL.index('device.type == "blacklist"')
        post = PORTAL.index('if method == "POST" then', blacklist + 1)
        authorize = PORTAL.index("authorize_with_code", post)
        self.assertLess(blacklist, authorize)

    def test_radius_response_authenticator_is_verified(self) -> None:
        self.assertIn("response:sub(5, 20) ~= expected_auth", PORTAL)
        self.assertIn("response_id ~= packet_id", PORTAL)

    def test_radius_password_is_not_written_to_runtime_log(self) -> None:
        log_calls = "\n".join(re.findall(r"append_runtime_log\((.*?)\)\s*", PORTAL))
        self.assertNotIn("radius_password", log_calls)
        self.assertNotIn("form.password", log_calls)

    def test_auth_success_exposes_duration_and_expiry(self) -> None:
        for marker in ('"expires_at"', '"expires_at_text"', '"valid_seconds"', '"valid_text"'):
            self.assertIn(marker, PORTAL)

    def test_ip_session_cache_requires_current_unrestricted_device(self) -> None:
        session_lookup = block(PORTAL, "local function get_device_by_ip_session", "local function resolve_client_device")
        self.assertIn("is_unrestricted_device(device)", session_lookup)
        self.assertIn("forget_ip_session(ip)", session_lookup)

    def test_auth_code_is_not_consumed_before_client_mac_is_known(self) -> None:
        transaction = block(PORTAL, "local function authorize_with_code", "local function read_body")
        mac_reject = transaction.index('if not mac or mac == "" then')
        consume = transaction.index("validate_auth_code(code)")
        self.assertLess(mac_reject, consume)
        self.assertIn("acquire_auth_lock", PORTAL)
        self.assertIn("used_count + 1", transaction)

    def test_post_body_has_a_hard_size_limit(self) -> None:
        reader = block(PORTAL, "local function read_body()", "local function request_target()")
        self.assertRegex(reader, r"(MAX_REQUEST|413|Payload Too Large|length\s*>\s*\d+)")

    def test_disabling_all_auth_methods_does_not_reenable_code_auth(self) -> None:
        self.assertNotIn("if not code_enabled and not radius_enabled then\n\t\tcode_enabled = true", PORTAL)

    def test_portal_responses_set_basic_browser_security_headers(self) -> None:
        response_fn = block(PORTAL, "local function response", "local function json_response")
        self.assertIn("X-Content-Type-Options", response_fn)
        self.assertIn("Content-Security-Policy", response_fn)


class FirewallAndServiceContracts(unittest.TestCase):
    def test_dhcp_rules_precede_pending_drop(self) -> None:
        discover = INIT.index("udp sport 68 udp dport 67 return")
        drop = INIT.index('meta nfproto ipv6 drop')
        self.assertLess(discover, drop)

    def test_dns_is_explicitly_allowed_for_pending_clients(self) -> None:
        self.assertIn("portal_pre_filter udp dport 53 return", INIT)
        self.assertIn("portal_pre_filter tcp dport 53 return", INIT)
        self.assertIn("portal_nat udp dport 53 return", INIT)

    def test_passwall_precedence_chains_remain_early(self) -> None:
        self.assertIn("priority -310", INIT)
        self.assertIn("priority -199", INIT)

    def test_tls_is_blocked_instead_of_redirected_to_plain_http(self) -> None:
        self.assertNotIn("portal_nat tcp dport 443 redirect", INIT)
        self.assertIn("portal_pre_filter tcp dport 443 return", INIT)

    def test_advertisement_setup_has_matching_cleanup(self) -> None:
        self.assertIn("setup_captive_portal_advertisement", INIT)
        self.assertIn("cleanup_captive_portal_advertisement", INIT)
        self.assertIn("odhcpd_prev_captive_portal_uri", INIT)

    def test_init_script_is_valid_posix_shell_syntax(self) -> None:
        result = subprocess.run(["sh", "-n", str(APP / "root/etc/init.d/wifidog_v3")], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_failed_start_rolls_back_firewall_and_advertisements(self) -> None:
        start = block(INIT, "start_service()", "stop_service()")
        self.assertIn("if ! setup_nft; then", start)
        self.assertIn("if ! start_portal_server; then", start)
        self.assertGreaterEqual(start.count("cleanup_captive_portal_advertisement"), 3)
        self.assertIn("cleanup_firewall", start)

    def test_expiry_preserves_device_metadata_as_pending(self) -> None:
        expiry = block(INIT, "check_device_expiry()", "start_service()")
        self.assertIn(".type=pending", expiry)
        self.assertNotIn('uci -q delete "wifidog_v3.$cfg"', expiry)


class LuCIContracts(unittest.TestCase):
    def test_only_dedicated_cgi_portal_is_public(self) -> None:
        public_entries = re.findall(r'entry\(\{([^}]+)\}.*?\)\.sysauth\s*=\s*false', CONTROLLER)
        self.assertEqual(public_entries, [])

    def test_mutating_views_attach_csrf_token(self) -> None:
        for name in ("devices.htm", "whitelist.htm", "blacklist.htm", "auth_codes.htm", "backup.htm", "logs.htm"):
            text = (APP / f"luasrc/view/wifidog_v3/{name}").read_text()
            self.assertIn("authtoken", text, name)
            self.assertTrue("token=" in text or "set('token'" in text, name)

    def test_list_views_guard_json_arrays(self) -> None:
        expectations = {
            "devices.htm": "Array.isArray(data.devices)",
            "whitelist.htm": "Array.isArray(data.devices)",
            "blacklist.htm": "Array.isArray(data.devices)",
            "auth_codes.htm": "Array.isArray(data.codes)",
        }
        for name, marker in expectations.items():
            self.assertIn(marker, (APP / f"luasrc/view/wifidog_v3/{name}").read_text(), name)

    def test_auth_code_rows_escape_untrusted_backup_values(self) -> None:
        view = (APP / "luasrc/view/wifidog_v3/auth_codes.htm").read_text()
        self.assertIn("function esc(", view)
        self.assertIn("esc(c.code)", view)
        self.assertNotIn('onclick="deleteCode', view)

    def test_device_mutations_validate_mac_before_uci_section_creation(self) -> None:
        for action, next_action in (
            ("function action_add_whitelist()", "function action_add_blacklist()"),
            ("function action_add_blacklist()", "function action_add_authorize()"),
            ("function action_add_authorize()", "function action_update_note()"),
            ("function action_update_note()", "function action_remove_device()"),
        ):
            body = block(CONTROLLER, action, next_action)
            self.assertIn("normalize_mac(mac)", body, action)

    def test_runtime_log_has_bounded_rotation(self) -> None:
        combined = CONTROLLER + INIT + PORTAL
        self.assertRegex(combined, r"(logrotate|max_log_size|LOG_MAX_BYTES|rotate_runtime_log)")

    def test_management_pages_share_responsive_dashboard_structure(self) -> None:
        for name in ("devices.htm", "whitelist.htm", "blacklist.htm", "auth_codes.htm", "backup.htm", "logs.htm"):
            view = (APP / f"luasrc/view/wifidog_v3/{name}").read_text()
            self.assertIn("wifidog-shell", view, name)
            self.assertIn("wifidog-page-head", view, name)
            self.assertIn("wifidog-panel", view, name)

        styles = (APP / "luasrc/view/wifidog_v3/styles.htm").read_text()
        for marker in (
            "--wd-surface: rgba",
            "prefers-color-scheme: dark",
            "max-width: 1280px",
            "max-width: 700px",
            "overflow-x: auto",
            "wifidog-state-banner",
        ):
            self.assertIn(marker, styles)

    def test_management_pages_do_not_render_duplicate_simpleform_titles(self) -> None:
        for name in ("devices.lua", "whitelist.lua", "blacklist.lua", "auth_codes.lua", "backup.lua", "logs.lua"):
            model = (APP / f"luasrc/model/cbi/wifidog_v3/{name}").read_text()
            self.assertIn('SimpleForm("wifidog_v3")', model, name)
            self.assertNotIn('SimpleForm("wifidog_v3",', model, name)

    def test_settings_page_loads_shared_styles_without_noop_request(self) -> None:
        settings = (APP / "luasrc/model/cbi/wifidog_v3/settings.lua").read_text()
        self.assertIn('m:append(Template("wifidog_v3/styles"))', settings)
        self.assertNotIn("xhr.open", settings)


if __name__ == "__main__":
    unittest.main(verbosity=2)
