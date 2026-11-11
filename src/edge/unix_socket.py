import json
import os
import socket
import threading
from collections.abc import Callable
from pathlib import Path

# A client gets this long to send its question. Without it, a client that
# connects and sends nothing would block the server forever.
CLIENT_TIMEOUT_S = 0.5

class UnixSocketServer:
    """
    Answers questions from other processes through a Unix domain socket.

    A Unix socket is a file on disk that two local processes connect to.
    Each message is one line of JSON. One connection = one question + one answer.
    The questions are answered in a background thread.
    """

    def __init__(self, path: str | Path, handler: Callable[[dict], dict]) -> None:

        # The path is the socket file that clients connect to.
        self.path = str(path)

        # The handler is a function: it receives the question (a dict) and returns the answer (a dict).
        self.handler = handler

        # The socket is created here, so start() can only be called once.
        self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

        # The thread runs serve() in the background. daemon=True: it does not keep the program alive.
        self._thread = threading.Thread(target=self.serve, daemon=True)

        # The running flag tells serve() when to stop.
        self._running = False

    def start(self) -> None:
        """
        Create the socket file and start answering in the background thread.
        """

        folder = os.path.dirname(self.path)
        if folder:
            # bind() fails if the folder is missing.
            os.makedirs(folder, exist_ok=True)

        # A crashed run may have left the socket file behind.
        self.remove_socket_file()

        self._socket.bind(self.path)
        self._socket.listen()

        # accept() wakes up every 0.2 s so the thread can notice stop().
        self._socket.settimeout(0.2)

        self._running = True
        self._thread.start()

    def stop(self) -> None:
        """
        Stop the background thread, close the socket and remove the socket file.
        """

        self._running = False
        self._thread.join()
        self._socket.close()
        self.remove_socket_file()

    def serve(self) -> None:
        """
        Accept clients one by one and answer them, until stop() is called.

            accept()  --no client after 0.2 s-->  still running?  --yes-->  accept() again
               |                                       |
             client                                    no
               v                                       v
            answer(connection)                      leave the loop (stop() was called)
               |
            close the connection, back to accept()

        A client that connects and sends nothing would block answer() forever,
        so each connection gets CLIENT_TIMEOUT_S to send its question.
        """

        while self._running:
            try:
                connection, _ = self._socket.accept()
            except socket.timeout:
                continue
            connection.settimeout(CLIENT_TIMEOUT_S)
            with connection:
                self.answer(connection)

    def answer(self, connection: socket.socket) -> None:
        """
        Read one question, call the handler, and send back its answer.
        If anything goes wrong, send back {"error": ...} instead.
        """

        try:
            question = json.loads(read_line(connection))
            answer = self.handler(question)
        except Exception as error:
            # A bad question must not kill the server.
            answer = {"error": str(error)}

        try:
            connection.sendall(to_line(answer))
        except OSError:
            # The client already left: nobody to answer.
            pass

    def remove_socket_file(self) -> None:
        """
        Remove the socket file if it exists.
        """

        if os.path.exists(self.path):
            os.remove(self.path)


class UnixSocketClient:
    """
    Asks questions to a UnixSocketServer.
    """

    def __init__(self, path: str | Path, timeout: float = 1.0) -> None:

        # The path is the socket file of the server.
        self.path = str(path)

        # The timeout is how long to wait for the server before giving up.
        self.timeout = timeout

    def ask(self, question: dict) -> dict:
        """
        Send one question (dict) and return the answer (dict).

            Client (ask)                                Server (serve + answer)
            ------------                                -----------------------
            connect(path)          -------------->      accept()

            send {"cmd": "status"} -------------->      read_line(), json.loads() handler(question)

            read_line()            <--------------      send {"ok": true}

            json.loads(), return                        close the connection
        """

        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(self.timeout)
            connection.connect(self.path)
            connection.sendall(to_line(question))
            return json.loads(read_line(connection))


def to_line(message: dict) -> bytes:
    """
    Turn a dict into one line of JSON, ready to be sent.
    """

    return (json.dumps(message) + "\n").encode()


def read_line(connection: socket.socket) -> bytes:
    """
    Read one line from the connection.
    Raise ConnectionError if the other side closed before a full line.
    """

    with connection.makefile("rb") as reader:
        line = reader.readline()
    if not line:
        raise ConnectionError("connection closed before a full message")
    return line
