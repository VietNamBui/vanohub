# VanoHub System Architecture

Combined system architecture across all repository branches (`main`, `origin/feature/project-manager`, `feature/director-annotator-qc1`) and uncommitted working-tree additions.

```mermaid
flowchart TB
    subgraph Legend["Branch Layering"]
        direction LR
        B0["1. main (3e21fa1): Base Scaffold + DB"] --> B1["2. origin/feature/project-manager (47cb33d): Core RBAC · PM · QC2 · TL · CVAT"] --> B2["3. feature/director-annotator-qc1 (d4b06d7): Annotator + QC1"] -.-> B3["4. Working Tree (Uncommitted): Requests · Notifications · Analytics · Settings"]
    end

    subgraph Frontend["Frontend SPA (React 19 · TypeScript · Vite 8)"]
        subgraph FE_Shell["Shell & Routing"]
            FE_Base["[main] MainLayout · Placeholder Routes"]
            FE_Auth["[PM] RequireAuth · RequireCap · ProjectLayout · Untitled UI / AntD / Tailwind"]
            FE_WIP_UI["[WIP] NotificationBell · QuickSearchModal · SupportCenterDrawer · AccountSettingsPage"]
        end

        subgraph FE_Pages["Feature Modules"]
            FE_PM["[PM] PM · Director · Team Leader · QC2 · CVAT Link Pages"]
            FE_DAQ["[Dir/Ann/QC1] AnnotatorDashboard · AnnotatorJobs · AnnotatorJobPanel\nQc1Dashboard · Qc1Work · Qc1ReviewPanel"]
            FE_WIP["[WIP] AnnotatorJobDetail · AnnotatorRework · AnnotatorRequests · AnnotatorAnalytics"]
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
            AccPM["[PM] JWT Auth · RoleAssignment · IMPLIED_ROLES (PM->QC2, TL->QC1)\nProjectScopedViewMixin · HasProjectCapability"]
            AccDAQ["[Dir/Ann/QC1] + ANNOTATE_JOBS, PERFORM_QC1"]
            AccWIP["[WIP] /auth/me/ · /auth/change-password/ · Profile & Notify Prefs"]
            AccBase --> AccPM --> AccDAQ -.-> AccWIP
        end

        subgraph Domain["Domain Apps (Skeletons in [main])"]
            Projects["[PM] projects: Project · Dataset · Batch · Delivery · Guideline · Announcement · ActivityLog\n[WIP] + UserNotification · annotator_wip_limit"]
            Teams["[PM] teams: Team · TeamMember (capacity) · leader_views (grant QC1, Team Dashboard/Jobs)"]
            Jobs["[PM] jobs: Job Workflow · JobQueueView · Assign/Deadline/Lock/Escalation\n[Dir/Ann/QC1] + AnnotatorJobViewSet (claim, start, submit)\n[WIP] + AnnotatorRequest (error_dispute, data_issue) · QuickSearch"]
            Quality["[PM] quality: ErrorCategory · Audit · AuditSample · ReviewError · Random/Stratified Sampling\n[Dir/Ann/QC1] + Qc1JobViewSet (start, pass, reject)"]
            Analytics["[PM] analytics: Overview · Team Ranking · Member Performance · QC2 Summary\n[Dir/Ann/QC1] + AnnotatorDashboard · Qc1Summary\n[WIP] + AnnotatorAnalytics"]
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
