"""ORM models for the Finance Tracker backend.

Models are imported here so that Alembic can auto-discover them via
``from backend.app.models import *``.
"""

from backend.app.models.transaction import Transaction  # noqa: F401
from backend.app.models.account import Account  # noqa: F401
from backend.app.models.classification import Classification  # noqa: F401
from backend.app.models.parser import Parser  # noqa: F401
from backend.app.models.unparsed_message import UnparsedMessage  # noqa: F401
from backend.app.models.ingest_cursor import IngestCursor  # noqa: F401
from backend.app.models.fetched_email import FetchedEmail  # noqa: F401
