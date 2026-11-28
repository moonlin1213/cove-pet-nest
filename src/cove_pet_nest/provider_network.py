"""Local model traffic stays on the loopback interface."""
from ipaddress import ip_address
from urllib.parse import urlsplit


def trust_environment_proxy(url):
    host = (urlsplit(url).hostname or '').lower().rstrip('.')
    if host=='localhost' or host.endswith('.localhost'):
        return False
    try:
        address=ip_address(host)
    except ValueError:
        return True
    mapped=getattr(address,'ipv4_mapped',None)
    return not (mapped or address).is_loopback
