"""
Data Schemas for FinTech Data Ingestion & Normalization Pipeline.
"""

from pydantic import BaseModel, Field


class NormalizedTransaction(BaseModel):
    """Strict Pydantic model for normalized transaction records."""

    transaction_id: str = Field(..., description="Unique identifier for the transaction")
    amount_inr: float = Field(..., description="Transaction amount normalized to INR rounded to 2 decimal places")
    merchant_category: str = Field(..., description="Enriched broad merchant category")
    timestamp: str = Field(..., description="ISO or raw transaction timestamp string")
