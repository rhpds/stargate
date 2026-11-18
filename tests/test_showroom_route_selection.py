"""The showroom check must probe the showroom route — not the first route.

Found against 16 Nov evidence: failing runs probed `containerview-*` and even
`adminer-*`, while the showroom route was healthy. Deployment 1/1, pods ready,
endpoints ready, Service 8080→8080.
"""

from cli.worker import _pick_showroom_host


ROUTES = "\n".join([
    "adminer=adminer-z9vlb.apps.ocpv06.rhdp.net",
    "containerview=containerview-z9vlb.apps.ocpv06.rhdp.net",
    "showroom=showroom-z9vlb.apps.ocpv06.rhdp.net",
])


class TestPickShowroomHost:
    def test_ignores_adminer_and_containerview(self):
        assert _pick_showroom_host(ROUTES) == "showroom-z9vlb.apps.ocpv06.rhdp.net"

    def test_returns_empty_when_no_showroom_route_exists(self):
        assert _pick_showroom_host("adminer=a.example.com\nconsole=c.example.com") == ""

    def test_tolerates_blank_and_malformed_lines(self):
        assert _pick_showroom_host("\n\nshowroom=s.example.com\n") == "s.example.com"
