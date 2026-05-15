"""
CloudSentinel - FastAPI Backend
Main entrypoint: initializes DB, ChromaDB, mounts all routers, sets up CORS
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os
from dotenv import load_dotenv

load_dotenv()

from core.database import init_db
from routers.auth import router as auth_router
from routers.dashboard import router as dashboard_router
from routers.anomalies import router as anomalies_router
from routers.recommendations import router as recommendations_router
from routers.query import router as query_router
from routers.agents import router as agents_router
from routers.cost import router as cost_router

app = FastAPI(
    title="CloudSentinel Backend",
    description="Multi-agent cloud cost optimization system with RAG and Groq LLM",
    version="1.0.0",
)

# CORS for frontend
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")
ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:3000",
    "http://127.0.0.1:5173",
    FRONTEND_URL,
]
# Also allow any vercel.app subdomain for preview deployments
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount all routers
app.include_router(auth_router)
app.include_router(dashboard_router)
app.include_router(anomalies_router)
app.include_router(recommendations_router)
app.include_router(query_router)
app.include_router(agents_router)
app.include_router(cost_router)


@app.on_event("startup")
async def startup_event():
    """Initialize database and run agents on first startup."""
    print("[STARTUP] Initializing CloudSentinel Backend...")

    # Init DB tables
    init_db()

    # Initialize ChromaDB
    try:
        from core.vectorstore import get_collection
        collection = get_collection()
        print(f"[STARTUP] ChromaDB ready. Documents: {collection.count()}")
    except Exception as e:
        print(f"[STARTUP] ChromaDB warning: {e}")

    # Auto-run agents on startup to populate DB with initial data
    from core.database import SessionLocal, CostData
    db = SessionLocal()
    try:
        cost_count = db.query(CostData).count()
        if cost_count == 0:
            print("[STARTUP] No cloud data found. Running initial agent pipeline...")
            from agents.orchestrator import run_all_agents
            run_all_agents(db)
            print("[STARTUP] Initial agent pipeline complete!")
        else:
            print(f"[STARTUP] Cloud data already exists ({cost_count} records). Skipping auto-run.")
    except Exception as e:
        print(f"[STARTUP] Agent auto-run error: {e}")
    finally:
        db.close()

    print("[STARTUP] CloudSentinel Backend ready at http://localhost:8000")
    print("[STARTUP] API Docs: http://localhost:8000/docs")


@app.get("/")
def root():
    return {
        "status": "online",
    "service": "CloudSentinel Backend",
        "version": "1.0.0",
        "docs": "/docs",
    }


@app.get("/health")
def health():
    return {"status": "healthy", "timestamp": __import__("datetime").datetime.utcnow().isoformat()}
