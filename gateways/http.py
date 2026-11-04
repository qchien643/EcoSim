"""Standard-library HTTPS transport with IPv4 routing."""
import http.client
import io
import json
import socket
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit, urlunsplit


class IPv4HTTPSConnection(http.client.HTTPSConnection):
    def connect(self):
        addresses = socket.getaddrinfo(
            self.host, self.port, socket.AF_INET, socket.SOCK_STREAM
        )
        if not addresses:
            raise OSError(f"No IPv4 address for {self.host}")
        _, socktype, proto, _, address = addresses[0]
        sock = socket.socket(socket.AF_INET, socktype, proto)
        try:
            sock.settimeout(self.timeout)
            sock.connect(address)
            if self._tunnel_host:
                self.sock = sock
                self._tunnel()
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except Exception:
            sock.close()
            raise

class IPv4HTTPConnection(http.client.HTTPConnection):
    def connect(self):
        addresses = socket.getaddrinfo(
            self.host, self.port, socket.AF_INET, socket.SOCK_STREAM
        )
        if not addresses:
            raise OSError(f"No IPv4 address for {self.host}")
        _, socktype, proto, _, address = addresses[0]
        sock = socket.socket(socket.AF_INET, socktype, proto)
        try:
            sock.settimeout(self.timeout)
            sock.connect(address)
            self.sock = sock
        except Exception:
            sock.close()
            raise


def _retry_after_seconds(error: HTTPError, maximum: float = 5.0) -> float | None:
    value = error.headers.get("Retry-After") if error.headers else None
    if value is None:
        return None
    try:
        delay = float(value.strip())
    except (AttributeError, ValueError):
        return None
    if delay < 0:
        return None
    return min(delay, maximum)


def _retryable_http(error: HTTPError) -> bool:
    return error.code == 429 or 500 <= error.code <= 599


def load_json(
    request,
    timeout,
    *,
    max_attempts: int = 2,
    retry_delay: float = 1.0,
    max_retry_after: float = 5.0,
):
    if max_attempts < 1:
        raise ValueError("max_attempts must be positive")
    parsed = urlsplit(request.full_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Only HTTP and HTTPS URLs are supported")
    path = urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
    connection_type = (
        IPv4HTTPSConnection if parsed.scheme == "https" else IPv4HTTPConnection
    )
    last_error = None
    for attempt in range(max_attempts):
        connection = connection_type(
            parsed.hostname,
            parsed.port or (443 if parsed.scheme == "https" else 80),
            timeout=timeout,
        )
        try:
            connection.request(
                getattr(request, "method", None) or request.get_method() or "GET",
                path,
                body=request.data,
                headers=dict(request.header_items()),
            )
            response = connection.getresponse()
            body = response.read()
            if response.status >= 400:
                raise HTTPError(
                    request.full_url,
                    response.status,
                    response.reason,
                    response.headers,
                    io.BytesIO(body),
                )
            return json.loads(body)
        except HTTPError as error:
            last_error = error
            retryable = _retryable_http(error)
            if not retryable or attempt + 1 >= max_attempts:
                raise
            delay = _retry_after_seconds(error, max_retry_after)
            time.sleep(retry_delay if delay is None else delay)
        except (TimeoutError, socket.timeout, ConnectionError, OSError) as error:
            last_error = error
            if attempt + 1 >= max_attempts:
                raise
            time.sleep(retry_delay)
        finally:
            connection.close()
    raise last_error  # pragma: no cover
