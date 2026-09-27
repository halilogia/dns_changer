"""Check GitHub Releases for a newer Apex DNS Changer build.

Design notes
------------
The checker is deliberately dependency-free: it talks to the API with
:mod:`urllib.request` from the standard library and borrows the TLS context
built by :func:`core.resolver.ssl_context`, which layers certifi's CA bundle
over the platform store.  The Windows certificate store is missing
intermediates for some chains, so verifying with a bare
:func:`ssl.create_default_context` is not reliable here and the shared helper
is reused instead of building a second context.

Every failure path collapses into an :class:`UpdateInfo` carrying
``available=False`` and a short human-readable ``error``.
:func:`check_for_update` never raises: it is called from the settings panel
where an exception would tear down the UI, and an update check is a
nice-to-have that must not be able to break the app.

Versions are compared as integer tuples rather than strings, because
``"2.10.0" > "2.9.0"`` is False lexicographically but True semantically.
Parsing is intentionally forgiving (missing components, a leading ``v``,
trailing pre-release junk) and degrades to "nothing to compare" instead of
raising, so a malformed tag can never be mistaken for a newer build.

Network access is injectable through the ``fetch`` parameter, whose signature
is ``fetch(url: str, timeout: float) -> bytes``.  That seam is what the tests
drive, so the suite is deterministic and never touches the network.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

from core import resolver

__all__ = [
    "DEFAULT_REPO",
    "NOTES_LIMIT",
    "RELEASES_URL",
    "USER_AGENT",
    "UpdateInfo",
    "check_for_update",
    "is_newer",
    "parse_version",
]

DEFAULT_REPO = "halilogia/dns_changer"
RELEASES_URL = "https://api.github.com/repos/{repo}/releases/latest"

#: GitHub rejects requests that carry no User-Agent, and the default urllib
#: agent ("Python-urllib/3.x") is rate limited far more aggressively.
USER_AGENT = "ApexDNSChanger/2.0.0"

#: Release bodies run to tens of kilobytes; the UI only shows a teaser.
NOTES_LIMIT = 2000

_ERROR_LIMIT = 120
_UNPARSEABLE: tuple[int, ...] = (0, 0, 0)
_VERSION_RE = re.compile(r"\d+(?:\.\d+)*")


@dataclass(frozen=True, slots=True)
class UpdateInfo:
    """Outcome of one update check.

    ``available`` is the only field the UI branches on; ``error`` explains why
    a check that did not produce a version failed, and is empty on success.
    """

    available: bool
    current: str
    latest: str = ""
    url: str = ""
    notes: str = ""
    error: str = ""
    prerelease: bool = False


def _segments(text: object) -> list[int]:
    """Return the numeric components found in ``text``.

    Tolerates a leading ``v``, missing components and trailing junk such as
    ``-beta.1``.  Returns an empty list when no number can be found, which the
    callers treat as "unparseable" rather than as version ``0``.
    """
    if text is None:
        return []
    match = _VERSION_RE.search(str(text).strip())
    if match is None:
        return []
    return [int(part) for part in match.group(0).split(".") if part]


def parse_version(text: str) -> tuple:
    """Turn a version string into a comparable tuple of integers.

    ``"2.1.0"`` and ``"v2.1.0"`` both give ``(2, 1, 0)``; ``"2.1"`` is padded
    to ``(2, 1, 0)``.  Anything unparseable yields ``(0, 0, 0)``, which sorts
    below every real version so a broken tag reads as "older", never "newer".
    """
    parts = _segments(text)
    if not parts:
        return _UNPARSEABLE
    return tuple(parts + [0] * (3 - len(parts))) if len(parts) < 3 else tuple(parts)


def is_newer(remote: str, local: str) -> bool:
    """Return ``True`` only when ``remote`` is strictly newer than ``local``.

    Returns ``False`` when either side cannot be parsed: an unreadable version
    is never evidence of an upgrade.
    """
    remote_parts = _segments(remote)
    local_parts = _segments(local)
    if not remote_parts or not local_parts:
        return False
    size = max(len(remote_parts), len(local_parts))
    padded_remote = tuple(remote_parts) + (0,) * (size - len(remote_parts))
    padded_local = tuple(local_parts) + (0,) * (size - len(local_parts))
    return padded_remote > padded_local


def _fetch_url(url: str, timeout: float) -> bytes:
    """Default transport: one GET against the GitHub API.

    Kept tiny and isolated so that :func:`check_for_update` can swap it out.
    """
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(request, timeout=timeout, context=resolver.ssl_context()) as response:
        return response.read()


def _error_text(exc: BaseException) -> str:
    """Render an exception as a short line suitable for the UI."""
    if isinstance(exc, urllib.error.HTTPError):
        return f"GitHub answered HTTP {exc.code}"
    reason = " ".join(str(exc).split()) or exc.__class__.__name__
    return f"{exc.__class__.__name__}: {reason}"[:_ERROR_LIMIT]


def _clean_notes(body: object) -> str:
    """Trim a release body, clipping it to :data:`NOTES_LIMIT` characters."""
    text = body if isinstance(body, str) else ("" if body is None else str(body))
    notes = text.strip()
    if len(notes) <= NOTES_LIMIT:
        return notes
    return notes[: NOTES_LIMIT - 3].rstrip() + "..."


def _strip_tag(tag: str) -> str:
    """Drop the conventional leading ``v`` from a release tag."""
    return tag[1:] if tag[:1] in ("v", "V") else tag


def _text(value: object) -> str:
    return str(value).strip() if value is not None else ""


def check_for_update(
    current_version: str,
    *,
    repo: str = DEFAULT_REPO,
    timeout: float = 6.0,
    fetch=None,
) -> UpdateInfo:
    """Ask GitHub whether a newer release exists.

    ``fetch(url, timeout) -> bytes`` replaces the real HTTP call when given,
    which is how the tests stay offline.  This function does not raise: any
    transport, HTTP, or decoding problem is reported through
    :attr:`UpdateInfo.error` with ``available=False``.
    """
    current = _text(current_version)
    getter = fetch if fetch is not None else _fetch_url
    try:
        url = RELEASES_URL.format(repo=_text(repo).strip("/") or DEFAULT_REPO)
        raw = getter(url, timeout)
    except urllib.error.HTTPError as exc:
        return UpdateInfo(available=False, current=current, error=_error_text(exc))
    except Exception as exc:  # transport failures, timeouts, bad arguments
        return UpdateInfo(available=False, current=current, error=_error_text(exc))

    try:
        text = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw)
        payload = json.loads(text)
    except Exception as exc:
        return UpdateInfo(available=False, current=current, error=f"Could not read the response ({_error_text(exc)})")

    if not isinstance(payload, dict):
        return UpdateInfo(available=False, current=current, error="Unexpected response from GitHub")

    latest = _strip_tag(_text(payload.get("tag_name")))
    if not latest:
        return UpdateInfo(available=False, current=current, error="No release tag in the response")

    return UpdateInfo(
        available=is_newer(latest, current),
        current=current,
        latest=latest,
        url=_text(payload.get("html_url")),
        notes=_clean_notes(payload.get("body")),
        prerelease=bool(payload.get("prerelease")),
    )
