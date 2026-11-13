"""Who a visitor is, for the limits: a code made from their network and a secret that changes every day.

The address itself is never stored or logged. The secret mixed into the code changes every day (UTC) and old ones
are deleted, so codes cannot be linked across days or turned back into an address.
"""

from __future__ import annotations

import hashlib
import ipaddress
from collections.abc import Mapping

from wts_core.ports import SYSTEM_CLOCK, SYSTEM_RANDOM, Clock, KeyValue, Random
from wts_core.state import today

__all__ = ["client_address", "network_of", "visitor_code"]

SALT = "visitor_salt"
FORWARDED = "x-forwarded-for"


def network_of(address: str | None) -> str:
    """The unit limits count by: an IPv4 address, or an IPv6 /64 (one home or phone connection is given a whole
    /64, so counting single IPv6 addresses would let one person appear as countless visitors)."""
    if not address:
        return "-"
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return address
    if ip.version == 4:
        return str(ip)
    if ip.ipv4_mapped:
        return str(ip.ipv4_mapped)
    return str(ip) if ip.is_loopback else str(ipaddress.ip_network(f"{ip}/64", strict=False))


def _header(headers: Mapping[str, str], name: str) -> str:
    value = headers.get(name)
    if value is None:  # a plain dictionary keeps the case its keys were written in
        value = next((v for k, v in headers.items() if k.lower() == name), "")
    return value


def client_address(headers: Mapping[str, str], peer: str | None, *, behind_proxy: bool,
                   trust_forwarded_first: bool) -> str | None:
    """The visitor's address, read in one of the two ways the sites read it today.

    ``peer`` is the address the web server reports (``request.client.host``). Where MPs Stand and Where Councils
    Stand use it as it is: behind the proxy, the web server has already taken it from ``X-Forwarded-For``
    (``trust_forwarded_first=False``). Where Countries Stand and Where Landlords Stand, behind the proxy, take the
    first entry of ``X-Forwarded-For`` themselves (``trust_forwarded_first=True``), and ``peer`` when the header is
    missing or its first entry is empty (Where Countries Stand's rule; Where Landlords Stand's copy returned the
    empty entry, which counts the same visitors: both are no address).

    Either way is right only if the front door replaces the header rather than adding to it: a header the visitor
    can set is a way round every limit.
    """
    if behind_proxy and trust_forwarded_first:
        return _header(headers, FORWARDED).split(",")[0].strip() or peer
    return peer


def visitor_code(kv: KeyValue, address: str | None, *, day: str | None = None, forget_undated_salt: bool = False,
                 clock: Clock = SYSTEM_CLOCK, random: Random = SYSTEM_RANDOM) -> str:
    """A 24-character code for a visitor's address (an IPv6 address by its /64: ``network_of``), used for daily
    limits and the spending record; the address itself is not kept.

    The day's secret is kept in the key-value store as ``visitor_salt:YYYY-MM-DD``; making a new one deletes every
    other day's. ``day`` fixes the day (tests). ``forget_undated_salt`` also deletes the one un-dated key
    ``visitor_salt`` from this store, should a site's import have copied a permanent secret across (Where MPs Stand
    once had one). A secret left in a site's own old table is the site's import to delete: the package never
    touches a table that is not its own.
    """
    name = f"{SALT}:{day or today(clock)}"
    salt = kv.get(name)
    if salt is None:
        kv.set_if_absent(name, random.token_hex(16))
        kv.delete_like(f"{SALT}:%", keep=name)
        if forget_undated_salt:
            kv.delete(SALT)
        salt = kv.get(name)
    return hashlib.sha256(f"{salt}|{network_of(address)}".encode()).hexdigest()[:24]
