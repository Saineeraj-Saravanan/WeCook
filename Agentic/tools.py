"""
ADK Tools for FinTech Data Ingestion & Normalization.
"""

import json
import logging
from typing import Any, Dict, List, Optional
import requests

from schemas import NormalizedTransaction
from resilient_orchestrator import ResilientOrchestrator

logger = logging.getLogger(__name__)


def load_merchant_categories(file_path: str = "merchant_categories.json") -> Dict[str, Any]:
    """
    Loads static local file containing raw merchant names mapped to broad categories.

    Args:
        file_path: Path to merchant categories JSON file.

    Returns:
        Dictionary mapping merchant names or category keys to broad categories.
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

    Args:
        records: List of normalized transaction dict records.
        output_file_path: Destination JSON file path.

    Returns:
        True if successfully written, False on failure.
    """
    try:
        with open(output_file_path, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2)
        logger.info(f"Successfully saved {len(records)} normalized records to '{output_file_path}'.")
        return True
    except Exception as e:
        logger.error(f"Failed to save normalized records to '{output_file_path}': {e}")
        return False


def fetch_transaction_page(
    page_num: int,
    base_url: str = "https://api.example.com/v1/transactions",
    api_key: Optional[str] = None,
    session: Optional[Any] = None,
    timeout: float = 10.0,
) -> List[Dict[str, Any]]:
    """
    Authenticates and pulls a page of transactions from a REST API endpoint.

    Args:
        page_num: Page index to fetch.
        base_url: Base REST API URL.
        api_key: Optional API key for authentication.
        session: Optional HTTP session for request pooling.
        timeout: Request timeout in seconds.

    Returns:
        List of raw transaction dictionary records. Returns [] on empty page or network/status errors.
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

        if isinstance(payload, list):
            return payload
        elif isinstance(payload, dict):
            for key in ["data", "transactions", "items", "results"]:
                if key in payload and isinstance(payload[key], list):
                    return payload[key]
            logger.warning("Response JSON object does not contain a recognized transaction list field.")
            return []

        return []
    except (requests.RequestException, ValueError) as e:
        logger.error(f"Error fetching transaction page {page_num}: {e}")
        return []


def normalize_currency(
    amount: float,
    currency: str,
    exchange_api_url: str = "https://open.er-api.com/v6/latest",
    session: Optional[Any] = None,
    rate_cache: Optional[Dict[str, float]] = None,
    timeout: float = 10.0,
) -> float:
    """
    Normalizes a monetary transaction amount to INR.
    If currency is INR, returns amount rounded to 2 decimal places.
    Otherwise, fetches rate from conversion rate API, converts amount, and rounds to 2 decimal places.

    Args:
        amount: Transaction amount value.
        currency: Currency code (e.g. 'USD', 'EUR', 'INR').
        exchange_api_url: Base exchange rate API URL.
        session: Optional HTTP session reuse.
        rate_cache: Optional in-memory rate lookup cache dict.
        timeout: Request timeout in seconds.

    Returns:
        Converted amount in INR rounded to 2 decimal places.
    """
    curr_upper = (currency or "INR").strip().upper()

    if curr_upper == "INR":
        return round(float(amount), 2)

    if rate_cache is not None and curr_upper in rate_cache:
        rate = rate_cache[curr_upper]
        return round(float(amount) * rate, 2)

    requester = session if session is not None else requests
    
    # Check if URL already has query parameters or requires path-based currency symbol
    if "?" in exchange_api_url:
        separator = "&" if "?" in exchange_api_url else "?"
        url = f"{exchange_api_url}{separator}base={curr_upper}&target=INR"
    else:
        url = f"{exchange_api_url.rstrip('/')}/{curr_upper}"

    try:
        response = requester.get(url, timeout=timeout)
        if response.status_code != 200:
            raise RuntimeError(f"Exchange rate API returned status {response.status_code}")

        data = response.json()
        inr_rate = None

        if isinstance(data, dict):
            inr_rate = data.get("rate")
            if inr_rate is None:
                rates = data.get("rates") or data.get("conversion_rates") or {}
                if isinstance(rates, dict):
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


def enrich_merchant_category(
    merchant_name: Optional[str],
    categories_map: Dict[str, Any],
) -> str:
    """
    Enriches raw merchant name to standardized category using broad categories mapping.

    Args:
        merchant_name: Raw merchant string from feed.
        categories_map: Dictionary mapping merchant names or category labels to values.

    Returns:
        Categorized category string, defaulting to 'Uncategorized' or 'Unknown/Other'.
    """
    if not merchant_name or not isinstance(merchant_name, str):
        return "Uncategorized"

    cleaned_name = merchant_name.strip()
    if not cleaned_name:
        return "Uncategorized"

    # Exact match lookup
    if cleaned_name in categories_map:
        val = categories_map[cleaned_name]
        return val if isinstance(val, str) else cleaned_name

    # Check category -> list mapping format (e.g. {"Retail": ["Target", "Walmart"]})
    m_lower = cleaned_name.lower()
    for cat, merchants in categories_map.items():
        if isinstance(merchants, list):
            if any(m_lower == str(m).lower() or str(m).lower() in m_lower for m in merchants if m):
                return cat
        elif isinstance(merchants, str):
            if m_lower == cat.lower() or cat.lower() in m_lower:
                return merchants

    # Case-insensitive & substring lookup
    for raw_merchant, category in categories_map.items():
        if isinstance(category, str) and raw_merchant.lower() in m_lower:
            return category

    return "Uncategorized"


def process_transactions_pipeline(
    page_num: int = 1,
    base_url: str = "https://api.example.com/v1/transactions",
    categories_file: str = "merchant_categories.json",
    exchange_api_url: str = "https://open.er-api.com/v6/latest",
    api_key: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    End-to-End automated transaction processing pipeline tool for ADK agents.
    Fetches raw feed, loads categories, normalizes foreign currencies to INR,
    enriches merchant categories, and validates via NormalizedTransaction schema.

    Args:
        page_num: Transaction feed page number.
        base_url: REST feed endpoint URL.
        categories_file: Path to categories JSON file.
        exchange_api_url: Base rate API endpoint.
        api_key: Feed authentication API key.

    Returns:
        List of validated normalized transaction dictionary objects.
    """
    categories_map = load_merchant_categories(categories_file)
    raw_transactions = fetch_transaction_page(
        page_num=page_num,
        base_url=base_url,
        api_key=api_key,
    )

    if not raw_transactions or not isinstance(raw_transactions, list):
        return []

    rate_cache: Dict[str, float] = {}
    normalized_records: List[Dict[str, Any]] = []

    for tx in raw_transactions:
        if not isinstance(tx, dict):
            continue

        tx_id = str(tx.get("transaction_id") or tx.get("id") or tx.get("tx_id") or "")
        raw_amount = float(tx.get("amount", 0.0))
        currency = str(tx.get("currency") or "INR")
        raw_merchant = tx.get("merchant") or tx.get("merchant_name") or tx.get("raw_merchant")
        timestamp = str(tx.get("timestamp") or tx.get("date") or tx.get("created_at") or "")

        amount_inr = normalize_currency(
            amount=raw_amount,
            currency=currency,
            exchange_api_url=exchange_api_url,
            rate_cache=rate_cache,
        )

        category = enrich_merchant_category(raw_merchant, categories_map)

        norm_model = NormalizedTransaction(
            transaction_id=tx_id,
            amount_inr=amount_inr,
            merchant_category=category,
            timestamp=timestamp,
        )

        if hasattr(norm_model, "model_dump"):
            record_dict = norm_model.model_dump()
        else:
            record_dict = norm_model.dict()

        normalized_records.append(record_dict)

    return normalized_records


