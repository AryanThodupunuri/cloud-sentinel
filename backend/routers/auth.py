"""
Auth Router - AWS cloud connection via STS credential validation
POST /api/auth/aws/connect
GET  /api/auth/status
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from core.database import get_db, CloudConnection
from core import aws_session
from datetime import datetime
import uuid

router = APIRouter(prefix="/api/auth", tags=["auth"])


class AWSConnectRequest(BaseModel):
    # For v2 we accept a Role ARN and optional External ID. If omitted, demo mode is used.
    role_arn: str = None
    external_id: str = None
    region: str = "us-east-1"


class AWSConnectResponse(BaseModel):
    success: bool
    connection_id: int
    account_id: str
    message: str


@router.post("/aws/connect", response_model=AWSConnectResponse)
def connect_aws(request: AWSConnectRequest, db: Session = Depends(get_db)):
    """
    Validate AWS credentials using STS GetCallerIdentity.
    If valid, store in DB and return connection_id.
    """
    # Default to demo if no role_arn provided
    if not request.role_arn:
        print("[AUTH] No Role ARN provided — using DEMO mode")
        account_id = "demo-123456789012"
        # Create or update a demo connection entry
        existing = db.query(CloudConnection).filter(CloudConnection.provider == "aws").first()
        if existing:
            existing.connection_status = "demo"
            existing.region = request.region
            existing.updated_at = datetime.utcnow()
            db.commit()
            conn_id = existing.id
        else:
            conn = CloudConnection(
                provider="aws",
                account_id=account_id,
                region=request.region,
                connection_status="demo",
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            db.add(conn)
            db.commit()
            db.refresh(conn)
            conn_id = conn.id

        return AWSConnectResponse(
            success=True,
            connection_id=conn_id,
            account_id=account_id,
            message="Demo mode enabled. No AWS Role ARN provided.",
        )

    # Ensure there's an external_id (used by the customer when creating the IAM trust)
    external_id = request.external_id or str(uuid.uuid4())

    # Validate the role by attempting to assume it
    result = aws_session.validate_assumed_role(request.role_arn, external_id)
    if not result.get("status"):
        # Clear error for user
        err = result.get("error", "Could not assume role")
        raise HTTPException(status_code=400, detail=f"AssumeRole failed: {err}")

    account_id = result.get("account_id")

    # Store or update the connection metadata without persisting raw keys
    existing = db.query(CloudConnection).filter(CloudConnection.role_arn == request.role_arn).first()
    if existing:
        existing.account_id = account_id
        existing.external_id = external_id
        existing.connection_status = "connected"
        existing.region = request.region
        existing.last_validated_at = datetime.utcnow()
        existing.updated_at = datetime.utcnow()
        db.commit()
        conn_id = existing.id
    else:
        conn = CloudConnection(
            provider="aws",
            account_id=account_id,
            region=request.region,
            role_arn=request.role_arn,
            external_id=external_id,
            connection_status="connected",
            last_validated_at=datetime.utcnow(),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(conn)
        db.commit()
        db.refresh(conn)
        conn_id = conn.id

    return AWSConnectResponse(
        success=True,
        connection_id=conn_id,
        account_id=account_id,
        message=f"Successfully validated Role ARN for AWS account {account_id} in {request.region}",
    )


@router.get("/status")
def get_auth_status(db: Session = Depends(get_db)):
    """Return all connected cloud accounts."""
    connections = db.query(CloudConnection).filter(
        CloudConnection.connection_status.in_(["connected", "demo"])
    ).all()
    return [
        {
            "id": c.id,
            "provider": c.provider,
            "account_id": c.account_id,
            "region": c.region,
            "connection_status": c.connection_status,
            "role_arn": getattr(c, "role_arn", None),
            "external_id": getattr(c, "external_id", None),
            "last_validated_at": getattr(c, "last_validated_at", None),
        }
        for c in connections
    ]
