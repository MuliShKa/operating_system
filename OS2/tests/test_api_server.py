import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.request import urlopen

from edge.api_server import _handler
from edge.config import load_config


class PathwayMapEndpointTests(unittest.TestCase):
    def test_serves_attributed_pathway_geojson(self) -> None:
        server = ThreadingHTTPServer(
            ("127.0.0.1", 0), _handler(load_config(), sensor_queue=None)
        )
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            with urlopen(
                f"http://127.0.0.1:{server.server_port}/api/map", timeout=2
            ) as response:
                data = json.load(response)
                self.assertEqual(response.headers["Content-Type"], "application/geo+json")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.assertEqual(data["type"], "FeatureCollection")
        self.assertEqual(len(data["features"]), 390)
        self.assertEqual(
            data["metadata"]["copyright"], "© OpenStreetMap contributors"
        )
        self.assertEqual(
            data["metadata"]["license"], "Open Database License (ODbL) 1.0"
        )


if __name__ == "__main__":
    unittest.main()