def run_resilient_orchestrator(
    feed_url: str = "https://api.example.com/v1/transactions",
    rate_url: str = "https://open.er-api.com/v6/latest",
) -> List[Dict[str, Any]]:
    """
    Executes resilient ingestion pipeline to handle live data degradations, dynamic field renames,
    null/malformed records, and exchange rate responses with auxiliary/stale fields.

    Args:
        feed_url: Raw transaction feed URL.
        rate_url: Base currency exchange rate API URL.

    Returns:
        List of validated and normalized transaction records.
    """
    orchestrator = ResilientOrchestrator(feed_url=feed_url, rate_url=rate_url)
    return orchestrator.run_pipeline()


def analyze_transaction_risk(
    merchant_name: str,
    amount: float,
    currency: str = "INR",
    timestamp: str = "",
    transaction_id: str = "",
    categories_file: str = "merchant_categories.json",
) -> Dict[str, Any]:
    """
    Analyzes a transaction detail for financial risk, fraud indicators, currency conversion, and merchant authenticity.

    Args:
        merchant_name: Name of the merchant or recipient.
        amount: Transaction monetary amount.
        currency: Currency code (e.g. 'USD', 'INR', 'EUR').
        timestamp: Transaction timestamp string.
        transaction_id: Unique transaction ID string.
        categories_file: Path to merchant categories JSON file.

    Returns:
        Risk evaluation dictionary containing risk_level, summary, key_findings, and recommended_action.
    """
    categories_map = load_merchant_categories(categories_file)
    category = enrich_merchant_category(merchant_name, categories_map)

    amount_inr = amount
    conversion_note = "Amount already in INR."
    curr_clean = (currency or "INR").strip().upper()

    if curr_clean != "INR":
        try:
            amount_inr = normalize_currency(amount, curr_clean)
            conversion_note = f"Converted {amount} {curr_clean} -> {amount_inr} INR."
        except Exception as e:
            conversion_note = f"Failed currency conversion for {curr_clean}: {e}"

    risk_flags = []
    is_high_risk = False

    # 1. Merchant status check
    if category in ["Uncategorized", "Unknown/Other"]:
        risk_flags.append({"label": "Merchant Status", "detail": f"Unregistered in our trusted categories database (defaults to High-Risk/Unknown category)."})
        is_high_risk = True
    else:
        risk_flags.append({"label": "Merchant Status", "detail": f"Verified merchant registered under category '{category}'."})

    # 2. Currency conversion & anomaly check
    if curr_clean != "INR":
        risk_flags.append({"label": "Anomaly Detected", "detail": f"Sudden foreign currency conversion mismatch ({curr_clean}). {conversion_note}"})
        if amount_inr > 50000:
            is_high_risk = True
    else:
        risk_flags.append({"label": "Anomaly Detected", "detail": "Standard local currency transaction. No conversion anomaly detected."})

    # 3. Data integrity & timestamp check
    if not timestamp or "INVALID" in timestamp.upper():
        risk_flags.append({"label": "Data Integrity", "detail": "Flagged for suspicious or missing timestamp patterns."})
        is_high_risk = True
    else:
        risk_flags.append({"label": "Data Integrity", "detail": f"Timestamp verified ({timestamp})."})

    if is_high_risk:
        risk_level = "🔴 HIGH RISK / SCAM ALERT"
        summary = f"This transaction involves an unverified foreign entity ({merchant_name}) exhibiting high-risk payout claims."
        recommended_action = "Block Transaction. Do not authorize funds transfer or release details to this merchant."
    else:
        risk_level = "🟢 LOW RISK / VERIFIED"
        summary = f"This transaction with {merchant_name} for {amount_inr} INR exhibits standard patterns and is verified."
        recommended_action = "Approve Transaction. Process transfer normally."

    return {
        "risk_level": risk_level,
        "summary": summary,
        "key_findings": risk_flags,
        "recommended_action": recommended_action,
        "amount_inr": amount_inr,
        "merchant_category": category,
    }


