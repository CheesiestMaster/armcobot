import asyncio
import time
import sys
from typing import Dict, Final, Tuple
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST, Gauge

# we are using pure asyncio here, not aiohttp, as we just need to check the first header line, and that the header is complete

if sys.version_info < (3, 5):
    raise RuntimeError("Python 3.5 or higher is required")

MAX_HEADER_BYTES: Final[int] = 16 * 1024
READ_TIMEOUT: Final[float] = 2.0
TIMEOUT_429_INTERVAL: Final[int] = 1  # Minimum seconds between requests per IP
CACHE_TIMEOUT: Final[int] = TIMEOUT_429_INTERVAL * 4
VERSION: Final[Tuple[int, int, int]] = (1,0,1)
VERSION_STRING: Final[str] = ".".join(map(str, VERSION))
SHARED_HEADERS: Final[bytes] = (
    b"Server: aioprom/" + VERSION_STRING.encode('ascii') + b"\r\n" +
    b"Cache-Control: no-store, no-cache, must-revalidate, proxy-revalidate\r\n" +
    b"Pragma: no-cache\r\n" +
    b"Expires: 0\r\n" +
    b"Connection: close\r\n"
)
CRLF: Final[bytes] = b"\r\n"
HDR_END: Final[bytes] = CRLF + CRLF
aioprom_info = Gauge("aioprom_info", "Information about the aioprom server", labelnames=['major', 'minor', 'patch', 'version'])
aioprom_info.labels(major=VERSION[0], minor=VERSION[1], patch=VERSION[2], version=VERSION_STRING).set(1) # standard _info gauge

# Track last request time per IP address
_last_seen: Dict[str, float] = {}

def itoa(value: int) -> bytes:
    return str(value).encode('ascii')

# Pre-computed error responses at module level
_ERROR_RESPONSES: Final[Dict[int, bytes]] = {}
retry_after = max(int(TIMEOUT_429_INTERVAL), 1)
for status_code, reason, extra_headers in [
    (400, b"Bad Request", b""),
    (405, b"Method Not Allowed", b"Allow: GET\r\n"),
    (429, b"Too Many Requests", b"Retry-After:" + itoa(retry_after) + CRLF),
    (431, b"Request Header Fields Too Large", b"")
]:
    body = reason + CRLF
    headers = (
        b"HTTP/1.1 " + itoa(status_code) + b" " + reason + CRLF +
        b"Content-Length:" + itoa(len(body)) + CRLF +
        b"Content-Type: text/plain\r\n" +
        SHARED_HEADERS +
        extra_headers +
        HDR_END
    )
    _ERROR_RESPONSES[status_code] = headers + body


FALLBACK_ERROR_RESPONSE: Final[bytes] = (
    b"HTTP/1.1 500 Internal Server Error\r\n" +
    SHARED_HEADERS +
    HDR_END
)

HDR_200_PREFIX: Final[bytes] = (
    b"HTTP/1.1 200 OK\r\n" +
    SHARED_HEADERS +
    b"Content-Type: " + CONTENT_TYPE_LATEST.encode('ascii') + CRLF +
    b"Content-Length: " # we don't know the length yet, but we can just append it and the HDR_END during the handler
)

async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    try:
        # Rate limiting: 1 request per TIMEOUT_429_INTERVAL seconds per IP
        peername = writer.get_extra_info('peername')[0]
        if peername:
            now = time.monotonic()
            last_time = _last_seen.get(peername, 0)
            if now - last_time < TIMEOUT_429_INTERVAL:
                await send_simple(writer, 429)
                return
            _last_seen[peername] = now
        
        try:
            data = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), timeout=READ_TIMEOUT)
        except asyncio.LimitOverrunError:
            await send_simple(writer, 431)
            return
        except (asyncio.IncompleteReadError, asyncio.TimeoutError):
            await send_simple(writer, 400)
            return
        if len(data) > MAX_HEADER_BYTES:
            await send_simple(writer, 431)
            return
        
        try:
            request_line = data.split(CRLF, 1)[0]
            method, path, version = request_line.split(b' ')
        except ValueError:
            await send_simple(writer, 400)
            return

        if version not in (b'HTTP/1.0', b'HTTP/1.1'):
            await send_simple(writer, 400)
            return
        
        if method != b'GET':
            await send_simple(writer, 405)
            return
        
        # we don't actually look at the path, we just always server metrics
        payload = generate_latest()
        
        headers = (
            HDR_200_PREFIX +
            itoa(len(payload)) +
            HDR_END
        )
        writer.write(headers)
        writer.write(payload)
        try:
            await writer.drain()
        except (ConnectionResetError, BrokenPipeError):
            return
        # the finally will close the writer
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        now = time.monotonic()
        old = []
        for peer, last_time in _last_seen.items():
            if now - last_time > CACHE_TIMEOUT:
                old.append(peer)
        for peer in old:
            del _last_seen[peer]

async def send_simple(writer: asyncio.StreamWriter, status_code: int):
    response = _ERROR_RESPONSES.get(status_code, FALLBACK_ERROR_RESPONSE)
    
    writer.write(response)
    try:
        await writer.drain()
    except (ConnectionResetError, BrokenPipeError):
        return
    # the finally will close the writer

async def start_server(host: str, port: int) -> None:
    server = await asyncio.start_server(handle_client, host, port, limit=MAX_HEADER_BYTES)
    await server.serve_forever()