"""
OS1-1: download the building footprints around the node from VWorld, once,
and write them to the local cache read by edge.inventory.

The node itself never goes online for this: run it by hand (or before a demo)
while the WAN is available.

Needs:
  VWORLD_API_KEY   your VWorld API key (https://www.vworld.kr, 인증키 발급)
  vworld_layer     the building layer ID, set in config/node.yaml (or VWORLD_LAYER)
  VWORLD_DOMAIN    the domain registered with the key, if VWorld asks for one

Run: PYTHONPATH=src python -m edge.vworld_fetch

Not tested against the live API (no key in the project). The request follows the
VWorld 2D data API (service=data, request=GetFeature); check the parameters in
the VWorld developer guide if the call is refused.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date
from urllib.parse import urlencode
from urllib.request import urlopen

from edge.node_config import INVENTORY, LATITUDE, LONGITUDE, PROJECT_DIR

API_URL = "https://api.vworld.kr/req/data"


def build_url(key: str, layer: str, radius: float, domain: str | None) -> str:
    box = (LONGITUDE - radius, LATITUDE - radius, LONGITUDE + radius, LATITUDE + radius)
    params = {
        "service": "data",
        "request": "GetFeature",
        "data": layer,
        "key": key,
        "format": "json",
        "crs": "EPSG:4326",
        "geomFilter": "BOX({:.6f},{:.6f},{:.6f},{:.6f})".format(*box),
        "size": 1000,
        "page": 1,
    }
    if domain:
        params["domain"] = domain
    return f"{API_URL}?{urlencode(params)}"


def main() -> int:
    key = os.environ.get("VWORLD_API_KEY")
    layer = os.environ.get("VWORLD_LAYER") or INVENTORY.get("vworld_layer")
    if not key:
        print("Set VWORLD_API_KEY first (never commit the key).", file=sys.stderr)
        return 2
    if not layer:
        print("Set inventory.vworld_layer in config/node.yaml (or VWORLD_LAYER).", file=sys.stderr)
        return 2

    url = build_url(key, layer, float(INVENTORY["fetch_radius_deg"]), os.environ.get("VWORLD_DOMAIN"))
    with urlopen(url, timeout=30) as response:
        reply = json.load(response)

    body = reply.get("response", {})
    if body.get("status") != "OK":
        print(f"VWorld refused the request: {json.dumps(body.get('error') or body)[:500]}", file=sys.stderr)
        return 1

    collection = body["result"]["featureCollection"]
    collection["metadata"] = {
        "source": f"VWorld 2D data API, layer {layer}",
        "retrieved_at": date.today().isoformat(),
        "node": f"({LATITUDE}, {LONGITUDE})",
    }
    target = PROJECT_DIR / INVENTORY["cache"]
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(".partial")
    partial.write_text(json.dumps(collection, ensure_ascii=False), encoding="utf-8")
    partial.rename(target)
    print(f"Cached {len(collection.get('features', []))} features in {target}")
    print("Now fill retrieved_at and status in sources/source_registry.csv.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