def classify_scamshield_risk(
    merchant_name: str,
    amount: float,
    currency: str = "INR",
    note: str = "",
    timestamp: str = "",
    transaction_id: str = "",
) -> Dict[str, Any]:
    """
    Evaluates transaction record and raw note/memo metadata for the ScamShield fraud-detection agent.
    Emits clean, human-readable card summaries mapped to High Risk (red alert), Medium Risk (yellow warning), or Low Risk (green check).

    Args:
        merchant_name: Merchant name or recipient node.
        amount: Transaction monetary amount.
        currency: Transaction currency code (e.g. 'INR', 'USD', 'EUR').
        note: Raw memo/note/description text.
        timestamp: ISO timestamp string.
        transaction_id: Unique transaction ID.

    Returns:
        ScamShield report dictionary containing threat_level, header, summary, key_findings, recommended_action, and formatted_card.
    """
    from scamshield_classifier import default_classifier
    categories_map = load_merchant_categories()
    category = enrich_merchant_category(merchant_name, categories_map)

    amount_inr = amount
    if (currency or "INR").strip().upper() != "INR":
        try:
            amount_inr = normalize_currency(amount, currency)
        except Exception:
            amount_inr = amount

    tx_dict = {
        "transaction_id": transaction_id,
        "merchant_name": merchant_name,
        "amount_inr": amount_inr,
        "currency": currency,
        "merchant_category": category,
        "timestamp": timestamp,
    }
    return default_classifier.evaluate_transaction(tx_dict, note=note)
