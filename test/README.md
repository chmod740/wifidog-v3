# Test Suites

Current release gates:

- `test_source_contracts.py`: fast source, packaging, security, and lifecycle contracts.
- `e2e_openwrt23_container.py`: authoritative Docker OpenWrt 23.05 end-to-end regression.
- `utm_smoke.lua`: OpenWrt 24/25 UTM functional smoke regression.
- `utm_radius_check.sh`: UTM FreeRADIUS PAP and `Session-Timeout` regression.
- `utm_serial.py`: helper for running commands through a UTM PTY serial console.

Run the local release gates:

```sh
python3 test/test_source_contracts.py
python3 test/e2e_openwrt23_container.py
```

The other scripts in this directory are retained as historical compatibility
fixtures. Some still reference the project's earlier iptables, ipset, or
lighttpd implementation and are not release gates for the current nftables and
uhttpd architecture.
