import pytest
from datetime import datetime, timedelta
from backend.services.cost_explorer_service import _parse_ce_response, generate_demo_daily_costs, fetch_daily_costs
import json


def test_parse_ce_response_sample():
    # Minimal sample response
    sample = {
        "ResultsByTime": [
            {
                "TimePeriod": {"Start": "2026-05-01", "End": "2026-05-02"},
                "Groups": [
                    {"Keys": ["Amazon EC2"], "Metrics": {"UnblendedCost": {"Amount": "12.34", "Unit": "USD"}}}
                ]
            }
        ]
    }
    records = _parse_ce_response(sample)
    assert len(records) == 1
    r = records[0]
    assert r["date"] == "2026-05-01"
    assert r["service_name"] == "Amazon EC2"
    assert abs(r["cost"] - 12.34) < 0.001


def test_generate_demo_daily_costs_length():
    recs = generate_demo_daily_costs(10)
    # 7 services * 10 days
    assert len(recs) == 7 * 10


def test_demo_idempotence(tmp_path, monkeypatch):
    # Use an in-memory sqlite DB to run the ingestion twice and verify no duplicates
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from backend.core.database import Base, CostDailyRecord

    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    # seed demo records
    recs = generate_demo_daily_costs(5)
    # insert first time
    ingested = 0
    for r in recs:
        existing = db.query(CostDailyRecord).filter(
            CostDailyRecord.account_id == "demo-unknown",
            CostDailyRecord.service_name == r["service_name"],
            CostDailyRecord.date == r["date"],
        ).first()
        if not existing:
            db.add(CostDailyRecord(
                account_id="demo-unknown",
                service_name=r["service_name"],
                date=r["date"],
                cost=r["cost"],
                currency=r["currency"],
                source="demo",
            ))
            ingested += 1
    db.commit()

    count1 = db.query(CostDailyRecord).count()
    # insert again - should not duplicate
    for r in recs:
        existing = db.query(CostDailyRecord).filter(
            CostDailyRecord.account_id == "demo-unknown",
            CostDailyRecord.service_name == r["service_name"],
            CostDailyRecord.date == r["date"],
        ).first()
        if not existing:
            db.add(CostDailyRecord(
                account_id="demo-unknown",
                service_name=r["service_name"],
                date=r["date"],
                cost=r["cost"],
                currency=r["currency"],
                source="demo",
            ))
    db.commit()
    count2 = db.query(CostDailyRecord).count()
    assert count1 == count2