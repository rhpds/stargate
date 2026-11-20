"""HTTP probe collector for route-ready — the one observation topology cannot supply.

`oc get route` proves a Route exists and is admitted. It cannot prove the
application answers. `health_endpoint_returns_200` therefore stays unobserved,
and the rubric resolves the stage INDETERMINATE — correctly, because nothing
ever checked (see docs/evidence-observation-semantics.md, "Corrected evidence
boundaries"). This module is the approved probe collector that closes that gap.

Result contract, one CollectedEvidence per probe, ``resource_kind="HttpProbe"``:

    http_status                  int | None    the status the server returned
    health_endpoint_returns_200  bool | None   True for 2xx/3xx; False for a
                                               refused connection or an HTTP
                                               error status; None when the
                                               outcome is genuinely unknown
    probe_error                  str | None    short, non-secret reason
    probe_duration_ms            int
    probed_url                   str           the URL actually requested

Tri-state discipline, same as every other evidence key:

* A timeout is **unobserved** (None). We did not learn that the endpoint fails
  to return 200 — we learned nothing, and the rubric should stay indeterminate.
* A refused connection or an explicit 4xx/5xx response is an **observed**
  non-200 (False). Something answered, or nothing was listening.
* Redirects are not followed: a 3xx is itself an answer (an OAuth-protected
  route redirecting to login is up), and following it would leave the lab's
  host and could turn one probe into a slow multi-hop fetch.
* No response body is read or retained. Only the status line is used.

Read-only: one GET per route, bounded timeout, no credentials, no mutation.
The caller supplies the URL from a Route object; this module does not accept
arbitrary destinations.
"""

from __future__ import annotations

import logging
import os
import socket
import ssl
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

from collectors.openshift.collect_resource_state import CollectedEvidence

logger = logging.getLogger("stargate.route_probe")

_DEFAULT_TIMEOUT_SECONDS = 10
_USER_AGENT = "stargate-route-probe/1.0"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Record a redirect as the answer instead of chasing it off-host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        return None


_ssl_lock = threading.Lock()
_ssl_contexts: Dict[bool, ssl.SSLContext] = {}
_openers: Dict[bool, urllib.request.OpenerDirector] = {}


def _verify_enabled(verify: Optional[bool]) -> bool:
    if verify is not None:
        return verify
    return os.environ.get("STARGATE_SSL_VERIFY", "true").lower() != "false"


def _opener(verify: bool) -> urllib.request.OpenerDirector:
    with _ssl_lock:
        if verify not in _openers:
            ctx = ssl.create_default_context()
            if not verify:
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
            _ssl_contexts[verify] = ctx
            _openers[verify] = urllib.request.build_opener(
                _NoRedirect(), urllib.request.HTTPSHandler(context=ctx)
            )
        return _openers[verify]


def route_url(route_evidence: CollectedEvidence) -> Optional[str]:
    """Build the base URL for a Route's evidence, or None when there is no host.

    OpenShift terminates edge/reencrypt/passthrough TLS at the router, so any
    route with a termination setting is served over https; an unset
    termination is plain http.
    """
    host = (route_evidence.observed or {}).get("host") or ""
    if not host:
        return None
    scheme = "http" if route_evidence.observed.get("tls_termination") in (None, "") else "https"
    return f"{scheme}://{host}"


def _evidence(
    url: str,
    *,
    status: Optional[int],
    healthy: Optional[bool],
    error: Optional[str],
    duration_ms: int,
    namespace: str = "",
) -> CollectedEvidence:
    return CollectedEvidence(
        resource_kind="HttpProbe",
        resource_name=url,
        namespace=namespace,
        observed={
            "http_status": status,
            "health_endpoint_returns_200": healthy,
            "probe_error": error,
            "probe_duration_ms": duration_ms,
            "probed_url": url,
        },
        source="http-probe",
    )


