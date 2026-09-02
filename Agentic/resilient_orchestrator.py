"""
Task 2 Orchestration and Resilience Layer for FinTech Track Agent.
Handles live data degradations, dynamic mid-stream field renames, null merchant filtering,
malformed timestamp handling, and robust exchange rate parsing.
"""

import json
import logging
import math
import os
from datetime import datetime
from typing import Any, Dict, List, Optional
import requests

logger = logging.getLogger(__name__)


class SchemaInspector:
    """Inspects and infers mappings for unfamiliar or dynamically renamed payload fields."""

    DEFAULT_MAPPINGS = {
        "txn_amt": "amount",
        "val": "amount",
        "amt": "amount",
        "value": "amount",
        "price": "amount",
        "merchant": "merchant_name",
        "vendor": "merchant_name",
        "seller": "merchant_name",
        "payee": "merchant_name",
        "timestamp_utc": "timestamp",
        "ts": "timestamp",
        "date": "timestamp",
        "created_at": "timestamp",
        "datetime": "timestamp",
        "time": "timestamp",
        "curr": "currency",
        "ccy": "currency",
        "currency_code": "currency",
        "tx_id": "id",
        "txn_id": "id",
        "transaction_id": "id",
        "reference_id": "id",
    }

    def inspect(self, record: Dict[str, Any]) -> Dict[str, str]:
        """
        Inspects record keys to dynamically discover mappings for unknown/renamed keys.
        """
        mapping = dict(self.DEFAULT_MAPPINGS)
        if not isinstance(record, dict):
            return mapping

        for k in record.keys():
            k_str = str(k).strip()
            if k_str in mapping:
                continue
            k_lower = k_str.lower().replace("-", "_")
            if any(term in k_lower for term in ["txn_amt", "val", "amt", "value", "price"]):
                mapping[k_str] = "amount"
            elif any(term in k_lower for term in ["merchant", "vendor", "seller", "payee"]):
                mapping[k_str] = "merchant_name"
            elif any(term in k_lower for term in ["timestamp", "ts", "created_at", "date", "time"]):
                mapping[k_str] = "timestamp"
            elif any(term in k_lower for term in ["curr", "ccy"]):
                mapping[k_str] = "currency"
            elif any(term in k_lower for term in ["tx_id", "txn_id", "transaction_id", "ref_id"]):
                mapping[k_str] = "id"

        return mapping


