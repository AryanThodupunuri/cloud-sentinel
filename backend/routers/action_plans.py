from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from core.database import get_db, ActionPlan, OptimizationRecommendation
from services.action_plan_service import create_action_plan_from_recommendation
from datetime import datetime

router = APIRouter(prefix="/api", tags=["action_plans"])


class ActionPlanResponse(BaseModel):
    id: int
    recommendation_id: int
    account_id: str
    action_type: str
    status: str
    risk_level: Optional[str]
    proposed_change: Optional[dict]
    rollback_plan: Optional[str]
    approval_required: bool
    external_url: Optional[str]
    created_at: datetime
    updated_at: datetime


@router.post("/recommendations/{recommendation_id}/action-plan")
def create_action_plan(recommendation_id: int, db: Session = Depends(get_db)):
    try:
        ap = create_action_plan_from_recommendation(db, recommendation_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    return {
        "id": ap.id,
        "recommendation_id": ap.recommendation_id,
        "account_id": ap.account_id,
        "action_type": ap.action_type,
        "status": ap.status,
        "risk_level": ap.risk_level,
        "proposed_change": ap.proposed_change,
        "rollback_plan": ap.rollback_plan,
        "approval_required": ap.approval_required,
        "external_url": ap.external_url,
        "created_at": ap.created_at,
        "updated_at": ap.updated_at,
    }


@router.get("/action-plans")
def list_action_plans(account_id: Optional[str] = None, status: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(ActionPlan)
    if account_id:
        q = q.filter(ActionPlan.account_id == account_id)
    if status:
        q = q.filter(ActionPlan.status == status)
    rows = q.order_by(ActionPlan.created_at.desc()).all()
    result = []
    for r in rows:
        # include basic recommendation context
        rec = db.query(OptimizationRecommendation).filter(OptimizationRecommendation.id == r.recommendation_id).first()
        result.append({
            "id": r.id,
            "recommendation_id": r.recommendation_id,
            "account_id": r.account_id,
            "action_type": r.action_type,
            "status": r.status,
            "risk_level": r.risk_level,
            "proposed_change": r.proposed_change,
            "rollback_plan": r.rollback_plan,
            "approval_required": r.approval_required,
            "external_url": r.external_url,
            "created_at": r.created_at,
            "updated_at": r.updated_at,
            "recommendation": {
                "resource_id": rec.resource_id if rec else None,
                "resource_type": rec.resource_type if rec else None,
                "recommendation_type": rec.recommendation_type if rec else None,
                "estimated_monthly_savings": rec.estimated_monthly_savings if rec else None,
                "source": rec.source if rec else None,
            },
        })
    return result


@router.post("/action-plans/{action_plan_id}/approve")
def approve_action_plan(action_plan_id: int, db: Session = Depends(get_db)):
    ap = db.query(ActionPlan).filter(ActionPlan.id == action_plan_id).first()
    if not ap:
        raise HTTPException(status_code=404, detail="Action plan not found")
    ap.status = "approved"
    ap.updated_at = datetime.utcnow()
    db.add(ap)
    db.commit()
    return {"success": True, "id": ap.id, "status": ap.status}


@router.post("/action-plans/{action_plan_id}/dismiss")
def dismiss_action_plan(action_plan_id: int, db: Session = Depends(get_db)):
    ap = db.query(ActionPlan).filter(ActionPlan.id == action_plan_id).first()
    if not ap:
        raise HTTPException(status_code=404, detail="Action plan not found")
    ap.status = "dismissed"
    ap.updated_at = datetime.utcnow()
    db.add(ap)
    db.commit()
    return {"success": True, "id": ap.id, "status": ap.status}
