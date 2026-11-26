# VanoHub System Architecture

Combined system architecture across all repository branches (`main`, `origin/feature/project-manager`, `annotator-qclv1`, `feature/issue-logger`).

```mermaid
flowchart TB
    subgraph Legend["Branch Layering"]
        direction LR
        B0["1. main (3e21fa1): Base Scaffold + DB"] --> B1["2. origin/feature/project-manager (47cb33d): Core RBAC · PM · QC2 · CVAT"] --> B2["3. annotator-qclv1 (25bd5f2): Annotator + QC1"] --> B3["4. feature/issue-logger: Requests · Notifications · Audit Decisions · Role Cut"]
    end

    subgraph Frontend["Frontend SPA (React 19 · TypeScript · Vite 8)"]
        subgraph FE_Shell["Shell & Routing"]
            FE_Base["[main] MainLayout · Placeholder Routes"]
            FE_Auth["[PM] RequireAuth · RequireCap · ProjectLayout · Untitled UI / AntD / Tailwind"]
            FE_WIP_UI["[IssueLogger] NotificationBell · QuickSearchModal · SupportCenterDrawer · AccountSettingsPage"]
        end

        subgraph FE_Pages["Feature Modules"]
            FE_PM["[PM] PM · QC2 · CVAT Link Pages"]
            FE_DAQ["[Ann/QC1] AnnotatorDashboard · AnnotatorJobs · AnnotatorJobPanel\nQc1Dashboard · Qc1Work · Qc1ReviewPanel"]
            FE_WIP["[IssueLogger] AnnotatorJobDetail · AnnotatorRework · AnnotatorRequests · AnnotatorAnalytics"]
        end

        ApiClient["[PM] Axios Client (shared/api/client.ts)\nJWT Bearer + 401 Refresh (/auth/token/refresh/)"]

        FE_Base --> FE_Auth --> FE_PM & FE_DAQ & FE_WIP
        FE_WIP_UI -.-> ApiClient
        FE_PM & FE_DAQ & FE_WIP --> ApiClient
    end

    subgraph Backend["Backend API (Django 6 · DRF · SimpleJWT)"]
        Urls["[main] /admin/  +  [PM] /api/* Router (config/urls.py)"]

        subgraph AuthLayer["accounts & RBAC"]
            AccBase["[main] Custom User Model"]
            AccPM["[PM] JWT Auth · RoleAssignment · IMPLIED_ROLES (PM->QC2)\nProjectScopedViewMixin · HasProjectCapability"]
            AccDAQ["[Ann/QC1] + ANNOTATE_JOBS, PERFORM_QC1"]
            AccWIP["[IssueLogger] /auth/me/ · /auth/change-password/ · /auth/users/ · cvat_username"]
            AccBase --> AccPM --> AccDAQ --> AccWIP
        end

        subgraph Domain["Domain Apps (Skeletons in [main])"]
            Projects["[PM] projects: Project · Dataset · Batch · Delivery · Guideline · Announcement · ActivityLog\n[IssueLogger] + UserNotification · Batch QC2 Confirm · annotator_wip_limit"]
            Teams["[PM] teams: Team · TeamMember (capacity)"]
            Jobs["[PM] jobs: Job Workflow · JobQueueView · Assign/Deadline/Lock/Escalation\n[Ann/QC1] + AnnotatorJobViewSet (claim, start, submit)\n[IssueLogger] + AnnotatorRequest (error_dispute, data_issue) · QuickSearch"]
            Quality["[PM] quality: ErrorCategory · Audit · AuditSample · ReviewError · Random/Stratified Sampling\n[Ann/QC1] + Qc1JobViewSet (start, pass, reject)\n[IssueLogger] + Audit Decisions (accept, reject, partial_reject)"]
            Analytics["[PM] analytics: Overview · Team Ranking · Member Performance · QC2 Summary\n[Ann/QC1] + AnnotatorDashboard · Qc1Summary\n[IssueLogger] + AnnotatorAnalytics"]
        end

        CvatSync["[PM] cvat_integration: CvatClient · sync.py (CVAT Task<->Batch, CVAT Job<->Job)"]

        Urls --> AccPM
        AccDAQ --> Projects & Teams & Jobs & Quality & Analytics & CvatSync
    end

    subgraph Infra["Persistence & External Services"]
        DB[("[main] PostgreSQL 17\ndocker-compose.yml :5432")]
        CVAT["[PM] External CVAT Server\nREST API (CVAT_URL) & UI (CVAT_PUBLIC_URL)"]
    end

    ApiClient -- "HTTPS / JSON + JWT" --> Urls
    FE_Auth -. "Deep Links" .-> CVAT

    AccBase & Projects & Teams & Jobs & Quality --> DB
    Analytics -. "Aggregates" .-> Projects & Jobs & Quality
    CvatSync -- "REST GET (Token / Basic)" --> CVAT
    CvatSync --> Jobs & Projects
```

## Key File References

- **Infrastructure & Entry**: `docker-compose.yml`, `backend/config/urls.py`, `backend/config/settings.py`, `frontend/src/App.tsx`, `frontend/src/app/router.tsx`, `frontend/src/shared/api/client.ts`
- **Backend Apps**: `backend/accounts/permissions.py`, `backend/accounts/models.py`, `backend/projects/models.py`, `backend/teams/models.py`, `backend/jobs/models.py`, `backend/quality/models.py`, `backend/analytics/urls.py`, `backend/cvat_integration/sync.py`
