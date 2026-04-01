"""Shared string enums for API / OpenAPI (mirror ORM choices where applicable)."""

from __future__ import annotations

from enum import Enum


class Direction(str, Enum):
    """Money flow direction mirroring the ORM enum, exposed in API responses."""

    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


class MessageType(str, Enum):
    TRANSACTION_ALERT = "TRANSACTION_ALERT"
    INVESTMENT_NOTICE = "INVESTMENT_NOTICE"
    STATEMENT = "STATEMENT"
    SINK = "SINK"
    OTHER = "OTHER"


class AccountType(str, Enum):
    SAVINGS = "SAVINGS"
    CURRENT = "CURRENT"
    CREDIT_CARD = "CREDIT_CARD"
    WALLET = "WALLET"
    UPI = "UPI"


class TransactionType(str, Enum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"
    PAYMENT = "PAYMENT"
    CARD_SPEND = "CARD_SPEND"
    CARD_REPAYMENT = "CARD_REPAYMENT"
    UPI = "UPI"
    ATM = "ATM"
    NEFT = "NEFT"
    IMPS = "IMPS"
    CHARGE = "CHARGE"
    REFUND = "REFUND"


class SubType(str, Enum):
    CARD_PAYMENT = "CARD_PAYMENT"
    CREDIT_CARD_REPAYMENT = "CREDIT_CARD_REPAYMENT"
    UPI_TRANSFER = "UPI_TRANSFER"
    UPI_RECEIVE = "UPI_RECEIVE"
    UPI_SEND = "UPI_SEND"
    NEFT_TRANSFER = "NEFT_TRANSFER"
    IMPS_TRANSFER = "IMPS_TRANSFER"
    ATM_WITHDRAWAL = "ATM_WITHDRAWAL"
    REFUND = "REFUND"
    CHARGE = "CHARGE"
    PAYMENT = "PAYMENT"
    FEE = "FEE"
    REVERSAL = "REVERSAL"
    BILL_PAYMENT = "BILL_PAYMENT"
    LOAN_EMI = "LOAN_EMI"
    STANDING_ORDER = "STANDING_ORDER"
    DDA = "DDA"


class Status(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    PENDING = "PENDING"
    UNKNOWN = "UNKNOWN"
