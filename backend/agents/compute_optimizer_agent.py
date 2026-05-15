"""
Compute Optimizer Agent
- Provides integration with AWS Compute Optimizer (EC2 and EBS recommendations)
- Supports demo mode when no AWS connection is available
"""
from typing import Optional, Tuple, List
from sqlalchemy.orm import Session
from core.database import OptimizationRecommendation, CloudConnection
from datetime import datetime
from core import aws_session
import botocore
import json


def _save_recommendation(db: Session, account_id: str, rec: dict) -> Tuple[bool, bool]:
    """Idempotent save: returns (created, updated)"""
    # Lookup by account_id + resource_arn/resource_id + recommendation_type + source
    q = db.query(OptimizationRecommendation).filter(
        OptimizationRecommendation.account_id == account_id,
        OptimizationRecommendation.recommendation_type == rec.get("recommendation_type"),
        OptimizationRecommendation.source == rec.get("source", "compute_optimizer"),
    )
    if rec.get("resource_arn"):
        q = q.filter(OptimizationRecommendation.resource_arn == rec.get("resource_arn"))
    elif rec.get("resource_id"):
        q = q.filter(OptimizationRecommendation.resource_id == rec.get("resource_id"))

    existing = q.first()
    if existing:
        # update fields if changed
        updated = False
        for k, v in rec.items():
            if hasattr(existing, k) and getattr(existing, k) != v:
                setattr(existing, k, v)
                updated = True
        if updated:
            existing.updated_at = datetime.utcnow()
            db.add(existing)
            return (False, True)
        return (False, False)

    # create
    o = OptimizationRecommendation(
        account_id=account_id,
        resource_id=rec.get("resource_id"),
        resource_arn=rec.get("resource_arn"),
        resource_type=rec.get("resource_type"),
        service=rec.get("service"),
        region=rec.get("region"),
        recommendation_type=rec.get("recommendation_type"),
        current_configuration=rec.get("current_configuration"),
        recommended_configuration=rec.get("recommended_configuration"),
        estimated_monthly_savings=rec.get("estimated_monthly_savings"),
        confidence=rec.get("confidence"),
        source=rec.get("source", "compute_optimizer"),
        status=rec.get("status", "open"),
        evidence=rec.get("evidence"),
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(o)
    return (True, False)


def _parse_instance_arn(arn: str) -> str:
    # arn:aws:ec2:region:account:instance/i-01234567
    try:
        return arn.split("/")[-1]
    except Exception:
        return arn


def get_ec2_instance_recommendations(session) -> List[dict]:
    client = session.client("compute-optimizer")
    paginator = client.get_paginator("get_ec2_instance_recommendations")
    results = []
    for page in paginator.paginate():
        for item in page.get("instanceRecommendations", []):
            try:
                arn = item.get("instanceArn")
                resource_id = _parse_instance_arn(arn) if arn else None
                finding = item.get("finding")
                current = {
                    "instanceType": item.get("currentInstanceType"),
                    "finding": finding,
                }
                options = item.get("recommendationOptions", [])
                top = options[0] if options else None
                rec = {
                    "resource_arn": arn,
                    "resource_id": resource_id,
                    "resource_type": "ec2_instance",
                    "service": "EC2",
                    "region": item.get("location"),
                    "recommendation_type": "ec2_rightsizing",
                    "current_configuration": current,
                    "recommended_configuration": top,
                    "estimated_monthly_savings": (top.get("estimatedMonthlySavings", {}).get("value") if top else None),
                    "confidence": item.get("utilizationMetrics", [{}])[0].get("statistic") if item.get("utilizationMetrics") else None,
                    "source": "compute_optimizer",
                    "evidence": item,
                }
                results.append(rec)
            except Exception:
                continue
    return results


def get_ebs_volume_recommendations(session) -> List[dict]:
    client = session.client("compute-optimizer")
    paginator = client.get_paginator("get_ebs_volume_recommendations")
    results = []
    for page in paginator.paginate():
        for item in page.get("volumeRecommendations", []):
            try:
                arn = item.get("volumeArn")
                vid = arn.split("/")[-1] if arn else None
                current = item.get("currentConfiguration")
                options = item.get("recommendationOptions", [])
                top = options[0] if options else None
                rec = {
                    "resource_arn": arn,
                    "resource_id": vid,
                    "resource_type": "ebs_volume",
                    "service": "EBS",
                    "region": item.get("location"),
                    "recommendation_type": "ebs_rightsizing",
                    "current_configuration": current,
                    "recommended_configuration": top,
                    "estimated_monthly_savings": (top.get("estimatedMonthlySavings", {}).get("value") if top else None),
                    "confidence": None,
                    "source": "compute_optimizer",
                    "evidence": item,
                }
                results.append(rec)
            except Exception:
                continue
    return results


def generate_demo_recommendations() -> List[dict]:
    # Return a few demo recs
    return [
        {
            "resource_id": "i-demo123",
            "resource_arn": "arn:aws:ec2:us-east-1:demo:instance/i-demo123",
            "resource_type": "ec2_instance",
            "service": "EC2",
            "region": "us-east-1",
            "recommendation_type": "ec2_rightsizing",
            "current_configuration": {"instanceType": "m5.large", "finding": "Overprovisioned"},
            "recommended_configuration": {"instanceType": "t3.medium", "estimatedMonthlySavings": {"value": 40.0, "unit": "USD"}},
            "estimated_monthly_savings": 40.0,
            "confidence": "medium",
            "source": "demo",
            "evidence": {"note": "demo spike-based recommendation"},
        },
        {
            "resource_id": "vol-demo123",
            "resource_arn": "arn:aws:ec2:us-east-1:demo:volume/vol-demo123",
            "resource_type": "ebs_volume",
            "service": "EBS",
            "region": "us-east-1",
            "recommendation_type": "ebs_rightsizing",
            "current_configuration": {"volumeType": "gp2"},
            "recommended_configuration": {"volumeType": "gp3", "estimatedMonthlySavings": {"value": 12.0, "unit": "USD"}},
            "estimated_monthly_savings": 12.0,
            "confidence": "low",
            "source": "demo",
            "evidence": {"note": "demo ebs recommendation"},
        },
        {
            "resource_id": "lambda-demo-1",
            "resource_arn": "arn:aws:lambda:us-east-1:demo:function:demo-api-handler",
            "resource_type": "lambda_function",
            "service": "Lambda",
            "region": "us-east-1",
            "recommendation_type": "lambda_memory",
            "current_configuration": {"memory": 1024},
            "recommended_configuration": {"memory": 512, "estimatedMonthlySavings": {"value": 15.0, "unit": "USD"}},
            "estimated_monthly_savings": 15.0,
            "confidence": "medium",
            "source": "demo",
            "evidence": {"note": "demo lambda memory recommendation"},
        },
    ]


def run_compute_optimizer_agent(db: Session, connection_id: Optional[int] = None, account_id: Optional[str] = None) -> dict:
    """Run Compute Optimizer scan. Returns summary dict."""
    errors = []
    created = 0
    updated = 0
    mode = "real"

    # Resolve account_id from connection if provided
    conn = None
    if connection_id:
        conn = db.query(CloudConnection).filter(CloudConnection.id == connection_id).first()
        if conn:
            account_id = conn.account_id or account_id

    recs = []
    if conn and getattr(conn, "connection_status", None) == "connected" and getattr(conn, "role_arn", None):
        # real AWS mode
        try:
            session = aws_session.get_assumed_role_session(conn.role_arn, conn.external_id)
            # EC2
            try:
                ec2_recs = get_ec2_instance_recommendations(session)
                recs.extend(ec2_recs)
            except botocore.exceptions.ClientError as e:
                errors.append(str(e))
            # EBS
            try:
                ebs_recs = get_ebs_volume_recommendations(session)
                recs.extend(ebs_recs)
            except botocore.exceptions.ClientError as e:
                errors.append(str(e))
        except botocore.exceptions.ClientError as e:
            errors.append(str(e))
            mode = "failed"
    else:
        # demo mode
        recs = generate_demo_recommendations()
        mode = "demo"
        if not account_id:
            account_id = "demo-unknown"

    # Persist recs idempotently
    for r in recs:
        # ensure account_id exists
        acct = account_id or (conn.account_id if conn else f"demo-{datetime.utcnow().timestamp()}")
        try:
            c, u = _save_recommendation(db, acct, r)
            if c:
                created += 1
            if u:
                updated += 1
        except Exception as e:
            errors.append(str(e))

    db.commit()

    status = "completed"
    if mode == "demo":
        status = "demo_mode"
    elif errors and created == 0 and updated == 0:
        status = "failed"
    elif errors:
        status = "partial_failure"

    return {
        "status": status,
        "account_id": account_id or (conn.account_id if conn else None),
        "source": ("compute_optimizer" if mode == "real" else "demo"),
        "recommendations_created": created,
        "recommendations_updated": updated,
        "errors": errors,
    }
