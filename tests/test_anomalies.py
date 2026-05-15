import pytest
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.core.database import Base, CostDailyRecord, CostAnomaly
from backend.agents.cost_anomaly_agent import run_cost_anomaly_agent


def make_session():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    return Session()


def seed_stable_series(db, account_id="acct-1", service="TestService", days=10, base=10.0):
    today = datetime.utcnow().date()
    for i in range(days):
        d = (today - timedelta(days=(days - 1 - i))).isoformat()
        db.add(CostDailyRecord(account_id=account_id, service_name=service, date=d, cost=base + (i%2)))
    db.commit()


def seed_spike_series(db, account_id="acct-1", service="EC2", days=10, base=10.0, spike_amount=100.0):
    today = datetime.utcnow().date()
    for i in range(days):
        d = (today - timedelta(days=(days - 1 - i))).isoformat()
        cost = base
        if i == days - 1:
            cost = spike_amount
        db.add(CostDailyRecord(account_id=account_id, service_name=service, date=d, cost=cost))
    db.commit()


def test_spike_flagged():
    db = make_session()
    seed_spike_series(db)
    res = run_cost_anomaly_agent(db, "acct-1")
    assert res["new_anomalies"] >= 1
    rows = db.query(CostAnomaly).filter(CostAnomaly.account_id == "acct-1").all()
    assert len(rows) >= 1
    a = rows[0]
    assert "EC2" in a.service_name or a.service_name == "EC2"
    assert a.severity in ["low", "medium", "high"]
    assert "spend" in a.explanation.lower()


def test_stable_not_flagged():
    db = make_session()
    seed_stable_series(db)
    res = run_cost_anomaly_agent(db, "acct-1")
    # all days stable - no anomalies
    assert res["new_anomalies"] == 0


def test_zero_std_handling():
    db = make_session()
    # create series where all previous costs identical -> std dev 0
    today = datetime.utcnow().date()
    for i in range(8):
        d = (today - timedelta(days=(8 - 1 - i))).isoformat()
        db.add(CostDailyRecord(account_id="acct-2", service_name="FlatService", date=d, cost=5.0))
    db.commit()
    # add a small bump
    db.add(CostDailyRecord(account_id="acct-2", service_name="FlatService", date=(today + timedelta(days=0)).isoformat(), cost=6.0))
    db.commit()
    res = run_cost_anomaly_agent(db, "acct-2")
    # With std=0, agent should rely on avg thresholds and not crash
    assert isinstance(res.get("new_anomalies"), int)


def test_idempotence_of_detection():
    db = make_session()
    seed_spike_series(db, account_id="acct-3", service="EC2", days=10, base=10.0, spike_amount=120.0)
    r1 = run_cost_anomaly_agent(db, "acct-3")
    count1 = db.query(CostAnomaly).filter(CostAnomaly.account_id == "acct-3").count()
    r2 = run_cost_anomaly_agent(db, "acct-3")
    count2 = db.query(CostAnomaly).filter(CostAnomaly.account_id == "acct-3").count()
    assert count1 == count2
    assert r2["new_anomalies"] == 0


def test_ingest_history_with_run_anomaly_detection(tmp_path):
    # This test simulates calling the ingest route logic: insert demo records and run anomaly detection
    from backend.routers.cost import ingest_history, IngestRequest
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from backend.core.database import Base, CostDailyRecord, CostAnomaly

    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    # monkeypatch get_db dependency by calling ingest_history directly with db
    req = IngestRequest(connection_id=None, days_back=10, run_anomaly_detection=True)
    res = ingest_history(req, db=db)
    assert res["records_ingested"] > 0
    assert "anomaly_detection" in res
    # anomalies should be created for the demo spike (service EC2)
    anomalies = db.query(CostAnomaly).filter(CostAnomaly.account_id == res["account_id"]).all()
    assert len(anomalies) >= 1


def test_ingest_idempotence_with_detection(tmp_path):
    from backend.routers.cost import ingest_history, IngestRequest
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from backend.core.database import Base, CostDailyRecord, CostAnomaly

    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    req = IngestRequest(connection_id=None, days_back=10, run_anomaly_detection=True)
    r1 = ingest_history(req, db=db)
    count_cost_1 = db.query(CostDailyRecord).filter(CostDailyRecord.account_id == r1["account_id"]).count()
    count_anom_1 = db.query(CostAnomaly).filter(CostAnomaly.account_id == r1["account_id"]).count()

    r2 = ingest_history(req, db=db)
    count_cost_2 = db.query(CostDailyRecord).filter(CostDailyRecord.account_id == r2["account_id"]).count()
    count_anom_2 = db.query(CostAnomaly).filter(CostAnomaly.account_id == r2["account_id"]).count()

    assert count_cost_1 == count_cost_2
    assert count_anom_1 == count_anom_2
