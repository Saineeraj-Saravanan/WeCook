"""
Live API Server & Resilient Orchestrator End-to-End Demo.
"""

import json
import threading
import time
import requests

from api_server import PORT, run_server
from resilient_orchestrator import ResilientOrchestrator


def start_server_in_thread():
    server_thread = threading.Thread(target=run_server, kwargs={"port": PORT}, daemon=True)
    server_thread.start()
    time.sleep(1.0)  # Allow server to bind port


def main():
    print("\n[1] Starting Local FinTech Mock REST API Server...")
    start_server_in_thread()

    feed_url = f"http://127.0.0.1:{PORT}/v1/transactions"
    rate_url = f"http://127.0.0.1:{PORT}/v1/exchange-rates"

    print("\n[2] Connecting ResilientOrchestrator to Live API Endpoints:")
    print(f"    Feed URL: {feed_url}")
    print(f"    Rate URL: {rate_url}")

    orchestrator = ResilientOrchestrator(feed_url=feed_url, rate_url=rate_url)

    print("\n[3] Ingesting Live Data Stream & Resolving Degraded Records...")
    results = orchestrator.run_pipeline()

    print("\n" + "=" * 80)
    print(f"  SUCCESSFULLY INGESTED & NORMALIZED {len(results)} VALID RECORDS!")
    print("=" * 80)
    for idx, rec in enumerate(results, 1):
        print(f"\nRecord {idx}:")
        print(json.dumps(rec, indent=2))
    print("\n" + "=" * 80 + "\n")


if __name__ == "__main__":
    main()
