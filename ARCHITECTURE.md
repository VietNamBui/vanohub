# VanoHub System Architecture

Combined system architecture across the VanoHub backend (Django / DRF) and frontend SPA (React / TypeScript / Vite).

```mermaid
flowchart TB
    subgraph Frontend["Frontend SPA (React 19 · TypeScript · Vite 8)"]
        subgraph FE_Shell["Shell & Routing"]
            FE_Auth["RequireAuth · RequireCap · ProjectLayout · MainLayout\nNotificationBell · QuickSearchModal · SupportCenterDrawer · AccountSettingsPage"]
        end

        subgraph FE_Pages["Feature Modules"]
            FE_PM["PM & QC2: Overview · Datasets · Batches · Jobs · Queue · Teams · Audits · Strategy · QC2 Work · Delivery · CVAT Link"]
            FE_AQ["Annotator & QC1: AnnotatorDashboard · AnnotatorAnalytics · AnnotatorJobs · AnnotatorJobDetail · AnnotatorRework · AnnotatorRequests\nQc1Dashboard · Qc1Work · Qc1ReviewPanel"]
        end

        ApiClient["Axios Client (shared/api/client.ts)\nJWT Bearer + 401 Refresh (/auth/token/refresh/)"]

        FE_Auth --> FE_PM & FE_AQ --> ApiClient
    end

    subgraph Backend["Backend API (Django 6 · DRF · SimpleJWT)"]
        Urls["/admin/  +  /api/* Router (config/urls.py)"]

        subgraph AuthLayer["accounts & RBAC"]
            Acc["Custom User · RoleAssignment (PM, QC2, QC1, Annotator)\nIMPLIED_ROLES (PM->QC2) · ProjectScopedViewMixin · HasProjectCapability\n/auth/me/ · /auth/change-password/ · /auth/users/"]
        end

        subgraph Domain["Domain Apps"]
            Projects["projects: Project · Dataset · Batch · Delivery · Guideline · Announcement · ActivityLog · UserNotification"]
            Teams["teams: Team · TeamMember (capacity, workload, transfer)"]
            Jobs["jobs: Job Workflow · JobQueueView · AnnotatorJobViewSet (claim, start, submit)\nAnnotatorRequest (error_dispute, data_issue -> PM) · QuickSearch"]
            Quality["quality: ErrorCategory · Audit · AuditSample · ReviewError · Qc1JobViewSet (start, pass, reject)"]
            Analytics["analytics: Overview · Team Ranking · Member Performance · QC2 Summary · AnnotatorDashboard · AnnotatorAnalytics · Qc1Summary"]
        end

        CvatSync["cvat_integration: CvatClient · sync.py (CVAT Task<->Batch, CVAT Job<->Job)"]

        Urls --> Acc --> Projects & Teams & Jobs & Quality & Analytics & CvatSync
    end

    subgraph Infra["Persistence & External Services"]
        DB[("PostgreSQL 17\ndocker-compose.yml :5432")]
        CVAT["External CVAT Server\nREST API (CVAT_URL) & UI (CVAT_PUBLIC_URL)"]
    end

    ApiClient -- "HTTPS / JSON + JWT" --> Urls
    FE_Auth -. "Deep Links" .-> CVAT

    Acc & Projects & Teams & Jobs & Quality --> DB
    Analytics -. "Aggregates" .-> Projects & Jobs & Quality
    CvatSync -- "REST GET (Token / Basic)" --> CVAT
    CvatSync --> Jobs & Projects
```

## Key File References

- **Infrastructure & Entry**: `docker-compose.yml`, `backend/config/urls.py`, `backend/config/settings.py`, `frontend/src/App.tsx`, `frontend/src/app/router.tsx`, `frontend/src/shared/api/client.ts`
- **Backend Apps**: `backend/accounts/permissions.py`, `backend/accounts/models.py`, `backend/projects/models.py`, `backend/teams/models.py`, `backend/jobs/models.py`, `backend/quality/models.py`, `backend/analytics/urls.py`, `backend/cvat_integration/sync.py`
