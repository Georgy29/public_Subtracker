from sqlalchemy.orm import Session
from sqlalchemy import select, func
from models import Transaction, Vendor, Subscription
from datetime import datetime

def detect_basic_subscriptions(db: Session):
    """
    Очень простая эвристика:
      - группируем по merchant_name
      - если >= 3 транзакций за последние ~120 дней и средний интервал ~30±3 дней — считаем как monthly
    """
    # 1) load every transaction where merchant_name != NULL
    txns = db.execute(select(Transaction).where(Transaction.merchant_name.isnot(None))).scalars().all()
    if not txns:
        return
    # 2)
    """
    {
    "Netflix": [Transaction(...), Transaction(...), Transaction(...)],
    "Spotify": [Transaction(...), Transaction(...)]
    }
    """
    from collections import defaultdict
    groups = defaultdict(list)
    for t in txns:
        groups[t.merchant_name].append(t)
    # 3)
    for merchant, items in groups.items():
        if len(items) < 3:
            continue
        # sort by date
        items.sort(key=lambda x: x.date or "")
        from datetime import datetime as dt
        dates = []
        for it in items:
            try:
                dates.append(dt.strptime(it.date, "%Y-%m-%d"))
            except Exception:
                pass
        if len(dates) < 3:
            continue

        diffs = [(dates[i] - dates[i-1]).days for i in range(1, len(dates))]
        if not diffs:
            continue
        avg = sum(diffs)/len(diffs)
        if 27 <= avg <= 33:
            # upsert Vendor
            vendor = db.query(Vendor).filter(Vendor.name == merchant).one_or_none()
            if not vendor:
                from models import Vendor as V
                vendor = V(name=merchant)
                db.add(vendor)
                db.flush()

            # upsert Subscription
            sub = db.query(Subscription).filter(Subscription.vendor_id == vendor.id).one_or_none()
            if not sub:
                sub = Subscription(vendor_id=vendor.id, status="inferred", interval="monthly", confidence=0.7)
                db.add(sub)
            else:
                sub.interval = "monthly"
                sub.confidence = max(sub.confidence, 0.7)
            sub.last_seen = datetime.utcnow()
    db.commit()