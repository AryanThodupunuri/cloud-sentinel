CloudSentinel v2 - Notes

Overview

CloudSentinel v2 upgrades the backend to use AWS AssumeRole-based connections instead of storing raw access keys. It also introduces a safer connection model and sets the foundation for Cost Explorer ingestion, anomaly detection, Compute Optimizer integration, CloudWatch idle detection, normalized recommendations, action plans, and GitHub issue creation.

Key Changes (v2 step 1)

- CloudConnection model no longer stores raw AWS access keys.
  - New fields: role_arn, external_id, connection_status, last_validated_at, created_at, updated_at
  - Raw keys were removed to avoid storing secrets in the DB.

- New helper: `backend/core/aws_session.py`
  - get_assumed_role_session(role_arn, external_id) -> boto3.Session
  - validate_assumed_role(role_arn, external_id) -> dict (account_id, arn, user_id, status)
  - These functions use STS assume_role and never persist temporary credentials.

- Auth route updated: `POST /api/auth/aws/connect`
  - Accepts `role_arn` and optional `external_id` and region.
  - If role_arn omitted, the backend enables demo mode (no AWS calls).
  - On success, stores connection metadata (role_arn, external_id, account_id, connection_status).

- Frontend LandingPage updated to collect Role ARN / External ID and a Demo Mode button.

Running locally (quick)

1. Backend (Python)
   - Install requirements from `backend/requirements.txt` into a virtualenv
   - Set environment variables as needed (DATABASE_URL)
   - Run `python backend/main.py` (or `uvicorn backend.main:app --reload` depending on project layout)

2. Frontend (Node)
   - cd frontend
   - npm install
   - npm run dev

Notes and next steps

- This commit only covers Step 1 (AWS credential handling) and basic refactors to use AssumeRole sessions in existing agents.
- Subsequent steps will add new models (CostDailyRecord, CostAnomaly, OptimizationRecommendation, ActionPlan), services (cost_explorer_service, github_service, action_plan_service), agents (cost_anomaly_agent, compute_optimizer_agent, idle_resource_agent), routes for ingestion and action plans, and frontend dashboard updates.

Security

- The system does not persist AWS secret keys anymore. AssumeRole temporary credentials are used in-memory per-request.
- Demo mode remains available for local testing.

If you want me to continue implementing the other steps (compute optimizer, idle detection, action plans, GitHub integration, frontend updates, and tests), say "Continue with Step 2" and I will proceed to implement them incrementally with tests and verification.

New: cost ingestion can optionally trigger anomaly detection

POST /api/cost/ingest-history body:

```json
{
  "connection_id": null, // or connection id
  "days_back": 90,
  "run_anomaly_detection": true
}
```

Example curl (demo mode):

```bash
curl -X POST http://localhost:8000/api/cost/ingest-history \
  -H 'Content-Type: application/json' \
  -d '{"connection_id": null, "days_back": 30, "run_anomaly_detection": true}' | jq
```

Step 4: AWS Compute Optimizer integration (demo + real)

Routes added:
- POST /api/recommendations/compute-optimizer/scan
  Body: {"connection_id": <int>, "account_id": "..."}
  Triggers a Compute Optimizer scan (EC2 and EBS) using AssumeRole when a role ARN exists. In demo mode it seeds example recommendations.

- GET /api/recommendations/history?account_id=...
  Returns stored optimization recommendations (filter by source/status optional).

Demo example:

```bash
curl -X POST http://127.0.0.1:8000/api/recommendations/compute-optimizer/scan \
  -H "Content-Type: application/json" \
  -d '{}' | jq
```

Fetch history example:

```bash
curl "http://127.0.0.1:8000/api/recommendations/history?account_id=demo-unknown" | jq
```

Notes:
- Real AWS mode requires Compute Optimizer to be enabled and an IAM role with compute-optimizer:GetEC2InstanceRecommendations and compute-optimizer:GetEBSVolumeRecommendations.
- The agent uses AssumeRole and never stores raw AWS credentials.
