"""Shared sentinel values for API and analytics dimensions."""

# Top merchants: DEBIT rows with no trimmed merchant and no trimmed counterparty_name.
TOP_MERCHANTS_UNDEFINED_MERCHANT = "__UNDEFINED__"

# Distinct counterparties list when ``counterparty_name`` is null or blank after trim.
DISTINCT_UNNAMED_COUNTERPARTY = "__NO_COUNTERPARTY__"
