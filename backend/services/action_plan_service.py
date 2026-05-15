from sqlalchemy.orm import Session
from core.database import OptimizationRecommendation, ActionPlan
from datetime import datetime
from typing import Optional


def _determine_risk_for_idle(confidence: Optional[str], evidence: dict) -> str:
    # Simple heuristic: use confidence and datapoints to set risk
    datapoints = evidence.get("datapoints") if isinstance(evidence, dict) else None
    if confidence == "high" and datapoints and datapoints >= 10:
        return "low"
    if not datapoints or datapoints < 5:
        return "high"
    return "medium"


def create_action_plan_from_recommendation(db: Session, recommendation_id: int) -> ActionPlan:
    rec = db.query(OptimizationRecommendation).filter(OptimizationRecommendation.id == recommendation_id).first()
    if not rec:
        raise ValueError("Recommendation not found")

    # Idempotent: find existing action plan for this recommendation that is not dismissed
    existing = db.query(ActionPlan).filter(ActionPlan.recommendation_id == recommendation_id, ActionPlan.status != "dismissed").first()
    if existing:
        # Update timestamp and proposed_change if needed
        existing.updated_at = datetime.utcnow()
        db.add(existing)
        db.commit()
        return existing

    # Build action plan based on recommendation_type
    rtype = (rec.recommendation_type or "").lower()
    ap = ActionPlan(
        recommendation_id=rec.id,
        account_id=rec.account_id,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )

    if rtype == "ec2_rightsizing":
        ap.action_type = "REVIEW_EC2_RIGHTSIZING"
        ap.risk_level = "medium"
        ap.proposed_change = {
            "resource_id": rec.resource_id,
            "resource_type": rec.resource_type,
            "current_configuration": rec.current_configuration,
            "recommended_configuration": rec.recommended_configuration,
            "estimated_monthly_savings": rec.estimated_monthly_savings,
            "source": rec.source,
        }
        ap.rollback_plan = "Restore the previous EC2 instance type and redeploy the infrastructure change if performance or availability is impacted."
        ap.approval_required = True
    elif rtype == "idle_ec2":
        ap.action_type = "REVIEW_IDLE_EC2"
        # risk based on evidence
        evidence = rec.evidence or {}
        ap.risk_level = _determine_risk_for_idle(rec.confidence, evidence)
        ap.proposed_change = {
            "resource_id": rec.resource_id,
            "current_configuration": rec.current_configuration,
            "evidence": rec.evidence,
            "recommended_action": "Investigate owner, stop during off-hours, downsize, or schedule shutdown after approval",
        }
        ap.rollback_plan = "Restart the instance or revert the scheduling/rightsizing change if the workload is still required."
        ap.approval_required = True
    elif rtype == "ebs_rightsizing":
        ap.action_type = "REVIEW_EBS_OPTIMIZATION"
        ap.risk_level = "medium"
        ap.proposed_change = {
            "resource_id": rec.resource_id,
            "current_configuration": rec.current_configuration,
            "recommended_configuration": rec.recommended_configuration,
            "estimated_monthly_savings": rec.estimated_monthly_savings,
        }
        ap.rollback_plan = "Restore the previous EBS volume configuration from infrastructure code or backup if performance is impacted."
        ap.approval_required = True
    elif "lambda" in rtype:
        ap.action_type = "REVIEW_LAMBDA_MEMORY_OPTIMIZATION"
        ap.risk_level = "low"
        ap.proposed_change = {
            "resource_id": rec.resource_id,
            "current_configuration": rec.current_configuration,
            "recommended_configuration": rec.recommended_configuration,
        }
        ap.rollback_plan = "Restore the previous Lambda memory allocation if latency, timeout rate, or error rate increases."
        ap.approval_required = True
    else:
        ap.action_type = "REVIEW_RECOMMENDATION"
        ap.risk_level = "medium"
        ap.proposed_change = {
            "resource_id": rec.resource_id,
            "current_configuration": rec.current_configuration,
            "recommended_configuration": rec.recommended_configuration,
            "evidence": rec.evidence,
        }
        ap.rollback_plan = "Revert to the previous configuration if the change causes reliability, performance, or cost issues."
        ap.approval_required = True

    db.add(ap)
    db.commit()
    return ap
