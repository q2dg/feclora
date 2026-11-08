import unittest

from feclora.network.pxe_config import (
    PXEConfigError,
    PXENetworkConfig,
    render_caddy,
    render_dnsmasq,
)


def proxy(**changes):
    values = dict(
        interface="enp1s0",
        address="192.0.2.1",
        prefix_length=24,
        mode="proxy",
        tftp_root="/srv/feclora/tftp",
        bios_boot_file="undionly.kpxe",
        uefi_boot_file="snponly.efi",
        http_root="/srv/feclora/http",
    )
    values.update(changes)
    return PXENetworkConfig(**values)


class PXEConfigTests(unittest.TestCase):
    def test_proxy_profile_has_no_lease_pool_and_binds_selected_address(self):
        rendered = render_dnsmasq(proxy())
        self.assertIn("interface=enp1s0", rendered)
        self.assertIn("listen-address=192.0.2.1", rendered)
        self.assertIn("dhcp-range=192.0.2.0/24,proxy", rendered)
        self.assertNotIn("dhcp-authoritative", rendered)
        self.assertNotIn("0.0.0.0", rendered)

    def test_proxy_rejects_address_pool_options(self):
        with self.assertRaisesRegex(PXEConfigError, "must not define"):
            render_dnsmasq(proxy(pool_start="192.0.2.20", pool_end="192.0.2.80"))

    def test_isolated_requires_explicit_confirmation_and_pool(self):
        with self.assertRaisesRegex(PXEConfigError, "confirmation"):
            render_dnsmasq(proxy(
                mode="isolated",
                pool_start="192.0.2.20",
                pool_end="192.0.2.80",
            ))

    def test_isolated_renders_authoritative_pool_only_after_confirmation(self):
        rendered = render_dnsmasq(proxy(
            mode="isolated",
            pool_start="192.0.2.20",
            pool_end="192.0.2.80",
            authoritative_confirmed=True,
        ))
        self.assertIn("dhcp-authoritative", rendered)
        self.assertIn("dhcp-range=192.0.2.20,192.0.2.80,255.255.255.0,1h", rendered)

    def test_rejects_server_address_inside_pool(self):
        with self.assertRaisesRegex(PXEConfigError, "exclude the server"):
            render_dnsmasq(proxy(
                mode="isolated",
                pool_start="192.0.2.1",
                pool_end="192.0.2.80",
                authoritative_confirmed=True,
            ))

    def test_rejects_invalid_interface_and_wildcard_address(self):
        with self.assertRaises(PXEConfigError):
            render_dnsmasq(proxy(interface="bad interface"))
        with self.assertRaises(PXEConfigError):
            render_dnsmasq(proxy(address="0.0.0.0"))

    def test_caddy_is_plain_http_and_bound_to_deployment_address(self):
        rendered = render_caddy(proxy())
        self.assertIn("http://192.0.2.1:8080", rendered)
        self.assertIn("root * "/srv/feclora/http"", rendered)
        self.assertIn("file_server", rendered)
        self.assertNotIn("https://", rendered)
        self.assertNotIn("0.0.0.0", rendered)


if __name__ == "__main__":
    unittest.main()
