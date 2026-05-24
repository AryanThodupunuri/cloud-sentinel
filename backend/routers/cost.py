from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from core.database import get_db, CloudConnection, CostDailyRecord
from core import aws_session
from services.cost_explorer_service import fetch_daily_costs, generate_demo_daily_costs
from agents.cost_anomaly_agent import run_cost_anomaly_agent

router = APIRouter(prefix="/api/cost", tags=["cost"])


class IngestRequest(BaseModel):
    connection_id: Optional[int] = None
    days_back: int = 90
    run_anomaly_detection: bool = False


@router.post("/ingest-history")
def ingest_history(req: IngestRequest, db: Session = Depends(get_db)):
    days = req.days_back or 90
    end = datetime.utcnow().date()
    start = end - timedelta(days=days)

    # Resolve connection
    mode = "demo"
    account_id = "demo-unknown"
    records = []

    if req.connection_id:
        conn = db.query(CloudConnection).filter(CloudConnection.id == req.connection_id).first()
        if not conn:
            raise HTTPException(status_code=404, detail="Connection not found")
        account_id = conn.account_id or account_id
        if getattr(conn, 'connection_status', None) == 'connected' and getattr(conn, 'role_arn', None):
            # real mode
            mode = "real"
            session = aws_session.get_assumed_role_session(conn.role_arn, conn.external_id)
            records = fetch_daily_costs(session, start.isoformat(), end.isoformat())
        else:
            # demo for this connection
            records = generate_demo_daily_costs(days)
    else:
        # no connection -> demo
        records = generate_demo_daily_costs(days)

    # Upsert records into CostDailyRecord (idempotent)
    ingested = 0
    updated = 0
    for r in records:
        existing = db.query(CostDailyRecord).filter(
            CostDailyRecord.account_id == account_id,
            CostDailyRecord.service_name == r["service_name"],
            CostDailyRecord.date == r["date"],
        ).first()
        if existing:
            # update if different
            if abs(existing.cost - r["cost"]) > 0.0001:
                existing.cost = r["cost"]
                existing.currency = r.get("currency", existing.currency)
                db.add(existing)
                updated += 1
        else:
            rec = CostDailyRecord(
                account_id=account_id,
                service_name=r["service_name"],
                date=r["date"],
                cost=r["cost"],
                currency=r.get("currency", "USD"),
                source="demo" if mode == "demo" else "cost_explorer",
            )
            db.add(rec)
            ingested += 1

    db.commit()

    result = {
        "records_ingested": ingested,
        "records_updated": updated,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "account_id": account_id,
        "mode": mode,
    }

    # Optionally run anomaly detection after ingestion
    if getattr(req, "run_anomaly_detection", False):
        try:
            anomaly_result = run_cost_anomaly_agent(db, account_id)
        except Exception as e:
            anomaly_result = {"error": str(e)}
        result["anomaly_detection"] = anomaly_result

    return result


@router.get("/history")
def get_history(account_id: str = None, db: Session = Depends(get_db)):
    if not account_id:
        raise HTTPException(status_code=400, detail="account_id query param required")
    rows = db.query(CostDailyRecord).filter(CostDailyRecord.account_id == account_id).order_by(CostDailyRecord.date).all()
    return [
        {
            "date": r.date,
            "service": r.service_name,
            "cost": r.cost,
            "currency": r.currency,
            "source": r.source,
        }
        for r in rows
    ]
