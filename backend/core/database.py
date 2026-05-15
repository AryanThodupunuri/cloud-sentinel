from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Text, Boolean, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/cloudsentinel")

# Try PostgreSQL first, fallback to SQLite for easier setup
try:
    engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args={})
    # Test connection
    with engine.connect() as conn:
        pass
except Exception:
    print("[INFO] PostgreSQL not available, falling back to SQLite")
    engine = create_engine("sqlite:///./cloudsentinel.db", connect_args={"check_same_thread": False})

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class CloudConnection(Base):
    __tablename__ = "cloud_connections"
    id = Column(Integer, primary_key=True, index=True)
    provider = Column(String(50), default="aws")
    account_id = Column(String(100), nullable=True)
    region = Column(String(50), default="us-east-1")
    # For v2 we store only AssumeRole metadata. Raw AWS access keys are no longer stored.
    role_arn = Column(String(500), nullable=True)
    external_id = Column(String(200), nullable=True)
    # connection_status replaces previous 'status' column name to be more explicit
    connection_status = Column(String(20), default="connected")
    last_validated_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


class Anomaly(Base):
    __tablename__ = "anomalies"
    id = Column(Integer, primary_key=True, index=True)
    service = Column(String(100))
    resource = Column(String(200))
    detected = Column(String(100))
    spike = Column(String(50))
    baseline = Column(String(50))
    current_cost = Column(String(50))
    status = Column(String(20), default="OPEN")
    explanation = Column(Text)
    severity = Column(String(20), default="WARNING")
    created_at = Column(DateTime, default=datetime.utcnow)


class Recommendation(Base):
    __tablename__ = "recommendations"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200))
    description = Column(Text)
    potential_savings = Column(String(50))
    difficulty = Column(String(20))
    status = Column(String(20), default="PENDING")
    category = Column(String(50), default="optimization")
    created_at = Column(DateTime, default=datetime.utcnow)


class AgentLog(Base):
    __tablename__ = "agent_logs"
    id = Column(Integer, primary_key=True, index=True)
    agent_type = Column(String(100))
    action = Column(Text)
    result = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class ChatHistory(Base):
    __tablename__ = "chat_history"
    id = Column(Integer, primary_key=True, index=True)
    role = Column(String(20))  # 'user' or 'ai'
    text = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class CostData(Base):
    __tablename__ = "cost_data"
    id = Column(Integer, primary_key=True, index=True)
    provider = Column(String(50), default="aws")
    service = Column(String(100))
    amount = Column(Float, default=0.0)
    unit = Column(String(20), default="USD")
    start_date = Column(String(20))
    end_date = Column(String(20))
    raw_data = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class CostDailyRecord(Base):
    __tablename__ = "cost_daily_records"
    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(String(100), index=True)
    service_name = Column(String(200), index=True)
    date = Column(String(20), index=True)  # YYYY-MM-DD
    cost = Column(Float, default=0.0)
    currency = Column(String(10), default="USD")
    source = Column(String(50), default="cost_explorer")
    created_at = Column(DateTime, default=datetime.utcnow)


class CostAnomaly(Base):
    __tablename__ = "cost_anomalies"
    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(String(100), index=True)
    service_name = Column(String(200), index=True)
    anomaly_date = Column(String(20), index=True)
    current_cost = Column(Float, default=0.0)
    baseline_cost = Column(Float, default=0.0)
    percent_increase = Column(Float, default=0.0)
    z_score = Column(Float, default=0.0)
    severity = Column(String(20), default="low")
    explanation = Column(Text)
    source = Column(String(50), default="rolling_baseline")
    created_at = Column(DateTime, default=datetime.utcnow)
    scan_job_id = Column(String(100), nullable=True)


class OptimizationRecommendation(Base):
    __tablename__ = "optimization_recommendations"
    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(String(100), index=True)
    resource_id = Column(String(200), index=True, nullable=True)
    resource_arn = Column(String(500), index=True, nullable=True)
    resource_type = Column(String(100))
    service = Column(String(100))
    region = Column(String(50), nullable=True)
    recommendation_type = Column(String(100))
    current_configuration = Column(JSON, nullable=True)
    recommended_configuration = Column(JSON, nullable=True)
    estimated_monthly_savings = Column(Float, nullable=True)
    confidence = Column(String(50), nullable=True)
    source = Column(String(50), default="compute_optimizer")
    status = Column(String(50), default="open")
    evidence = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    Base.metadata.create_all(bind=engine)
    print("[INFO] Database tables created successfully")