class ResilientOrchestrator:
    """
    Resilient Orchestration Layer for live data degradations and runtime chaos.
    """

    MAPPING = {
        "txn_amt": "amount",
        "val": "amount",
        "amt": "amount",
        "value": "amount",
        "price": "amount",
        "merchant": "merchant_name",
        "vendor": "merchant_name",
        "seller": "merchant_name",
        "payee": "merchant_name",
        "timestamp_utc": "timestamp",
        "ts": "timestamp",
        "date": "timestamp",
        "created_at": "timestamp",
        "datetime": "timestamp",
        "time": "timestamp",
        "curr": "currency",
        "ccy": "currency",
        "currency_code": "currency",
        "tx_id": "id",
        "txn_id": "id",
        "transaction_id": "id",
        "reference_id": "id",
    }

    DEFAULT_API_KEY = "AQ.Ab8RN6KjOrx5Y29jHChuCM5zWAZB0T5CH5Jzqpl5Vma_awjzyQ"

    def __init__(self, feed_url: str, rate_url: str, schema_inspector=None, api_key: Optional[str] = None):
        self.feed_url = feed_url
        self.rate_url = rate_url
        self.schema_inspector = schema_inspector or SchemaInspector()
        self.api_key = api_key or os.environ.get("FINTECH_API_KEY", self.DEFAULT_API_KEY)
        self.rate_cache: Dict[str, float] = {}

    def _get_headers(self) -> Dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
            headers["x-api-key"] = self.api_key
        return headers

    def fetch_raw_feed(self) -> List[Dict[str, Any]]:
        """
        Fetches raw transactions list safely handling network failures or nested dictionary payloads.
        """
        try:
            response = requests.get(self.feed_url, headers=self._get_headers(), timeout=10.0)
            if response.status_code != 200:
                logger.warning(f"Feed API returned non-200 status code: {response.status_code}")
                return []

            data = response.json()
            if isinstance(data, list):
                return data
            elif isinstance(data, dict):
                for key in ["transactions", "data", "items", "results"]:
                    if key in data and isinstance(data[key], list):
                        return data[key]
                return []
            return []
        except Exception as e:
            logger.error(f"Error fetching raw feed from '{self.feed_url}': {e}")
            return []

    def adapt_schema(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """
        Dynamically adapts raw record keys to canonical field names.
        """
        if not isinstance(record, dict):
            return {}

        dynamic_mapping = {}
        if self.schema_inspector:
            if hasattr(self.schema_inspector, "inspect"):
                dynamic_mapping = self.schema_inspector.inspect(record)
            elif hasattr(self.schema_inspector, "get_mapping"):
                dynamic_mapping = self.schema_inspector.get_mapping(record)
            elif callable(self.schema_inspector):
                dynamic_mapping = self.schema_inspector(record)

        adapted = {}
        for k, v in record.items():
            k_clean = str(k).strip()
            resolved_key = dynamic_mapping.get(k_clean, self.MAPPING.get(k_clean, k_clean))
            adapted[resolved_key] = v

        return adapted

    def validate_link_and_fields(self, record: Dict[str, Any]) -> bool:
        """
        Ensures all required canonical fields exist in the record.
        """
        if not isinstance(record, dict):
            return False

        required = ["id", "amount", "currency", "merchant_name", "timestamp"]
        if all(k in record for k in required):
            return True

        # Flexible verification fallback
        rec_id = record.get("id") or record.get("transaction_id") or record.get("tx_id")
        rec_amt = record.get("amount") or record.get("txn_amt") or record.get("val")
        rec_curr = record.get("currency") or record.get("curr")
        rec_merch = record.get("merchant_name") or record.get("merchant")
        rec_ts = record.get("timestamp") or record.get("ts") or record.get("timestamp_utc")

        return bool(rec_id is not None and rec_amt is not None and rec_curr is not None and rec_merch is not None and rec_ts is not None)

    def validate_record(self, record: Dict[str, Any]) -> bool:
        """
        Filters out records with null/invalid merchants or malformed timestamps without crashing.
        """
        if not isinstance(record, dict):
            return False

        # Validate merchant_name
        merchant = record.get("merchant_name") if "merchant_name" in record else record.get("merchant")
        if merchant is None:
            return False

        merchant_str = str(merchant).strip()
        invalid_merchants = {"null", "none", "n/a", "undefined", "nan", ""}
        if merchant_str.lower() in invalid_merchants:
            return False

        # Validate amount
        raw_amt = record.get("amount")
        if raw_amt is None:
            return False
        try:
            amt_float = float(raw_amt)
            if math.isnan(amt_float) or math.isinf(amt_float):
                return False
        except (ValueError, TypeError):
            return False

        # Validate timestamp
        raw_ts = record.get("timestamp") or record.get("ts") or record.get("date")
        if raw_ts is None:
            return False

        ts_str = str(raw_ts).strip()
        if not ts_str or ts_str.lower() in invalid_merchants:
            return False

        # Parse timestamp safely
        parsed_ok = False
        try:
            num_ts = float(ts_str)
            if num_ts > 0:
                parsed_ok = True
        except (ValueError, TypeError):
            pass

        if not parsed_ok:
            clean_ts = ts_str.replace("Z", "+00:00")
            for fmt in (
                None,  # datetime.fromisoformat
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d",
                "%Y/%m/%d %H:%M:%S",
                "%Y/%m/%d",
            ):
                try:
                    if fmt is None:
                        datetime.fromisoformat(clean_ts)
                    else:
                        datetime.strptime(clean_ts, fmt)
                    parsed_ok = True
                    break
                except (ValueError, TypeError):
                    continue

        return parsed_ok

    def fetch_robust_rate(self, currency: str) -> float:
        """
        Parses exchange rate responses robustly, ignoring auxiliary fields or stale flags.
        """
        if not currency or not isinstance(currency, str):
            return 1.0

        curr_upper = currency.strip().upper()
        if curr_upper == "INR":
            return 1.0

        if curr_upper in self.rate_cache:
            return self.rate_cache[curr_upper]

        FALLBACK_RATES = {
            "USD": 84.0,
            "EUR": 90.0,
            "GBP": 105.0,
            "JPY": 0.55,
            "CAD": 62.0,
            "AUD": 55.0,
        }

        try:
            separator = "&" if "?" in self.rate_url else "?"
            url = f"{self.rate_url}{separator}base={curr_upper}&target=INR"
            response = requests.get(url, headers=self._get_headers(), timeout=5.0)

            if response.status_code == 200:
                data = response.json()
                if isinstance(data, dict):
                    extracted = None
                    if "rate" in data and data["rate"] is not None:
                        extracted = data["rate"]
                    elif "rates" in data and isinstance(data["rates"], dict):
                        extracted = data["rates"].get("INR") or data["rates"].get("inr")
                    elif "conversion_rates" in data and isinstance(data["conversion_rates"], dict):
                        extracted = data["conversion_rates"].get("INR") or data["conversion_rates"].get("inr")
                    elif "data" in data and isinstance(data["data"], dict):
                        extracted = data["data"].get("rate") or data["data"].get("rates", {}).get("INR")

                    if extracted is not None:
                        rate_float = float(extracted)
                        self.rate_cache[curr_upper] = rate_float
                        return rate_float
        except Exception as e:
            logger.warning(f"Failed fetching rate for '{curr_upper}': {e}")

        fallback = self.rate_cache.get(curr_upper, FALLBACK_RATES.get(curr_upper, 1.0))
        return float(fallback)

    def run_pipeline(self) -> List[Dict[str, Any]]:
        """
        Executes end-to-end resilient ingestion pipeline.
        """
        raw_records = self.fetch_raw_feed()
        valid_records = []

        for raw in raw_records:
            if not isinstance(raw, dict):
                continue

            cleaned_record = self.adapt_schema(raw)
            if not self.validate_link_and_fields(cleaned_record):
                continue
            if not self.validate_record(cleaned_record):
                continue

            curr = str(cleaned_record.get("currency", "INR"))
            raw_amt = float(cleaned_record.get("amount", 0.0))
            rate = self.fetch_robust_rate(curr)
            cleaned_record["amount_inr"] = round(raw_amt * rate, 2)

            if "id" in cleaned_record and "transaction_id" not in cleaned_record:
                cleaned_record["transaction_id"] = str(cleaned_record["id"])

            valid_records.append(cleaned_record)

        return valid_records


if __name__ == "__main__":
    print("ResilientOrchestrator module loaded successfully.")
