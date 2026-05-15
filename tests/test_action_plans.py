from backend.core.database import Base, OptimizationRecommendation, ActionPlan
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.services.action_plan_service import create_action_plan_from_recommendation
from backend.routers.action_plans import create_action_plan, list_action_plans, approve_action_plan, dismiss_action_plan


def make_session():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    return Session()


def seed_recommendation(db, rtype="idle_ec2", account_id="demo-123"):
    rec = OptimizationRecommendation(
        account_id=account_id,
        resource_id="i-abc123",
        resource_arn=None,
        resource_type="ec2_instance",
        service="EC2",
        region="us-east-1",
        recommendation_type=rtype,
        current_configuration={"instanceType": "t3.large"},
        recommended_configuration={"instanceType": "t3.medium"},
        estimated_monthly_savings=25.0,
        confidence="medium",
        source="demo",
        status="open",
    )
    db.add(rec)
    db.commit()
    return rec


def test_create_action_plan_from_ec2_rightsizing():
    db = make_session()
    rec = seed_recommendation(db, rtype="ec2_rightsizing")
    ap = create_action_plan_from_recommendation(db, rec.id)
    assert ap.action_type == "REVIEW_EC2_RIGHTSIZING"


def test_create_action_plan_from_idle_ec2():
    db = make_session()
    rec = seed_recommendation(db, rtype="idle_ec2")
    ap = create_action_plan_from_recommendation(db, rec.id)
    assert ap.action_type == "REVIEW_IDLE_EC2"


def test_create_action_plan_idempotent():
    db = make_session()
    rec = seed_recommendation(db, rtype="idle_ec2")
    ap1 = create_action_plan_from_recommendation(db, rec.id)
    ap2 = create_action_plan_from_recommendation(db, rec.id)
    assert ap1.id == ap2.id


def test_approve_and_dismiss_endpoints():
    db = make_session()
    rec = seed_recommendation(db, rtype="idle_ec2")
    ap = create_action_plan_from_recommendation(db, rec.id)
    # Call router helpers directly (they expect a db session via dependency injection normally)
    resp = approve_action_plan(ap.id, db=db)
    assert resp["status"] == "approved"
    resp2 = dismiss_action_plan(ap.id, db=db)
    assert resp2["status"] == "dismissed"


def test_missing_recommendation_404():
    db = make_session()
    try:
        create_action_plan_from_recommendation(db, 9999)
        assert False, "Should have raised"
    except ValueError:
        assert True
