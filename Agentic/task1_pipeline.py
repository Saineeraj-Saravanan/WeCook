"""
Agent Colosseum Project - Task 1 FinTech Data Normalization Pipeline
"""

import json
from typing import Any, Dict, List, Union
from unittest.mock import patch
import requests
from pydantic import BaseModel


class NormalizedTransaction(BaseModel):
    transaction_id: str
    amount_inr: float
    merchant_category: str
    timestamp: str


def load_merchant_categories(filepath: str = "merchant_categories.json") -> Dict[str, Any]:
    """Load merchant categories mapping from a local JSON file."""
    try:
        with open(filepath, "r", encoding="utf-8") as file:
            return json.load(file)
    except Exception:
        return {}


def normalize_currency(amount: Any, currency: str, rate_api_url: str) -> float:
    """Normalize foreign transaction amount to INR using rate API endpoint."""
    if currency == "INR":
        return round(float(amount), 2)
    
    try:
        separator = "&" if "?" in rate_api_url else "?"
        url = f"{rate_api_url}{separator}base={currency}&target=INR"
        response = requests.get(url)
        res_json = response.json() if hasattr(response, "json") else {}
        
        rate = 1.0
        if isinstance(res_json, dict):
            rate = res_json.get("rate") or res_json.get("rates", {}).get("INR") or 1.0

        return round(float(amount) * float(rate), 2)
    except Exception:
        return round(float(amount), 2)


def enrich_merchant(merchant_name: str, categories_dict: Dict[str, Any]) -> str:
    """Map raw merchant string to broad category label."""
    if not merchant_name:
        return "Unknown/Other"
        
    m_lower = merchant_name.lower().strip()
    
    for category, merchants in categories_dict.items():
        if isinstance(merchants, list):
            if any(m_lower == m.lower() or m.lower() in m_lower for m in merchants):
                return category
        elif isinstance(merchants, str):
            if m_lower == category.lower() or category.lower() in m_lower:
                return merchants
                
    return "Unknown/Other"


def process_transaction_page(
    api_endpoint: str, 
    rate_api_url: str, 
    categories_dict: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """Fetch raw transaction page, normalize currency & category, validate with Pydantic."""
    try:
        response = requests.get(api_endpoint)
        status = getattr(response, "status_code", 200)
        if status != 200:
            return []
        payload = response.json() if hasattr(response, "json") else {}
    except Exception:
        return []

    if isinstance(payload, dict):
        data = payload.get("transactions") or payload.get("data") or []
    elif isinstance(payload, list):
        data = payload
    else:
        data = []

    if not data or not isinstance(data, list):
        return []

    normalized_records = []
    for txn in data:
        if not isinstance(txn, dict):
            continue
            
        txn_id = str(txn.get("id") or txn.get("transaction_id") or "")
        amount = txn.get("amount", 0)
        currency = str(txn.get("currency") or "INR")
        merchant_name = str(txn.get("merchant_name") or txn.get("merchant") or "")
        timestamp = str(txn.get("timestamp") or txn.get("date") or "")

        inr_amount = normalize_currency(amount, currency, rate_api_url)
        category = enrich_merchant(merchant_name, categories_dict)

        record = NormalizedTransaction(
            transaction_id=txn_id,
            amount_inr=inr_amount,
            merchant_category=category,
            timestamp=timestamp
        )

        if hasattr(record, "model_dump"):
            normalized_records.append(record.model_dump())
        else:
            normalized_records.append(record.dict())

    return normalized_records


if __name__ == "__main__":
    print("=" * 70)
    print("                 RUNNING VERIFICATION TEST SUITE                 ")
    print("=" * 70)

    # 1. Setup local JSON File
    print("\n[TEST 1] File I/O: Creating & loading 'merchant_categories.json'...")
    dummy_categories = {
        "Retail": ["AMZN Mktp", "Target", "Walmart"],
        "Subscriptions": ["Netflix", "Spotify"]
    }
    with open("merchant_categories.json", "w") as f:
        json.dump(dummy_categories, f)

    categories_dict = load_merchant_categories("merchant_categories.json")
    assert "Retail" in categories_dict and "Subscriptions" in categories_dict
    print("  -> Passed: Successfully loaded merchant category mappings.")

    # Mock Data Setup
    mock_feed_data = {
        "transactions": [
            {"id": "TXN_01", "amount": 1000, "currency": "INR", "merchant_name": "Target", "timestamp": "2026-09-02T10:00:00Z"},
            {"id": "TXN_02", "amount": 50, "currency": "USD", "merchant_name": "Netflix", "timestamp": "2026-09-02T11:00:00Z"}
        ]
    }
    mock_empty_data = {"transactions": []}
    mock_rate_data = {"rate": 84.50}

    test_empty = False

    def mocked_requests_get(url, *args, **kwargs):
        class MockResponse:
            def __init__(self, json_data, status_code=200):
                self._json_data = json_data
                self.status_code = status_code
            def json(self):
                return self._json_data
                
        if "feed_endpoint" in url:
            return MockResponse(mock_empty_data if test_empty else mock_feed_data)
        elif "rate_api" in url:
            return MockResponse(mock_rate_data)
        return MockResponse({})

    with patch('requests.get', side_effect=mocked_requests_get):
        # 2. Test Transaction Ingestion & Merchant Enrichment
        print("\n[TEST 2] Feed Fetcher & Merchant Enrichment:")
        test_empty = False
        results = process_transaction_page("http://feed_endpoint", "http://rate_api", categories_dict)
        assert len(results) == 2, f"Expected 2 records, got {len(results)}"
        assert results[0]["merchant_category"] == "Retail"
        assert results[1]["merchant_category"] == "Subscriptions"
        print("  -> Passed: Raw merchant strings ('Target', 'Netflix') mapped to categories ('Retail', 'Subscriptions').")

        # 3. Test Foreign Currency Conversion Math
        print("\n[TEST 3] Currency Normalization Math:")
        inr_tx1 = results[0]["amount_inr"]
        usd_tx2 = results[1]["amount_inr"]
        assert inr_tx1 == 1000.0, f"Expected 1000.0 INR, got {inr_tx1}"
        assert usd_tx2 == 4225.0, f"Expected 4225.0 INR (50 * 84.50), got {usd_tx2}"
        print(f"  -> Passed: INR transaction kept as {inr_tx1} INR.")
        print(f"  -> Passed: USD transaction converted (50 USD * 84.50 rate) -> {usd_tx2} INR.")

        # 4. Test Empty Page Handling (Strict Rule 1)
        print("\n[TEST 4] Feed Fetcher Empty Page Rule:")
        test_empty = True
        empty_results = process_transaction_page("http://feed_endpoint", "http://rate_api", categories_dict)
        assert empty_results == [], f"Expected [], got {empty_results}"
        print("  -> Passed: Empty feed response immediately returned [] without error or dummy data.")

        # 5. Test Pydantic Schema Validation
        print("\n[TEST 5] Pydantic Schema Validation (NormalizedTransaction):")
        for record in results:
            assert "transaction_id" in record
            assert "amount_inr" in record
            assert "merchant_category" in record
            assert "timestamp" in record
            assert isinstance(record["transaction_id"], str)
            assert isinstance(record["amount_inr"], float)
            assert isinstance(record["merchant_category"], str)
            assert isinstance(record["timestamp"], str)
        print("  -> Passed: All output records match NormalizedTransaction Pydantic schema.")

    print("\n" + "=" * 70)
    print("           All 5 verification tests passed successfully!         ")
    print("=" * 70 + "\n")