def probe_route(
    url: str,
    *,
    timeout: float = _DEFAULT_TIMEOUT_SECONDS,
    verify: Optional[bool] = None,
    path: str = "/",
    namespace: str = "",
) -> CollectedEvidence:
    """GET ``url + path`` once and report what was observed.

    Never raises for network conditions; the outcome is carried in the
    evidence. Raises ValueError only for a URL without a scheme, which is a
    caller bug, not an observation.
    """
    if "://" not in url:
        raise ValueError(f"probe URL needs a scheme: {url!r}")

    target = url if path == "/" else url.rstrip("/") + path
    started = time.monotonic()

    def _elapsed() -> int:
        return int((time.monotonic() - started) * 1000)

    request = urllib.request.Request(target, method="GET")
    request.add_header("User-Agent", _USER_AGENT)

    try:
        opener = _opener(_verify_enabled(verify))
        with opener.open(request, timeout=timeout) as response:
            status = int(response.status)
            return _evidence(
                target,
                status=status,
                healthy=200 <= status < 400,
                error=None,
                duration_ms=_elapsed(),
                namespace=namespace,
            )
    except urllib.error.HTTPError as exc:
        # The server answered. That is an observation, even when it is a 401.
        status = int(exc.code)
        try:
            exc.close()
        except Exception:  # pragma: no cover - best effort
            pass
        return _evidence(
            target,
            status=status,
            healthy=200 <= status < 400,
            error=None,
            duration_ms=_elapsed(),
            namespace=namespace,
        )
    except urllib.error.URLError as exc:
        reason = exc.reason
        if isinstance(reason, (socket.timeout, TimeoutError)):
            # Unobserved, not failed: the probe ran out of time.
            return _evidence(
                target,
                status=None,
                healthy=None,
                error=f"timeout after {timeout}s",
                duration_ms=_elapsed(),
                namespace=namespace,
            )
        if isinstance(reason, socket.gaierror):
            # The name did not resolve. That says nothing reliable about the
            # application: the scanner's resolver may be the broken part, and
            # a cluster serves every route host from one wildcard. Unobserved.
            return _evidence(
                target,
                status=None,
                healthy=None,
                error=_short_reason(reason),
                duration_ms=_elapsed(),
                namespace=namespace,
            )
        return _evidence(
            target,
            status=None,
            healthy=False,
            error=_short_reason(reason),
            duration_ms=_elapsed(),
            namespace=namespace,
        )
    except (socket.timeout, TimeoutError):
        return _evidence(
            target,
            status=None,
            healthy=None,
            error=f"timeout after {timeout}s",
            duration_ms=_elapsed(),
            namespace=namespace,
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("route probe failed for %s: %s", target, exc)
        return _evidence(
            target,
            status=None,
            healthy=None,
            error=_short_reason(exc),
            duration_ms=_elapsed(),
            namespace=namespace,
        )


def probe_route_evidence(
    route_evidence: CollectedEvidence,
    *,
    timeout: float = _DEFAULT_TIMEOUT_SECONDS,
    verify: Optional[bool] = None,
    path: Optional[str] = None,
) -> Optional[CollectedEvidence]:
    """Probe the Route described by ``route_evidence``.

    Returns None when the Route has no host yet — the caller then has no
    observation to add, and the criterion stays unobserved.

    The request path is the Route's own ``spec.path`` unless one is given, so a
    route mounting the app at ``/showroom`` is not probed at ``/`` and reported
    as a 404.
    """
    url = route_url(route_evidence)
    if not url:
        return None
    if path is None:
        path = (route_evidence.observed or {}).get("path") or "/"
    return probe_route(
        url,
        timeout=timeout,
        verify=verify,
        path=path,
        namespace=route_evidence.namespace,
    )


def _short_reason(exc: Any) -> str:
    """A one-line, non-secret reason for the evidence record."""
    text = str(exc) or exc.__class__.__name__
    text = text.replace("\n", " ").strip()
    return text[:160]
