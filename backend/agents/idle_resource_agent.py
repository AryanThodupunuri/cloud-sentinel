"""
Idle Resource Agent
- Detect underutilized EC2 instances using CloudWatch metrics and create OptimizationRecommendation entries.
"""
from typing import Optional, List, Tuple, Dict
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from core.database import OptimizationRecommendation, CloudConnection
from core import aws_session
import botocore

# Thresholds (tunable)
CPU_THRESHOLD_PERCENT = 5.0
NETWORK_THRESHOLD_BYTES_PER_HOUR = 1_000_000  # ~1 MB/hour
MIN_DATAPOINTS = 5


def _save_recommendation(db: Session, account_id: str, rec: dict) -> Tuple[bool, bool]:
    """Idempotent save: returns (created, updated)"""
    q = db.query(OptimizationRecommendation).filter(
        OptimizationRecommendation.account_id == account_id,
        OptimizationRecommendation.recommendation_type == rec.get("recommendation_type"),
        OptimizationRecommendation.source == rec.get("source", "cloudwatch_custom"),
    )
    if rec.get("resource_arn"):
        q = q.filter(OptimizationRecommendation.resource_arn == rec.get("resource_arn"))
    elif rec.get("resource_id"):
        q = q.filter(OptimizationRecommendation.resource_id == rec.get("resource_id"))

    existing = q.first()
    if existing:
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
        source=rec.get("source", "cloudwatch_custom"),
        status=rec.get("status", "open"),
        evidence=rec.get("evidence"),
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(o)
    return (True, False)


def list_running_ec2_instances(session, region_name: str) -> List[dict]:
    client = session.client("ec2", region_name=region_name)
    instances = []
    paginator = client.get_paginator("describe_instances")
    try:
        for page in paginator.paginate(Filters=[{"Name": "instance-state-name", "Values": ["running"]}]):
            for r in page.get("Reservations", []):
                for i in r.get("Instances", []):
                    tags = {t.get("Key"): t.get("Value") for t in i.get("Tags", [])} if i.get("Tags") else {}
                    instances.append({
                        "instance_id": i.get("InstanceId"),
                        "instance_type": i.get("InstanceType"),
                        "availability_zone": i.get("Placement", {}).get("AvailabilityZone"),
                        "launch_time": i.get("LaunchTime"),
                        "tags": tags,
                    })
    except botocore.exceptions.ClientError:
        raise
    return instances


def get_instance_metric_average(session, region_name: str, instance_id: str, metric_name: str, lookback_days: int) -> dict:
    client = session.client("cloudwatch", region_name=region_name)
    end_time = datetime.utcnow()
    start_time = end_time - timedelta(days=lookback_days)
    # Use hourly period to calculate per-hour averages
    period = 3600
    try:
        resp = client.get_metric_statistics(
            Namespace="AWS/EC2",
            MetricName=metric_name,
            Dimensions=[{"Name": "InstanceId", "Value": instance_id}],
            StartTime=start_time,
            EndTime=end_time,
            Period=period,
            Statistics=["Average"],
        )
    except botocore.exceptions.ClientError:
        raise

    datapoints = resp.get("Datapoints", [])
    if not datapoints:
        return {"average": 0.0, "datapoints": 0}
    # get the average of the averages
    avg = sum([d.get("Average", 0.0) for d in datapoints]) / len(datapoints)
    return {"average": float(avg), "datapoints": len(datapoints)}


def is_idle_ec2(avg_cpu: float, avg_network_in: float, avg_network_out: float, datapoint_count: int) -> bool:
    if datapoint_count < MIN_DATAPOINTS:
        return False
    if avg_cpu >= CPU_THRESHOLD_PERCENT:
        return False
    if avg_network_in >= NETWORK_THRESHOLD_BYTES_PER_HOUR:
        return False
    if avg_network_out >= NETWORK_THRESHOLD_BYTES_PER_HOUR:
        return False
    return True


