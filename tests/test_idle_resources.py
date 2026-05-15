import pytest
from datetime import datetime
from core.database import OptimizationRecommendation, get_db
from agents.idle_resource_agent import is_idle_ec2, run_idle_resource_agent


def get_db_instance():
    return next(get_db())


def test_is_idle_true():
    assert is_idle_ec2(1.0, 0.0, 0.0, 10) is True


def test_is_idle_false_cpu():
    assert is_idle_ec2(10.0, 0.0, 0.0, 10) is False


def test_is_idle_false_datapoints():
    assert is_idle_ec2(1.0, 0.0, 0.0, 1) is False


def test_demo_idle_scan_creates():
    db = get_db_instance()
    # Clean up any existing demo recs
    db.query(OptimizationRecommendation).filter(OptimizationRecommendation.account_id.like("demo-%"), OptimizationRecommendation.recommendation_type == "idle_ec2").delete()
    db.commit()

    res = run_idle_resource_agent(db, account_id="demo-123456789012", region="us-east-1", lookback_days=14)
    assert res["status"] in ("demo_mode", "completed")
    assert res["idle_instances_found"] >= 1
    rows = db.query(OptimizationRecommendation).filter(OptimizationRecommendation.account_id == "demo-123456789012", OptimizationRecommendation.recommendation_type == "idle_ec2").all()
    assert len(rows) >= 1


def test_demo_idle_scan_idempotent():
    db = get_db_instance()
    # Run twice
    res1 = run_idle_resource_agent(db, account_id="demo-123456789012", region="us-east-1", lookback_days=14)
    res2 = run_idle_resource_agent(db, account_id="demo-123456789012", region="us-east-1", lookback_days=14)
    assert res2["recommendations_created"] == 0