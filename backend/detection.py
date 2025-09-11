from sqlalchemy.orm import Session
from sqlalchemy import select, func
from models import Transaction, Vendor, Subscription
from datetime import datetime, timedelta
import re
from collections import defaultdict

# Name-based noise (substring match, lowercase) -- this is just an example list
NAME_BLACKLIST = {
    "starbucks", "mcdonald", "kfc",
    "credit card", "intrst pymnt", "automatic payment",
    "ach electronic credit", "cd deposit", "gusto pay",
    "payroll", "deposit", "thank", "atm", "pos", "gas"
}

# Plaid personal finance categories to exclude (if present in tx.raw)
PFC_PRIMARY_EXCLUDE = {
    "INCOME", "TRANSFER_IN", "TRANSFER_OUT", "LOAN_PAYMENTS", "BANK_FEES", "SAVINGS"
}

WINDOW_DAYS = 150

def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())

def _is_noise(tx: Transaction) -> bool:
    n = _norm(tx.merchant_name or (tx.raw or {}).get("name", ""))
    if any(b in n for b in NAME_BLACKLIST):
        return True
    raw = tx.raw or {}
    pfc = (raw.get("personal_finance_category") or {})
    primary = (pfc.get("primary") or "").upper()
    if primary in PFC_PRIMARY_EXCLUDE:
        return True
    return False

def _amounts_consistent(amts: list[float]) -> bool:
    """Return True if amounts are reasonably consistent (±25% tolerance or ≤ $5 absolute)."""
    amts = [a for a in amts if isinstance(a, (int, float))]
    if len(amts) < 3:
        return True  # don't block on small sample
    amts.sort()
    mid = amts[len(amts)//2]
    if mid == 0:
        return True
    spread = max(abs(a - mid) for a in amts)
    return (spread <= 5.0) or (spread / abs(mid) <= 0.25)

def detect_basic_subscriptions(db: Session):
    since = (datetime.utcnow() - timedelta(days=WINDOW_DAYS)).date()

    txns = db.execute(
        select(Transaction).where(Transaction.merchant_name.isnot(None))
    ).scalars().all()
    if not txns:
        return

    groups: dict[str, list[Transaction]] = defaultdict(list)
    for t in txns:
        # date window filter and noise filter
        try:
            if not t.date or datetime.strptime(t.date, "%Y-%m-%d").date() < since:
                continue
        except Exception:
            continue
        if _is_noise(t):
            continue
        groups[_norm(t.merchant_name)].append(t)

    for norm_merchant, items in groups.items():
        if len(items) < 3:
            continue

        # use a display name from original data
        merchant_display = next((it.merchant_name for it in items if it.merchant_name), norm_merchant)

        # sort by date
        items.sort(key=lambda x: x.date or "")
        dates = []
        for it in items:
            try:
                dates.append(datetime.strptime(it.date, "%Y-%m-%d"))
            except Exception:
                pass
        if len(dates) < 3:
            continue

        # amounts must be fairly consistent (reduces KFC/Starbucks etc.)
        if not _amounts_consistent([it.amount for it in items]):
            continue

        diffs = [(dates[i] - dates[i-1]).days for i in range(1, len(dates))]
        if not diffs:
            continue
        avg = sum(diffs) / len(diffs)

        # monthly ~ 30±3
        if 27 <= avg <= 33:
            # upsert vendor (case-insensitive)
            vendor = (
                db.query(Vendor)
                  .filter(func.lower(Vendor.name) == merchant_display.lower())
                  .one_or_none()
            )
            if not vendor:
                vendor = Vendor(name=merchant_display)
                db.add(vendor)
                db.flush()

            # link transactions to this vendor
            for it in items:
                if it.vendor_id != vendor.id:
                    it.vendor_id = vendor.id

            # compute next_expected
            last_dt = max(dates)
            next_expected = (last_dt + timedelta(days=30)).date().isoformat()

            # upsert subscription
            sub = (
                db.query(Subscription)
                  .filter(Subscription.vendor_id == vendor.id)
                  .one_or_none()
            )
            if not sub:
                sub = Subscription(
                    vendor_id=vendor.id,
                    status="inferred",
                    interval="monthly",
                    confidence=0.7,
                    next_expected=next_expected,
                )
                db.add(sub)
            else:
                sub.interval = "monthly"
                sub.confidence = max(sub.confidence, 0.7)
                sub.next_expected = next_expected

            sub.last_seen = datetime.utcnow()

    db.commit()