def run_idle_resource_agent(db: Session, connection_id: Optional[int] = None, account_id: Optional[str] = None, region: Optional[str] = "us-east-1", lookback_days: int = 14) -> dict:
    errors: List[str] = []
    instances_scanned = 0
    idle_found = 0
    created = 0
    updated = 0
    mode = "real"

    conn = None
    if connection_id:
        conn = db.query(CloudConnection).filter(CloudConnection.id == connection_id).first()
        if conn:
            account_id = account_id or conn.account_id

    if conn and getattr(conn, "connection_status", None) == "connected" and getattr(conn, "role_arn", None):
        try:
            session = aws_session.get_assumed_role_session(conn.role_arn, conn.external_id)
            # list instances
            try:
                instances = list_running_ec2_instances(session, region)
            except botocore.exceptions.ClientError as e:
                errors.append(str(e))
                instances = []

            for inst in instances:
                instances_scanned += 1
                iid = inst.get("instance_id")
                try:
                    cpu = get_instance_metric_average(session, region, iid, "CPUUtilization", lookback_days)
                    net_in = get_instance_metric_average(session, region, iid, "NetworkIn", lookback_days)
                    net_out = get_instance_metric_average(session, region, iid, "NetworkOut", lookback_days)
                except botocore.exceptions.ClientError as e:
                    errors.append(f"metrics_error:{iid}:{str(e)}")
                    continue

                avg_cpu = cpu.get("average", 0.0)
                avg_net_in = net_in.get("average", 0.0)
                avg_net_out = net_out.get("average", 0.0)
                datapoints = min(cpu.get("datapoints", 0), net_in.get("datapoints", 0), net_out.get("datapoints", 0))

                if is_idle_ec2(avg_cpu, avg_net_in, avg_net_out, datapoints):
                    idle_found += 1
                    acct = account_id or (conn.account_id if conn else f"demo-{datetime.utcnow().timestamp()}")
                    rec = {
                        "resource_id": iid,
                        "resource_arn": None,
                        "resource_type": "ec2_instance",
                        "service": "EC2",
                        "region": region,
                        "recommendation_type": "idle_ec2",
                        "current_configuration": {"instance_id": iid, "instance_type": inst.get("instance_type"), "state": "running"},
                        "recommended_configuration": {"recommended_action": "Investigate, stop, downsize, or schedule this instance after owner approval"},
                        "estimated_monthly_savings": None,
                        "confidence": ("high" if avg_cpu < 1.0 and datapoints >= (lookback_days * 24 * 0.6) else "medium"),
                        "source": "cloudwatch_custom",
                        "status": "open",
                        "evidence": {"avg_cpu": avg_cpu, "avg_network_in": avg_net_in, "avg_network_out": avg_net_out, "lookback_days": lookback_days, "datapoints": datapoints},
                    }
                    try:
                        c, u = _save_recommendation(db, acct, rec)
                        if c:
                            created += 1
                        if u:
                            updated += 1
                    except Exception as e:
                        errors.append(str(e))

        except botocore.exceptions.ClientError as e:
            errors.append(str(e))
            mode = "failed"
    else:
        # demo mode
        mode = "demo"
        if not account_id:
            account_id = "demo-unknown"
        # create a demo idle instance recommendation
        instances_scanned = 1
        idle_found = 1
        rec = {
            "resource_id": "i-demo-idle001",
            "resource_arn": "arn:aws:ec2:us-east-1:demo:instance/i-demo-idle001",
            "resource_type": "ec2_instance",
            "service": "EC2",
            "region": region,
            "recommendation_type": "idle_ec2",
            "current_configuration": {"instance_id": "i-demo-idle001", "instance_type": "t3.large", "state": "running"},
            "recommended_configuration": {"recommended_action": "Investigate, stop, downsize, or schedule this instance after owner approval"},
            "estimated_monthly_savings": 35.0,
            "confidence": "medium",
            "source": "cloudwatch_custom",
            "status": "open",
            "evidence": {"avg_cpu": 1.8, "avg_network_in": 1000.0, "avg_network_out": 500.0, "lookback_days": lookback_days, "datapoints": 14},
        }
        try:
            c, u = _save_recommendation(db, account_id, rec)
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
        "region": region,
        "source": ("cloudwatch_custom" if mode == "real" else "demo"),
        "instances_scanned": instances_scanned,
        "idle_instances_found": idle_found,
        "recommendations_created": created,
        "recommendations_updated": updated,
        "errors": errors,
    }
