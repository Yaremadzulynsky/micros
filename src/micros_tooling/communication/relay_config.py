"""Validate authored relay settings; enrollment credentials remain private files."""
from urllib.parse import urlsplit
from micros_tooling.storage.packages import require


def server_settings(root):
    management = root.get("management", {})
    require(isinstance(management, dict) and management.keys() <= {"server"}, "Unknown management setting")
    server = management.get("server", {})
    require(isinstance(server, dict) and server.keys() <= {"url"}, "management.server accepts url only")
    url = server.get("url", "")
    require(isinstance(url, str), "management.server.url must be a string")
    if url:
        parsed = urlsplit(url)
        require(parsed.scheme == "https" and parsed.hostname and not parsed.username
                and parsed.path in ("", "/") and not parsed.query and not parsed.fragment and len(url) < 160,
                "management.server.url must be an HTTPS origin")
    return url.rstrip("/")


def enrolled_server_settings(root, credentials=None):
    """Use enrollment's server when a minimal application has no server setting."""
    import json
    url = server_settings(root)
    if url or credentials is None:
        return url
    path = credentials / "server.json"
    require(path.is_file(), "Enrollment has no server address. Repeat micros server enroll or set management.server.url before preparing the base.")
    url = server_settings(dict(management=dict(server=json.loads(path.read_text()))))
    require(url, "Enrollment server address is empty")
    return url
