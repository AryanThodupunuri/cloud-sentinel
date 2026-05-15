import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.core.database import Base, OptimizationRecommendation
from backend.agents.compute_optimizer_agent import run_compute_optimizer_agent, generate_demo_recommendations


def make_session():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    return Session()


def test_demo_scan_creates_recommendations():
    db = make_session()
    res = run_compute_optimizer_agent(db)
    assert res["status"] == "demo_mode"
    assert res["recommendations_created"] >= 1
    rows = db.query(OptimizationRecommendation).all()
    assert len(rows) >= res["recommendations_created"]


def test_demo_scan_idempotence():
    db = make_session()
    r1 = run_compute_optimizer_agent(db)
    count1 = db.query(OptimizationRecommendation).count()
    r2 = run_compute_optimizer_agent(db)
    count2 = db.query(OptimizationRecommendation).count()
    assert count1 == count2
    # second run should report zero created
    assert r2["recommendations_created"] == 0


def test_parsing_demo_structure():
    recs = generate_demo_recommendations()
    assert any(r["recommendation_type"] == "ec2_rightsizing" for r in recs)
    assert any(r["resource_type"] == "ebs_volume" for r in recs)
