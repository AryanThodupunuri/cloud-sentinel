"""
Anomalies Router
GET  /api/anomalies
POST /api/anomalies/{id}/acknowledge
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from core.database import get_db, Anomaly
from core.database import get_db, Anomaly, CostAnomaly, CostDailyRecord, CloudConnection
from agents.cost_anomaly_agent import run_cost_anomaly_agent
from fastapi import Body
from pydantic import BaseModel

router = APIRouter(prefix="/api/anomalies", tags=["anomalies"])


@router.get("")
def list_anomalies(db: Session = Depends(get_db)):
    anomalies = db.query(Anomaly).order_by(Anomaly.created_at.desc()).all()
    return [
        {
            "id": str(a.id),
            "service": a.service,
            "resource": a.resource,
            "detected": a.detected,
            "spike": a.spike,
            "baseline": a.baseline,
            "current": a.current_cost,
            "status": a.status,
            "explanation": a.explanation,
            "severity": a.severity,
        }
        for a in anomalies
    ]


@router.post("/{anomaly_id}/acknowledge")
def acknowledge_anomaly(anomaly_id: int, db: Session = Depends(get_db)):
    anomaly = db.query(Anomaly).filter(Anomaly.id == anomaly_id).first()
    if not anomaly:
        raise HTTPException(status_code=404, detail="Anomaly not found")
    anomaly.status = "ACKNOWLEDGED"
    db.commit()
    return {"success": True, "id": anomaly_id, "status": "ACKNOWLEDGED"}



class DetectRequest(BaseModel):
    account_id: str = None
    connection_id: int = None


@router.post("/detect")
def detect_anomalies(payload: DetectRequest = Body(...), db: Session = Depends(get_db)):
    # If connection_id provided and demo -> use connection account_id
    account_id = payload.account_id
    if payload.connection_id:
        conn = db.query(CloudConnection).filter(CloudConnection.id == payload.connection_id).first()
        if conn:
            account_id = conn.account_id

    result = run_cost_anomaly_agent(db, account_id)
    return result


@router.get("/history")
def anomaly_history(account_id: str = None, db: Session = Depends(get_db)):
    if not account_id:
        raise HTTPException(status_code=400, detail="account_id query param required")
    rows = db.query(CostAnomaly).filter(CostAnomaly.account_id == account_id).order_by(CostAnomaly.anomaly_date.desc()).all()
    return [
        {
            "id": r.id,
            "service": r.service_name,
            "anomaly_date": r.anomaly_date,
            "current_cost": r.current_cost,
            "baseline_cost": r.baseline_cost,
            "percent_increase": r.percent_increase,
            "z_score": r.z_score,
            "severity": r.severity,
            "explanation": r.explanation,
        }
        for r in rows
    ]
