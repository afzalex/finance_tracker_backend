import datetime
from sqlalchemy.orm import Session

from backend.app.models.transaction import Transaction, Direction, Origin
from backend.app.services.transaction_service import TransactionService, TransactionListParams

def seed_transactions(db: Session):
    txs = [
        Transaction(
            mail_id="1",
            origin=Origin.EMAIL_ALERT,
            account_id="ACC1",
            provider="HDFC",
            category="Food",
            direction=Direction.DEBIT,
            transacted_at=datetime.datetime(2024, 1, 10, 12, 0, 0),
            amount_parsed=150.0,
            merchant="Swiggy",
            counterparty_name="Food Vendor",
            currency="INR"
        ),
        Transaction(
            mail_id="2",
            origin=Origin.EMAIL_ALERT,
            account_id="ACC2",
            provider="SBI",
            category="Salary",
            direction=Direction.CREDIT,
            transacted_at=datetime.datetime(2024, 1, 15, 12, 0, 0),
            amount_parsed=50000.0,
            merchant="Employer",
            counterparty_name="Tech Corp",
            currency="INR"
        ),
        Transaction(
            mail_id="3",
            origin=Origin.EMAIL_ALERT,
            account_id="ACC1",
            provider="HDFC",
            category="Shopping",
            direction=Direction.DEBIT,
            transacted_at=datetime.datetime(2024, 1, 20, 12, 0, 0),
            amount_parsed=2000.0,
            merchant="Amazon",
            counterparty_name="Amazon India",
            currency="INR"
        )
    ]
    db.add_all(txs)
    db.commit()

def test_list_transactions_basic(db: Session):
    seed_transactions(db)
    service = TransactionService(db)
    items, total = service.list_transactions(TransactionListParams())
    
    assert total == 3
    assert len(items) == 3
    # Default sort is transacted_at DESC
    assert items[0].merchant == "Amazon"
    assert items[1].merchant == "Employer"
    assert items[2].merchant == "Swiggy"

def test_list_transactions_account_id(db: Session):
    seed_transactions(db)
    service = TransactionService(db)
    items, total = service.list_transactions(TransactionListParams(account_id="ACC1"))
    
    assert total == 2
    assert all(t.account_id == "ACC1" for t in items)

def test_list_transactions_provider(db: Session):
    seed_transactions(db)
    service = TransactionService(db)
    items, total = service.list_transactions(TransactionListParams(provider="SBI"))
    
    assert total == 1
    assert items[0].provider == "SBI"

def test_list_transactions_category(db: Session):
    seed_transactions(db)
    service = TransactionService(db)
    items, total = service.list_transactions(TransactionListParams(category="Food"))
    
    assert total == 1
    assert items[0].category == "Food"

def test_list_transactions_direction(db: Session):
    seed_transactions(db)
    service = TransactionService(db)
    items, total = service.list_transactions(TransactionListParams(direction="CREDIT"))
    
    assert total == 1
    assert items[0].direction == "CREDIT"

def test_list_transactions_date_range(db: Session):
    seed_transactions(db)
    service = TransactionService(db)
    # Between Jan 10 and Jan 15 inclusive
    params = TransactionListParams(
        date_from=datetime.date(2024, 1, 10),
        date_to=datetime.date(2024, 1, 15)
    )
    items, total = service.list_transactions(params)
    
    assert total == 2
    merchants = {t.merchant for t in items}
    assert merchants == {"Swiggy", "Employer"}

def test_list_transactions_search(db: Session):
    seed_transactions(db)
    service = TransactionService(db)
    # Search should be case insensitive and match partial strings
    params = TransactionListParams(search="wig")
    items, total = service.list_transactions(params)
    
    assert total == 1
    assert items[0].merchant == "Swiggy"

def test_list_transactions_sort_by_amount(db: Session):
    seed_transactions(db)
    service = TransactionService(db)
    params = TransactionListParams(sort_by="amount", sort_order="desc")
    items, total = service.list_transactions(params)
    
    assert total == 3
    assert items[0].amount_parsed == 50000.0  # Employer
    assert items[1].amount_parsed == 2000.0   # Amazon
    assert items[2].amount_parsed == 150.0    # Swiggy

def test_list_transactions_sort_by_merchant_asc(db: Session):
    seed_transactions(db)
    service = TransactionService(db)
    params = TransactionListParams(sort_by="merchant", sort_order="asc")
    items, total = service.list_transactions(params)
    
    assert total == 3
    assert items[0].merchant == "Amazon"
    assert items[1].merchant == "Employer"
    assert items[2].merchant == "Swiggy"
