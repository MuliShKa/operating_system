"""Line-delimited JSON request/response over a Unix domain socket.

The socket is local to one Linux host. Each client connection sends one JSON
object and receives one JSON response before the connection closes.
"""

import json
import socket
import threading
from collections.abc import Callable
from pathlib import Path

Message = dict[str, object]
MessageHandler = Callable[[Message], Message]
CLIENT_TIMEOUT_S = 1.0  # Do not let a silent client block the server forever.
ACCEPT_TIMEOUT_S = 0.1  # Wake the server periodically so it can notice shutdown.


class UnixMessageServer:
    """Serve one request at a time by calling the supplied message handler."""

    def __init__(self, path: str | Path, handler: MessageHandler) -> None:
        """Save the socket path and handler; the socket starts in start()."""
        self.path = Path(path)
        self.handler = handler
        self._socket: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._running = threading.Event()

    def start(self) -> None:
        """Create the local socket file and start its background server thread."""
        if not hasattr(socket, "AF_UNIX"):
            raise OSError("Unix domain sockets are not supported on this platform")
        # Make sure the parent folder exists before binding the socket path.
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Remove a stale file that may remain after an unclean previous exit.
        self.path.unlink(missing_ok=True)

        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(self.path))
        server.listen()
        server.settimeout(ACCEPT_TIMEOUT_S)
        self._socket = server
        self._running.set()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def close(self) -> None:
        """Stop accepting requests, close resources, and remove the socket file."""
        self._running.clear()
        if self._thread is not None:
            # Wait for the server loop to leave accept() before closing its socket.
            self._thread.join()
            self._thread = None
        if self._socket is not None:
            self._socket.close()
            self._socket = None
        self.path.unlink(missing_ok=True)

    def _serve(self) -> None:
        """Accept clients until close() clears the running event."""
        assert self._socket is not None
        while self._running.is_set():
            try:
                connection, _ = self._socket.accept()
            except socket.timeout:
                continue
            except OSError:
                if self._running.is_set():
                    raise
                break

            with connection:
                connection.settimeout(CLIENT_TIMEOUT_S)
                self._handle(connection)

    def _handle(self, connection: socket.socket) -> None:
        """Decode one request, call the handler, and send one response line."""
        try:
            request = json.loads(_read_line(connection))
            if not isinstance(request, dict):
                raise ValueError("request must be a JSON object")
            response = self.handler(request)
        except (ConnectionError, OSError, ValueError, json.JSONDecodeError) as error:
            # Return a useful error to the client without stopping the server loop.
            response = {"error": str(error)}

        try:
            connection.sendall(_to_line(response))
        except OSError:
            pass

    def __enter__(self) -> "UnixMessageServer":
        """Allow the server to be started and stopped with a with statement."""
        self.start()
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        """Always close the socket when its with block ends."""
        self.close()


class UnixMessageClient:
    """Send one JSON request and return its JSON response."""

    def __init__(self, path: str | Path, timeout: float = CLIENT_TIMEOUT_S) -> None:
        """Store the server path and maximum time allowed for a request."""
        self.path = str(path)
        self.timeout = timeout

    def request(self, message: Message) -> Message:
        """Connect, send one request line, read one response line, then disconnect."""
        if not hasattr(socket, "AF_UNIX"):
            raise OSError("Unix domain sockets are not supported on this platform")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(self.timeout)
            connection.connect(self.path)
            connection.sendall(_to_line(message))
            response = json.loads(_read_line(connection))
        if not isinstance(response, dict):
            raise ValueError("response must be a JSON object")
        return response


def _to_line(message: Message) -> bytes:
    """Encode a JSON object as UTF-8 with a newline message boundary."""
    return (json.dumps(message, separators=(",", ":")) + "\n").encode("utf-8")


def _read_line(connection: socket.socket) -> bytes:
    """Read one complete message; fail if the peer closes before sending it."""
    with connection.makefile("rb") as reader:
        line = reader.readline()
    if not line:
        raise ConnectionError("connection closed before a complete message")
    return line