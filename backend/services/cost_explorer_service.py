"""
Cost Explorer service helpers
- fetch_daily_costs(session: boto3.Session, start_date: date, end_date: date) -> list[dict]

Normalizes AWS Cost Explorer get_cost_and_usage DAILY response into list of records:
{ "date": "YYYY-MM-DD", "service_name": "Amazon EC2", "cost": 12.34, "currency": "USD" }

This module also provides a demo data generator for local/demo mode.
"""
from datetime import date, datetime, timedelta
from typing import List
import boto3
import botocore


def _parse_ce_response(response: dict) -> List[dict]:
    records = []
    results_by_time = response.get("ResultsByTime", [])
    for period in results_by_time:
        period_date = period.get("TimePeriod", {}).get("Start")
        for group in period.get("Groups", []):
            service = group.get("Keys", ["Unknown"])[0]
            metrics = group.get("Metrics", {})
            amt = metrics.get("UnblendedCost", {}).get("Amount")
            unit = metrics.get("UnblendedCost", {}).get("Unit", "USD")
            try:
                cost = float(amt) if amt is not None else 0.0
            except Exception:
                cost = 0.0
            records.append({
                "date": period_date,
                "service_name": service,
                "cost": cost,
                "currency": unit,
            })
    return records


def fetch_daily_costs(session: boto3.Session, start_date: str, end_date: str) -> List[dict]:
    """Fetch daily costs using Cost Explorer client from an assumed role session.

    start_date/end_date are strings YYYY-MM-DD
    Returns normalized records list.
    """
    try:
        client = session.client("ce")
        response = client.get_cost_and_usage(
            TimePeriod={"Start": str(start_date), "End": str(end_date)},
            Granularity="DAILY",
            Metrics=["UnblendedCost"],
            GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
        )
        return _parse_ce_response(response)
    except botocore.exceptions.ClientError as e:
        raise
    except Exception:
        raise


def generate_demo_daily_costs(days_back: int = 90) -> List[dict]:
    """Generate realistic demo daily costs for a set of services over days_back.

    Returns list of records with date/service_name/cost/currency.
    """
    import random
    # Use a fixed seed for demo data to make tests deterministic and idempotent
    random.seed(0)
    services = [
        "Amazon EC2",
        "Amazon RDS",
        "Amazon S3",
        "AWS Lambda",
        "NAT Gateway",
        "Amazon CloudWatch",
        "AWS Data Transfer",
    ]
    end = datetime.utcnow().date()
    start = end - timedelta(days=days_back)
    records = []
    for i in range(days_back):
        d = start + timedelta(days=i)
        # Simulate daily variation
        for svc in services:
            base = {
                "Amazon EC2": 1200,
                "Amazon RDS": 600,
                "Amazon S3": 300,
                "AWS Lambda": 45,
                "NAT Gateway": 80,
                "Amazon CloudWatch": 60,
                "AWS Data Transfer": 120,
            }.get(svc, 50)
            # Add noise
            fluct = random.uniform(0.7, 1.4)
            cost = round(base * fluct / 30, 2)  # approximate per-day
            # Inject a spike in the last 3 days for EC2 to ensure anomaly detection can find a spike
            if svc == "Amazon EC2" and i >= days_back - 3:
                # large spike: 3x-6x of typical
                spike_mult = random.uniform(3.0, 6.0)
                cost = round((base * spike_mult) / 30, 2)
            records.append({
                "date": d.isoformat(),
                "service_name": svc,
                "cost": cost,
                "currency": "USD",
            })
    return records
