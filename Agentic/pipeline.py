"""
FinTech Data Ingestion & Normalization Pipeline.

Core Modules:
1. File I/O (Merchant Categories)
2. Feed Fetcher
3. Currency Normaliser
4. Merchant Enricher
5. Data Output & Process Pipeline (NormalizedTransaction)
"""

import json
import logging
from typing import Any, Dict, List, Optional
import requests
from pydantic import BaseModel, Field

from resilient_orchestrator import ResilientOrchestrator, SchemaInspector
from scamshield_classifier import ScamShieldClassifier, ThreatLevel, classify_scamshield_transaction

# Configure logging
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


# -----------------------------------------------------------------------------
# Module 1: File I/O (Merchant Categories)
# -----------------------------------------------------------------------------
def load_merchant_categories(file_path: str = "merchant_categories.json") -> Dict[str, str]:
    """
    Load static local file containing raw merchant names mapped to broad categories.
    
    :param file_path: Path to merchant categories JSON file.
    :return: Dictionary mapping merchant names to categories.
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
            logger.warning("Merchant categories file content is not a JSON object. Defaulting to empty map.")
            return {}
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.warning(f"Failed to load merchant categories from '{file_path}': {e}. Defaulting to empty map.")
        return {}


def save_normalized_transactions(
    records: List[Dict[str, Any]],
    output_file_path: str = "normalized_transactions.json",
) -> bool:
    """
    Saves normalized transaction dictionary records to a local JSON file.

    :param records: List of normalized transaction dict records.
    :param output_file_path: Destination JSON file path.
    :return: True if successfully written, False on failure.
    """
    try:
        with open(output_file_path, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2)
        logger.info(f"Successfully saved {len(records)} normalized records to '{output_file_path}'.")
        return True
    except Exception as e:
        logger.error(f"Failed to save normalized records to '{output_file_path}': {e}")
        return False


# -----------------------------------------------------------------------------
# Module 2: Feed Fetcher
# -----------------------------------------------------------------------------
def fetch_transaction_page(
    page_num: int,
    base_url: str = "https://api.example.com/v1/transactions",
    api_key: Optional[str] = None,
    session: Optional[requests.Session] = None,
    timeout: float = 10.0,
) -> List[Dict[str, Any]]:
    """
    Authenticate and pull a page of transactions from a REST API endpoint.
    
    :param page_num: Page number to fetch.
    :param base_url: Base REST API URL.
    :param api_key: Optional API key for authentication.
    :param session: Optional requests.Session instance for connection pooling.
    :param timeout: Request timeout in seconds.
    :return: List of raw transaction records. Returns [] on empty page or missing/error data.
    """
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    params = {"page": page_num}
    requester = session if session is not None else requests

    try:
        response = requester.get(base_url, headers=headers, params=params, timeout=timeout)
        if response.status_code != 200:
            logger.warning(f"Feed API returned non-200 status code: {response.status_code}")
            return []

        payload = response.json()
        if not payload:
            return []

        # Extract transactions list handling multiple response structures (list root or enveloped list)
        if isinstance(payload, list):
            return payload
        elif isinstance(payload, dict):
            # Check common keys for transaction lists
            for key in ["data", "transactions", "items", "results"]:
                if key in payload and isinstance(payload[key], list):
                    return payload[key]
            logger.warning("Response JSON object does not contain a recognized transaction list field.")
            return []
        
        return []
    except (requests.RequestException, ValueError) as e:
        logger.error(f"Error fetching transaction page {page_num}: {e}")
        return []


# -----------------------------------------------------------------------------
# Module 3: Currency Normaliser
# -----------------------------------------------------------------------------
def normalize_currency(
    amount: float,
    currency: str,
    exchange_api_url: str = "https://open.er-api.com/v6/latest",
    session: Optional[requests.Session] = None,
    rate_cache: Optional[Dict[str, float]] = None,
    timeout: float = 10.0,
) -> float:
    """
    Check transaction currency. If 'INR', return amount as-is (rounded to 2 decimals).
    If not 'INR', make a network request to an exchange rate API to fetch conversion rate,
    multiply amount by rate, and round to 2 decimal places.
    
    :param amount: Original transaction amount.
    :param currency: Currency code (e.g., 'USD', 'EUR', 'INR').
    :param exchange_api_url: Base endpoint for public exchange rates.
    :param session: Optional requests.Session instance.
    :param rate_cache: Optional dict for caching conversion rates.
    :param timeout: Request timeout in seconds.
    :return: Normalized amount in INR rounded to 2 decimal places.
    """
    curr_upper = (currency or "INR").strip().upper()
    
    # If already INR, return amount rounded to 2 decimal places
    if curr_upper == "INR":
        return round(float(amount), 2)

    # Check in-memory cache if provided
    if rate_cache is not None and curr_upper in rate_cache:
        rate = rate_cache[curr_upper]
        return round(float(amount) * rate, 2)

    # Make network request to fetch exchange rate
    requester = session if session is not None else requests
    url = f"{exchange_api_url.rstrip('/')}/{curr_upper}"

    try:
        response = requester.get(url, timeout=timeout)
        response.raise_for_status()
        data = response.json()

        # Handle typical exchange rate API response schemas
        rates = data.get("rates") or data.get("conversion_rates") or {}
        inr_rate = rates.get("INR")

        if inr_rate is None:
            raise ValueError(f"INR rate not found in exchange rate response for currency '{curr_upper}'")

        rate_float = float(inr_rate)
        if rate_cache is not None:
            rate_cache[curr_upper] = rate_float

        converted_amount = float(amount) * rate_float
        return round(converted_amount, 2)

    except (requests.RequestException, ValueError, KeyError) as e:
        logger.error(f"Failed to fetch exchange rate for currency '{curr_upper}': {e}")
        raise RuntimeError(f"Currency conversion failed for currency '{curr_upper}': {e}") from e


# -----------------------------------------------------------------------------
# Module 4: Merchant Enricher
# -----------------------------------------------------------------------------
def enrich_merchant_category(
    merchant_name: Optional[str],
    categories_map: Dict[str, str],
) -> str:
    """
    Check raw merchant string against merchant_categories lookup map.
    Assigns correct category or falls back to 'Uncategorized'.
    
    :param merchant_name: Raw merchant string from transaction feed.
    :param categories_map: Mapping dictionary of merchant names to categories.
    :return: Category name string.
    """
    if not merchant_name or not isinstance(merchant_name, str):
        return "Uncategorized"

    cleaned_name = merchant_name.strip()
    if not cleaned_name:
        return "Uncategorized"

    # 1. Exact match lookup
    if cleaned_name in categories_map:
        return categories_map[cleaned_name]

    # 2. Case-insensitive exact match
    categories_lower = {k.lower(): v for k, v in categories_map.items()}
    if cleaned_name.lower() in categories_lower:
        return categories_lower[cleaned_name.lower()]

    # 3. Substring match (e.g. "Amazon.com Prime" -> "Amazon")
    for raw_merchant, category in categories_map.items():
        if raw_merchant.lower() in cleaned_name.lower():
            return category

    return "Uncategorized"


# -----------------------------------------------------------------------------
# Pydantic Model & Main Process Function
# -----------------------------------------------------------------------------
class NormalizedTransaction(BaseModel):
    """Strict Pydantic model for normalized transaction records."""
    transaction_id: str = Field(..., description="Unique identifier for the transaction")
    amount_inr: float = Field(..., description="Transaction amount normalized to INR")
    merchant_category: str = Field(..., description="Enriched merchant category")
    timestamp: str = Field(..., description="ISO or raw transaction timestamp string")


def process_transactions_page(
    page_num: int,
    base_url: str = "https://api.example.com/v1/transactions",
    categories_file: str = "merchant_categories.json",
    exchange_api_url: str = "https://open.er-api.com/v6/latest",
    api_key: Optional[str] = None,
    session: Optional[requests.Session] = None,
) -> List[Dict[str, Any]]:
    """
    Main ingestion pipeline process function.
    Connects to transaction feed, loads merchant categories, normalizes currency,
    enriches merchant metadata, validates via NormalizedTransaction Pydantic model,
    and returns a list of dictionaries.
    
    :param page_num: Page index to fetch.
    :param base_url: REST API endpoint for transactions.
    :param categories_file: Path to merchant categories JSON file.
    :param exchange_api_url: Endpoint for exchange rate API.
    :param api_key: Authentication API key.
    :param session: Optional HTTP session for requests reuse.
    :return: List of validated normalized transaction records dumped to dicts.
    """
    # Step 1: Load static merchant categories
    categories_map = load_merchant_categories(categories_file)

    # Step 2: Fetch transaction page
    raw_transactions = fetch_transaction_page(
        page_num=page_num,
        base_url=base_url,
        api_key=api_key,
        session=session,
    )

    # Rule: If empty page or missing data, immediately return []
    if not raw_transactions or not isinstance(raw_transactions, list):
        return []

    rate_cache: Dict[str, float] = {}
    normalized_records: List[Dict[str, Any]] = []

    for tx in raw_transactions:
        if not isinstance(tx, dict):
            continue

        # Extract transaction fields flexibly
        tx_id = str(tx.get("transaction_id") or tx.get("id") or tx.get("tx_id") or "")
        raw_amount = float(tx.get("amount", 0.0))
        currency = str(tx.get("currency", "INR"))
        raw_merchant = tx.get("merchant") or tx.get("merchant_name") or tx.get("raw_merchant")
        timestamp = str(tx.get("timestamp") or tx.get("date") or tx.get("created_at") or "")

        # Step 3: Normalize currency to INR
        amount_inr = normalize_currency(
            amount=raw_amount,
            currency=currency,
            exchange_api_url=exchange_api_url,
            session=session,
            rate_cache=rate_cache,
        )

        # Step 4: Enrich merchant category
        category = enrich_merchant_category(raw_merchant, categories_map)

        # Step 5: Validate with Pydantic model
        norm_model = NormalizedTransaction(
            transaction_id=tx_id,
            amount_inr=amount_inr,
            merchant_category=category,
            timestamp=timestamp,
        )

        # Dump to dictionary (Pydantic v2 model_dump with v1 fallback)
        if hasattr(norm_model, "model_dump"):
            record_dict = norm_model.model_dump()
        else:
            record_dict = norm_model.dict()

        normalized_records.append(record_dict)

    return normalized_records


if __name__ == "__main__":
    print("Pipeline module loaded successfully.")
