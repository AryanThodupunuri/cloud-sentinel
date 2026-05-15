"""
Recommendations Router
GET  /api/recommendations
POST /api/recommendations/{id}/apply
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from core.database import get_db, Recommendation, AgentLog
from core.database import get_db, Recommendation, AgentLog, OptimizationRecommendation, CloudConnection
from pydantic import BaseModel
from typing import Optional
from agents.compute_optimizer_agent import run_compute_optimizer_agent

router = APIRouter(prefix="/api/recommendations", tags=["recommendations"])


@router.get("")
def list_recommendations(db: Session = Depends(get_db)):
    recs = db.query(Recommendation).order_by(Recommendation.created_at.desc()).all()
    return [
        {
            "id": str(r.id),
            "title": r.title,
            "description": r.description,
            "potentialSavings": r.potential_savings,
            "difficulty": r.difficulty,
            "status": r.status,
            "category": r.category,
        }
        for r in recs
    ]


@router.post("/{rec_id}/apply")
def apply_recommendation(rec_id: int, db: Session = Depends(get_db)):
    rec = db.query(Recommendation).filter(Recommendation.id == rec_id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    rec.status = "APPLIED"
    db.add(AgentLog(
        agent_type="Optimization Agent",
        action=f"Applied recommendation: {rec.title}",
        result=f"Estimated savings: {rec.potential_savings}",
    ))
    db.commit()
    return {"success": True, "id": rec_id, "status": "APPLIED"}


class ComputeScanRequest(BaseModel):
    connection_id: Optional[int] = None
    account_id: Optional[str] = None


@router.post("/compute-optimizer/scan")
def scan_compute_optimizer(req: ComputeScanRequest, db: Session = Depends(get_db)):
    # Prefer connection_id; agent resolves account_id if needed
    result = run_compute_optimizer_agent(db, connection_id=req.connection_id, account_id=req.account_id)
    return result


@router.get("/history")
def recommendations_history(account_id: str = None, source: Optional[str] = None, status: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(OptimizationRecommendation)
    if account_id:
        q = q.filter(OptimizationRecommendation.account_id == account_id)
    if source:
        q = q.filter(OptimizationRecommendation.source == source)
    if status:
        q = q.filter(OptimizationRecommendation.status == status)
    rows = q.order_by(OptimizationRecommendation.created_at.desc()).all()
    return [
        {
            "id": r.id,
            "account_id": r.account_id,
            "resource_id": r.resource_id,
            "resource_arn": r.resource_arn,
            "resource_type": r.resource_type,
            "service": r.service,
            "region": r.region,
            "recommendation_type": r.recommendation_type,
            "current_configuration": r.current_configuration,
            "recommended_configuration": r.recommended_configuration,
            "estimated_monthly_savings": r.estimated_monthly_savings,
            "confidence": r.confidence,
            "source": r.source,
            "status": r.status,
            "evidence": r.evidence,
            "created_at": r.created_at,
        }
        for r in rows
    ]
