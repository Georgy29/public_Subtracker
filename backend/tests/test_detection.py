from datetime import date, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.detection import detect_basic_subscriptions
from backend.models import Base, Subscription, Transaction, Vendor


def test_detect_basic_subscriptions_monthly():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    s = session_local()
    try:
        base = date.today()
        for offset in (0, 30, 60):
            s.add(
                Transaction(
                    merchant_name="Netflix",
                    amount=15.99,
                    iso_currency_code="USD",
                    date=(base - timedelta(days=offset)).isoformat(),
                    raw={},
                )
            )
        for offset in (3, 11, 20):
            s.add(
                Transaction(
                    merchant_name="Starbucks",
                    amount=5.50,
                    iso_currency_code="USD",
                    date=(base - timedelta(days=offset)).isoformat(),
                    raw={},
                )
            )
        s.commit()

        detect_basic_subscriptions(s)

        subs = s.query(Subscription).all()
        assert len(subs) == 1
        vendor = s.get(Vendor, subs[0].vendor_id)
        assert vendor.name == "Netflix"
    finally:
        s.close()
