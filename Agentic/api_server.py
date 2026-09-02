"""
Mock REST API Server for FinTech Transaction Feed & Exchange Rates.
Generates dynamic live transaction feeds on every request with realistic data streams,
field renames, live data degradations, and exchange rate endpoints.
"""

from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import random
import socket
import sys
import urllib.parse
from datetime import datetime, timedelta, timezone

DEFAULT_PORT = 8585


def find_available_port(start_port=DEFAULT_PORT):
    for port in range(start_port, start_port + 50):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", port))
                return port
        except OSError:
            continue
    return start_port


PORT = find_available_port()


def generate_dynamic_transactions(count=6):
    """
    Generates dynamic real-time transaction records with random amounts, IDs, timestamps,
    and live data degradations (field renames, null merchants, malformed timestamps).
    """
    merchants = ["Amazon", "Swiggy", "Uber", "Starbucks Coffee", "Flipkart", "Netflix", "Walmart", "Target"]
    currencies = ["USD", "INR", "EUR", "GBP"]
    transactions = []
    now = datetime.now(timezone.utc)

    for i in range(1, count + 1):
        txn_id = f"TXN_{random.randint(10000, 99999)}"
        amount = round(random.uniform(15.0, 850.0), 2)
        currency = random.choice(currencies)
        merchant = random.choice(merchants)
        ts = (now - timedelta(minutes=random.randint(1, 180))).isoformat()

        # Alternate record structure & chaos types
        chaos_type = random.choice(["standard", "renamed_fields", "renamed_fields", "null_merchant", "malformed_ts"])

        if chaos_type == "renamed_fields":
            transactions.append(
                {
                    "tx_id": txn_id,
                    "txn_amt": amount,
                    "currency": currency,
                    "vendor": merchant,
                    "ts": ts,
                }
            )
        elif chaos_type == "null_merchant":
            transactions.append(
                {
                    "id": txn_id,
                    "amount": amount,
                    "currency": currency,
                    "merchant_name": random.choice(["null", None, "N/A", "undefined"]),
                    "timestamp": ts,
                }
            )
        elif chaos_type == "malformed_ts":
            transactions.append(
                {
                    "id": txn_id,
                    "amount": amount,
                    "currency": currency,
                    "merchant_name": merchant,
                    "timestamp": "invalid_date_str_999",
                }
            )
        else:
            transactions.append(
                {
                    "id": txn_id,
                    "amount": amount,
                    "currency": currency,
                    "merchant_name": merchant,
                    "timestamp": ts,
                }
            )

    return transactions


class MockAPIHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        sys.stdout.write(f"[API SERVER] {self.command} {self.path} -> {args[0]}\n")

    def _send_json(self, status_code: int, data: dict):
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def do_GET(self):
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path
        query_params = urllib.parse.parse_qs(parsed_url.query)

        # Endpoint 1: /v1/transactions (Dynamic Live Transaction Feed)
        if path == "/v1/transactions":
            page = query_params.get("page", ["1"])[0]
            if page == "1":
                transactions = generate_dynamic_transactions(count=6)
                self._send_json(200, {"transactions": transactions, "page": 1, "total_pages": 2, "timestamp": datetime.now(timezone.utc).isoformat()})
            elif page == "2":
                transactions = generate_dynamic_transactions(count=3)
                self._send_json(200, {"transactions": transactions, "page": 2, "total_pages": 2, "timestamp": datetime.now(timezone.utc).isoformat()})
            else:
                self._send_json(200, {"transactions": [], "page": int(page), "total_pages": 2})

        # Endpoint 2: /v1/exchange-rates (Query Param endpoint)
        elif path in ["/v1/exchange-rates", "/v1/rate"]:
            base = query_params.get("base", ["USD"])[0].upper()
            # Fluctuate rates slightly for live realism
            usd_base = 84.0 + round(random.uniform(-0.5, 0.5), 2)
            eur_base = 91.0 + round(random.uniform(-0.5, 0.5), 2)
            gbp_base = 107.0 + round(random.uniform(-0.5, 0.5), 2)
            rate_map = {"USD": usd_base, "EUR": eur_base, "GBP": gbp_base, "JPY": 0.56, "INR": 1.0}
            rate = rate_map.get(base, 1.0)
            self._send_json(
                200,
                {
                    "base": base,
                    "target": "INR",
                    "rate": rate,
                    "status": "active",
                    "stale_data": False,
                    "auxiliary_metadata": {"server": "node_01", "live_timestamp": datetime.now(timezone.utc).isoformat()},
                },
            )

        # Endpoint 3: /v1/rates/latest/{currency} (Path-based endpoint)
        elif path.startswith("/v1/rates/latest/"):
            base = path.split("/")[-1].upper()
            usd_base = 84.0 + round(random.uniform(-0.5, 0.5), 2)
            eur_base = 91.0 + round(random.uniform(-0.5, 0.5), 2)
            gbp_base = 107.0 + round(random.uniform(-0.5, 0.5), 2)
            rate_map = {"USD": usd_base, "EUR": eur_base, "GBP": gbp_base, "JPY": 0.56, "INR": 1.0}
            rate = rate_map.get(base, 1.0)
            self._send_json(
                200,
                {
                    "result": "success",
                    "base_code": base,
                    "rates": {"INR": rate, "USD": 1.0 if base == "USD" else round(1.0 / rate, 4)},
                },
            )

        # Root / Health Check
        elif path in ["/", "/health"]:
            self._send_json(
                200,
                {
                    "status": "online",
                    "service": "Dynamic FinTech Mock Data API Stream",
                    "endpoints": {
                        "feed": f"http://127.0.0.1:{PORT}/v1/transactions",
                        "exchange_rate": f"http://127.0.0.1:{PORT}/v1/exchange-rates?base=USD&target=INR",
                        "path_rate": f"http://127.0.0.1:{PORT}/v1/rates/latest/USD",
                    },
                },
            )
        else:
            self._send_json(404, {"error": "Endpoint not found"})


def run_server(port=PORT):
    server_address = ("127.0.0.1", port)
    httpd = HTTPServer(server_address, MockAPIHandler)
    print("=" * 80)
    print(f"  Dynamic FinTech Live REST API Server started at http://127.0.0.1:{port}")
    print(f"    - Feed Endpoint:          http://127.0.0.1:{port}/v1/transactions")
    print(f"    - Exchange Rate Endpoint: http://127.0.0.1:{port}/v1/exchange-rates")
    print(f"    - Path Rate Endpoint:     http://127.0.0.1:{port}/v1/rates/latest/USD")
    print("=" * 80)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Mock API Server...")
        httpd.server_close()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else PORT
    run_server(port)
