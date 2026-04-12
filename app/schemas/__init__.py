"""Pydantic schemas for the Finance Tracker API.

Schemas are used by FastAPI for request/response validation and OpenAPI docs.
They are separate from ORM models to maintain a clean separation of concerns.

Implementation lives in submodules (``enums``, ``transactions``, …); this package
re-exports the public API so callers can use ``from backend.app.schemas import …``.
"""

from __future__ import annotations

from backend.app.schemas.accounts import (
    AccountFromTransactionsMergedRead,
    AccountRead,
    AccountTransactionsConflictEntry,
    AccountUpsert,
    AccountUpsertRead,
)
from backend.app.schemas.analytics import (
    CashflowPoint,
    CategoryBreakdown,
    MerchantSummary,
    MonthlyStats,
    TransactionSummaryRead,
)
from backend.app.schemas.app_config import AppConfigRead, AppConfigUpdate
from backend.app.schemas.classifications import (
    ClassificationCreate,
    ClassificationRead,
    ClassificationUpdate,
)
from backend.app.schemas.emails import (
    ExtractRegexPreviewRequest,
    ExtractRegexPreviewResponse,
    FetchedEmailContentRead,
    FetchedEmailEnrichmentDetailRead,
    FetchedEmailEnrichmentRead,
    FetchedEmailRead,
    FetchedEmailWithEnrichmentResponse,
    FetchedEmailWithLinkedTransactionsRead,
    MatcherPreviewItemRead,
    MatcherPreviewRequest,
    MatcherPreviewResponse,
    RegexFieldPreviewRead,
    RegexGroupSpanRead,
    RegexSpanRead,
    UnparsedEmailDetailRead,
    UnparsedEmailListItem,
)
from backend.app.schemas.enums import (
    AccountType,
    Direction,
    MessageType,
    Status,
    SubType,
    TransactionType,
)
from backend.app.schemas.parsers import ParserCreate, ParserRead, ParserUpdate
from backend.app.schemas.transactions import (
    TransactionBase,
    TransactionDistinctCatalog,
    TransactionListResponse,
    TransactionRead,
)
from backend.app.schemas.meta import AppMetadataRead
from backend.app.schemas.mail_accounts import MailAccountCreate, MailAccountRead
from backend.app.schemas.exclusion_rules import ExclusionRuleCreate, ExclusionRuleRead, ExclusionRuleUpdate

__all__ = [
    "AccountFromTransactionsMergedRead",
    "AccountRead",
    "AccountTransactionsConflictEntry",
    "AccountUpsert",
    "AccountUpsertRead",
    "AccountType",
    "AppConfigRead",
    "AppConfigUpdate",
    "CashflowPoint",
    "CategoryBreakdown",
    "ClassificationCreate",
    "ClassificationRead",
    "ClassificationUpdate",
    "Direction",
    "FetchedEmailEnrichmentDetailRead",
    "FetchedEmailEnrichmentRead",
    "FetchedEmailContentRead",
    "FetchedEmailRead",
    "FetchedEmailWithEnrichmentResponse",
    "FetchedEmailWithLinkedTransactionsRead",
    "MerchantSummary",
    "MessageType",
    "MonthlyStats",
    "TransactionSummaryRead",
    "ParserCreate",
    "ParserRead",
    "ParserUpdate",
    "Status",
    "SubType",
    "TransactionBase",
    "TransactionDistinctCatalog",
    "TransactionListResponse",
    "TransactionRead",
    "TransactionType",
    "MatcherPreviewRequest",
    "MatcherPreviewItemRead",
    "MatcherPreviewResponse",
    "ExtractRegexPreviewRequest",
    "ExtractRegexPreviewResponse",
    "RegexFieldPreviewRead",
    "RegexGroupSpanRead",
    "RegexSpanRead",
    "UnparsedEmailDetailRead",
    "UnparsedEmailListItem",
    "AppMetadataRead",
    "MailAccountRead",
    "MailAccountCreate",
    "ExclusionRuleCreate",
    "ExclusionRuleRead",
    "ExclusionRuleUpdate",
]
