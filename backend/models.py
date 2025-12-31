from sqlalchemy.orm import declarative_base, relationship, Mapped, mapped_column
from sqlalchemy import String, Integer, Float, DateTime, ForeignKey, JSON, Text, Boolean
from datetime import datetime

Base = declarative_base()

class Vendor(Base):
    __tablename__ = "vendors"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    descriptors_regex: Mapped[str | None] = mapped_column(Text, nullable=True)

    transactions = relationship("Transaction", back_populates="vendor")
    invoices = relationship("Invoice", back_populates="vendor")
    subscriptions = relationship("Subscription", back_populates="vendor")

class Transaction(Base):
    __tablename__ = "transactions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vendor_id: Mapped[int | None] = mapped_column(ForeignKey("vendors.id"))
    plaid_txn_id: Mapped[str | None] = mapped_column(String(255), index=True)
    merchant_name: Mapped[str | None] = mapped_column(String(255))
    amount: Mapped[float | None] = mapped_column(Float)
    iso_currency_code: Mapped[str | None] = mapped_column(String(10))
    date: Mapped[str | None] = mapped_column(String(20))  
    raw: Mapped[dict | None] = mapped_column(JSON)

    vendor = relationship("Vendor", back_populates="transactions")

class Invoice(Base):
    __tablename__ = "invoices"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vendor_id: Mapped[int | None] = mapped_column(ForeignKey("vendors.id"))
    total: Mapped[float | None] = mapped_column(Float)
    invoice_date: Mapped[str | None] = mapped_column(String(20))
    billing_period: Mapped[str | None] = mapped_column(String(64))
    raw: Mapped[dict | None] = mapped_column(JSON)

    vendor = relationship("Vendor", back_populates="invoices")

class Subscription(Base):
    __tablename__ = "subscriptions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vendor_id: Mapped[int | None] = mapped_column(ForeignKey("vendors.id"))
    status: Mapped[str] = mapped_column(String(32), default="inferred")  # inferred|active|cancelled
    interval: Mapped[str | None] = mapped_column(String(32))  # monthly/yearly/unknown
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    first_seen: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    next_expected: Mapped[str | None] = mapped_column(String(20))

    vendor = relationship("Vendor", back_populates="subscriptions")
