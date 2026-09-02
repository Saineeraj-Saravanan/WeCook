"""
ScamShield Fraud Classification & Formatted Reporting Module.

Evaluates normalized transactions and raw note/memo metadata across specific fraud indicators
and emits clean, human-readable card summaries mapped to three threat levels:
- High Risk (Red alert: unverified offshore entities, guaranteed yields, prompt injections)
- Medium Risk (Yellow warning: unknown nodes, high P2P amounts, urgent pressure language)
- Low Risk (Green check: verified categories, utility/subscription payments, normal amounts)
"""

from enum import Enum
import re
from typing import Any, Dict, List, Optional


class ThreatLevel(str, Enum):
    HIGH_RISK = "🔴 HIGH RISK / SCAM ALERT"
    MEDIUM_RISK = "🟡 MEDIUM RISK / SUSPICIOUS ACTIVITY WARNING"
    LOW_RISK = "🟢 LOW RISK / VERIFIED TRANSACTION"


class ScamShieldClassifier:
    """Rules engine for evaluating transaction risk and generating structured card reports."""

    PROMPT_INJECTION_PATTERNS = [
        r"ignore\s+previous\s+instructions",
        r"system\s+override",
        r"admin\s+access",
        r"sudo\s+transfer",
        r"disregard\s+safety",
        r"bypass\s+security",
        r"transfer\s+all\s+funds\s+to",
    ]

    HIGH_RISK_SCAM_PATTERNS = [
        r"guaranteed\s+return",
        r"100%\s+roi",
        r"doubler",
        r"offshore\s+crypto",
        r"risk-free\s+yield",
        r"lottery\s+payout",
        r"claim\s+prize",
        r"wire\s+transfer\s+fee",
    ]

    URGENT_PRESSURE_PATTERNS = [
        r"urgent",
        r"immediate\s+action",
        r"account\s+suspend",
        r"pay\s+within",
        r"verify\s+immediately",
        r"emergency",
        r"final\s+notice",
    ]

    VERIFIED_CATEGORIES = [
        "Retail",
        "Subscriptions",
        "Utility",
        "Utilities",
        "Food & Beverage",
        "Shopping",
        "Transportation",
        "Groceries",
        "Healthcare",
        "Dining",
        "Travel",
        "Bill Payments",
        "Banking & Financial Services",
        "Banking",
        "Financial Services",
        "Finance",
    ]

    def __init__(self, p2p_high_value_inr_threshold: float = 20000.0):
        self.p2p_high_value_threshold = p2p_high_value_inr_threshold

    def evaluate_transaction(
        self,
        transaction: Dict[str, Any],
        note: str = "",
    ) -> Dict[str, Any]:
        """
        Evaluates a normalized transaction record and raw note/memo metadata.

        Args:
            transaction: Normalized transaction dictionary containing transaction_id, amount_inr,
                         merchant_category, timestamp, merchant_name, currency, etc.
            note: Raw note/memo/description metadata attached to the transaction.

        Returns:
            Dictionary containing threat_level, header, summary, key_findings, recommended_action, and formatted_card.
        """
        merchant_name = str(transaction.get("merchant_name") or transaction.get("merchant") or transaction.get("raw_merchant") or "Unknown")
        category = str(transaction.get("merchant_category") or "Uncategorized")
        amount_inr = float(transaction.get("amount_inr") or transaction.get("amount") or 0.0)
        currency = str(transaction.get("currency") or "INR").strip().upper()
        timestamp = str(transaction.get("timestamp") or "")

        combined_text = f"{merchant_name} {note}".lower()

        # Flags tracking
        high_risk_reasons = []
        medium_risk_reasons = []
        merchant_status_flag = ""
        behavioral_flag = ""
        data_integrity_flag = ""

        # 1. Check Prompt Injection
        has_prompt_injection = any(re.search(pattern, note, re.IGNORECASE) for pattern in self.PROMPT_INJECTION_PATTERNS)
        if has_prompt_injection:
            high_risk_reasons.append("Prompt injection attack detected in transaction memo metadata.")
            behavioral_flag = "Prompt Injection: Memory/prompt override instructions detected in metadata."

        # 2. Check High-Risk Scam Patterns
        has_high_risk_pattern = any(re.search(pattern, combined_text, re.IGNORECASE) for pattern in self.HIGH_RISK_SCAM_PATTERNS)
        if has_high_risk_pattern:
            high_risk_reasons.append("Unverified offshore entity exhibiting guaranteed yields or scam claims.")
            if not behavioral_flag:
                behavioral_flag = "Guaranteed Yield / Offshore Scam: High-risk payout claims or suspicious investment pattern detected."

        # 3. Check Timestamp Data Integrity
        if not timestamp or "INVALID" in timestamp.upper():
            high_risk_reasons.append("Flagged for suspicious or malformed timestamp patterns.")
            data_integrity_flag = "Data Integrity: Flagged for suspicious, missing, or corrupt timestamp patterns."

        # 4. Check Urgent Pressure Language
        has_urgent_pressure = any(re.search(pattern, note, re.IGNORECASE) for pattern in self.URGENT_PRESSURE_PATTERNS)
        if has_urgent_pressure:
            medium_risk_reasons.append("Urgent pressure or coercion language detected in transaction memo.")
            if not behavioral_flag:
                behavioral_flag = "Coercion Indicator: Urgent pressure language used to bypass user verification."

        # 5. Check Merchant Registration Status (case-insensitive)
        is_verified_merchant = any(category.strip().lower() == v.strip().lower() for v in self.VERIFIED_CATEGORIES)
        if not is_verified_merchant:
            medium_risk_reasons.append(f"Merchant '{merchant_name}' is unregistered in trusted categories database (category: '{category}').")
            merchant_status_flag = f"Merchant Status: Unregistered in our trusted categories database (defaults to High-Risk/Unknown category: '{category}')."
            # Unregistered offshore merchant with foreign currency -> High Risk
            if currency != "INR" or amount_inr > 50000.0:
                high_risk_reasons.append("Unverified offshore merchant node with foreign currency or high transfer amount.")
        else:
            merchant_status_flag = f"Merchant Status: Verified merchant node registered under category '{category}'."

        # 6. Check High P2P / High Value Transfers
        is_p2p_or_transfer = "p2p" in combined_text or "transfer" in combined_text or category in ["Uncategorized", "Unknown/Other"]
        if is_p2p_or_transfer and amount_inr >= self.p2p_high_value_threshold:
            medium_risk_reasons.append(f"High-value transfer of {amount_inr:.2f} INR exceeds P2P threshold ({self.p2p_high_value_threshold:.2f} INR).")
            if not behavioral_flag:
                behavioral_flag = f"High Amount P2P Transfer: Transfer of {amount_inr:.2f} INR flags peer-to-peer threshold."

        # Set default data integrity flag if not already set
        if not data_integrity_flag:
            if currency != "INR":
                data_integrity_flag = f"Data Integrity: Foreign currency ({currency}) normalized to {amount_inr:.2f} INR. Timestamp valid."
            else:
                data_integrity_flag = f"Data Integrity: Valid local transaction record with verified timestamp ({timestamp or 'OK'})."

        # Determine Threat Level & Recommended Action
        if high_risk_reasons:
            threat_level = ThreatLevel.HIGH_RISK
            summary = (
                f"This transaction involves an unverified foreign entity or malicious prompt injection "
                f"exhibiting high-risk fraud claims ({'; '.join(high_risk_reasons[:2])})."
            )
            recommended_action = "Block Transaction. Do not authorize funds transfer or release details to this merchant."
        elif medium_risk_reasons:
            threat_level = ThreatLevel.MEDIUM_RISK
            summary = (
                f"This transaction has been flagged for suspicious indicators including "
                f"{'; '.join(medium_risk_reasons[:2])}."
            )
            recommended_action = "Hold for Review. Require secondary authentication and manual verification before proceeding."
        else:
            threat_level = ThreatLevel.LOW_RISK
            summary = (
                f"This transaction with {merchant_name} for {amount_inr:.2f} INR matches standard "
                f"verified merchant patterns in category '{category}'."
            )
            recommended_action = "Approve Transaction. Process payment normally."
            if not behavioral_flag:
                behavioral_flag = "Behavioral Flags: None detected. Standard consumer transaction."

        # Format Card Output
        formatted_card = (
            f"{threat_level.value}\n\n"
            f"    Summary: {summary}\n\n"
            f"    Key Findings:\n\n"
            f"        Merchant Status: {merchant_status_flag.replace('Merchant Status: ', '')}\n\n"
            f"        Behavioral Flags: {behavioral_flag.replace('Behavioral Flags: ', '')}\n\n"
            f"        Data Integrity: {data_integrity_flag.replace('Data Integrity: ', '')}\n\n"
            f"    Recommended Action: {recommended_action}"
        )

        return {
            "threat_level": threat_level.name,
            "header": threat_level.value,
            "summary": summary,
            "key_findings": {
                "merchant_status": merchant_status_flag,
                "behavioral_flags": behavioral_flag,
                "data_integrity": data_integrity_flag,
            },
            "recommended_action": recommended_action,
            "formatted_card": formatted_card,
            "amount_inr": amount_inr,
            "merchant_category": category,
        }


# Module instance convenience function
default_classifier = ScamShieldClassifier()


def classify_scamshield_transaction(
    transaction: Dict[str, Any],
    note: str = "",
) -> Dict[str, Any]:
    """Convenience helper function for classifying transaction risk."""
    return default_classifier.evaluate_transaction(transaction, note=note)
