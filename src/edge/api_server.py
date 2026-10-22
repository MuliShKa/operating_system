from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


# Find the project's root directory.
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Directory containing the HTML dashboard.
WEB_ROOT = PROJECT_ROOT / "src" / "ui" / "static"


class DashboardHandler(SimpleHTTPRequestHandler):
    """Serve the dashboard's static files."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_ROOT), **kwargs)


def main():
    host = "127.0.0.1"
    port = 8000

    server = ThreadingHTTPServer((host, port), DashboardHandler)

    print(f"Dashboard available at http://{host}:{port}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping dashboard...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()