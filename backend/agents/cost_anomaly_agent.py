"""
Cost Anomaly Agent
- Loads CostDailyRecord grouped by account/service
- Computes rolling baselines and flags anomalies using rules
- Saves CostAnomaly rows idempotently
"""
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from core.database import CostDailyRecord, CostAnomaly
from collections import defaultdict
import statistics


def run_cost_anomaly_agent(db: Session, account_id: str = None) -> dict:
    """Scan cost records and persist anomalies. Returns summary."""
    # Load records grouped by account_id and service_name
    query = db.query(CostDailyRecord)
    if account_id:
        query = query.filter(CostDailyRecord.account_id == account_id)
    rows = query.order_by(CostDailyRecord.account_id, CostDailyRecord.service_name, CostDailyRecord.date).all()

    grouped = defaultdict(list)
    for r in rows:
        key = (r.account_id, r.service_name)
        grouped[key].append(r)

    anomalies_added = 0
    anomalies_skipped = 0

    for (acct, svc), recs in grouped.items():
        if len(recs) < 8:
            # Not enough history for meaningful detection
            continue
        # Ensure sorted by date
        recs = sorted(recs, key=lambda x: x.date)
        # Take most recent day as candidate
        candidate = recs[-1]
        current_cost = candidate.cost
        # Build windows excluding current day
        prev_7 = [r.cost for r in recs[-8:-1]] if len(recs) >= 8 else [r.cost for r in recs[:-1]]
        prev_30 = [r.cost for r in recs[-31:-1]] if len(recs) >= 31 else [r.cost for r in recs[:-1]]

        avg_7 = statistics.mean(prev_7) if prev_7 else 0.0
        avg_30 = statistics.mean(prev_30) if prev_30 else 0.0
        std_30 = statistics.pstdev(prev_30) if prev_30 else 0.0

        percent_increase = ((current_cost - avg_30) / avg_30 * 100.0) if avg_30 > 0 else 0.0
        z_score = ((current_cost - avg_30) / std_30) if std_30 > 0 else 0.0

        is_anomaly = False
        if std_30 > 0 and z_score >= 2.0:
            is_anomaly = True
        if avg_7 > 0 and current_cost >= avg_7 * 1.5:
            is_anomaly = True
        if avg_30 > 0 and current_cost >= avg_30 * 1.5:
            is_anomaly = True

        if not is_anomaly:
            anomalies_skipped += 1
            continue

        # Determine severity
        severity = "low"
        if percent_increase >= 200 or z_score >= 3:
            severity = "high"
        elif percent_increase >= 100 or z_score >= 2:
            severity = "medium"
        elif percent_increase >= 50:
            severity = "low"

        explanation = (f"{svc} spend reached ${current_cost:.2f} on {candidate.date}, compared with a 30-day baseline of ${avg_30:.2f}. "
                       f"This is a {percent_increase:.0f}% increase with a z-score of {z_score:.2f}.")

        # Idempotent insert: account_id + service_name + anomaly_date
        existing = db.query(CostAnomaly).filter(
            CostAnomaly.account_id == acct,
            CostAnomaly.service_name == svc,
            CostAnomaly.anomaly_date == candidate.date,
        ).first()
        if existing:
            # Update if metrics changed
            updated = False
            if abs(existing.current_cost - current_cost) > 0.0001:
                existing.current_cost = current_cost
                updated = True
            if abs(existing.baseline_cost - avg_30) > 0.0001:
                existing.baseline_cost = avg_30
                updated = True
            existing.percent_increase = percent_increase
            existing.z_score = z_score
            existing.severity = severity
            existing.explanation = explanation
            if updated:
                db.add(existing)
            continue

        anomaly = CostAnomaly(
            account_id=acct,
            service_name=svc,
            anomaly_date=candidate.date,
            current_cost=current_cost,
            baseline_cost=avg_30,
            percent_increase=percent_increase,
            z_score=z_score,
            severity=severity,
            explanation=explanation,
            source="rolling_baseline",
            created_at=datetime.utcnow(),
        )
        db.add(anomaly)
        anomalies_added += 1

    db.commit()
    return {"agent": "Cost Anomaly Agent", "new_anomalies": anomalies_added, "skipped": anomalies_skipped}
