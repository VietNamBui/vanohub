# VanoHub System Architecture

Combined system architecture across the VanoHub backend (Django / DRF) and frontend SPA (React / TypeScript / Vite).

**CVAT ↔ VanoHub Hierarchy & Boundaries:**
- `CVAT Organization ↔ Project` (`cvat_org_id`, `cvat_org_slug`, UI `"Organization"`)
- `CVAT Project ↔ Dataset` (`cvat_project_id`, UI `"Project"`)
- `CVAT Task ↔ Batch` (`cvat_task_id`, `qc2_confirmed_at`, UI `"Task"`)
- `CVAT Job ↔ Job` (`cvat_job_id`, `cvat_start_frame`, `cvat_assignee_id`, UI `"Job"`)
- **Outbound CVAT writes** (`backend/cvat_integration/assignee.py`) are strictly limited to CVAT job `assignee` updates and organization `worker` invitations. **QC2** runs frame-level deterministic sampling across every job entering `pending_qc2` (`backend/quality/qc2.py`).

```mermaid
flowchart TB
    subgraph Frontend["Frontend SPA (React 19 · TypeScript · Vite 8)"]
        subgraph FE_Shell["Shell & Routing"]
            FE_Auth["RequireAuth · RequireCap · ProjectLayout · MainLayout\nNotificationBell · QuickSearchModal · SupportCenterDrawer · AccountSettingsPage"]
        end

        subgraph FE_Pages["Feature Modules"]
            FE_PM["PM & QC2: Overview · Datasets (Projects) · Batches (Tasks, confirm-qc2) · Jobs · Queue · Teams · Workload · Audits · Strategy · QC2 Work · Delivery · CVAT Link"]
            FE_AQ["Annotator & QC1: AnnotatorDashboard · AnnotatorAnalytics · AnnotatorJobs · AnnotatorJobDetail · AnnotatorRework · AnnotatorRequests\nQc1Dashboard · Qc1Work · Qc1ReviewPanel"]
        end

        ApiClient["Axios Client (shared/api/client.ts)\nJWT Bearer + 401 Refresh (/auth/token/refresh/)"]

        FE_Auth --> FE_PM & FE_AQ --> ApiClient
    end

    subgraph Backend["Backend API (Django 6 · DRF · SimpleJWT)"]
        Urls["/admin/  +  /api/* Router (config/urls.py)"]

        subgraph AuthLayer["accounts & RBAC"]
            Acc["Custom User · RoleAssignment (PM, QC2, QC1, Annotator)\nIMPLIED_ROLES (PM->QC2) · ProjectScopedViewMixin · HasProjectCapability\n/auth/me/ · /auth/me/password/ · /auth/change-password/ · /auth/users/"]
        end

        subgraph Domain["Domain Apps"]
            Projects["projects: Project (Org) · Dataset (CVAT Project) · Batch (CVAT Task, confirm-qc2) · Delivery · Guideline · Announcement · ActivityLog · UserNotification"]
            Teams["teams: Team · TeamMember (capacity, workload, transfer)"]
            Jobs["jobs: Job Workflow · DailyOutputRecord · JobQueueView · AnnotatorJobViewSet (claim, start, submit)\nAnnotatorRequest (error_dispute, data_issue -> PM) · QuickSearch"]
            Quality["quality: ErrorCategory · Audit (read-only) · AuditSample (frame QC2 via qc2.py) · ReviewError\nQc1JobViewSet (start, pass, reject) · AuditSampleViewSet (pass, reject, assign)"]
            Analytics["analytics: Overview · Team Ranking · Member Performance · QC2 Summary · AnnotatorDashboard · AnnotatorAnalytics · Qc1Summary"]
        end

        CvatSync["cvat_integration: CvatClient · CvatAccount (/cvat/link/)\nsync.py (CVAT Org<->Project, Project<->Dataset, Task<->Batch, Job<->Job)\nassignee.py (outbound job assignee push & org worker invite) · sync_cvat"]

        Urls --> Acc --> Projects & Teams & Jobs & Quality & Analytics & CvatSync
    end

    subgraph Infra["Persistence & External Services"]
        DB[("PostgreSQL 17\ndocker-compose.yml :5432")]
        CVAT["External CVAT Server\nREST API (CVAT_URL) & UI (CVAT_PUBLIC_URL)"]
    end

    ApiClient -- "HTTPS / JSON + JWT" --> Urls
    FE_Auth -. "Deep Links (?org=, ?frame=)" .-> CVAT

    Acc & Projects & Teams & Jobs & Quality --> DB
    Analytics -. "Aggregates" .-> Projects & Jobs & Quality
    CvatSync -- "REST GET Sync + PATCH Assignee / POST Invite" --> CVAT
    CvatSync --> Jobs & Projects & Quality
```

## Key File References

- **Infrastructure & Entry**: `docker-compose.yml`, `backend/config/urls.py`, `backend/config/settings.py`, `frontend/src/App.tsx`, `frontend/src/app/router.tsx`, `frontend/src/shared/api/client.ts`
- **Backend Apps**: `backend/accounts/permissions.py`, `backend/accounts/models.py`, `backend/projects/models.py`, `backend/teams/models.py`, `backend/jobs/models.py`, `backend/quality/models.py`, `backend/quality/qc2.py`, `backend/analytics/urls.py`, `backend/cvat_integration/models.py`, `backend/cvat_integration/urls.py`, `backend/cvat_integration/sync.py`, `backend/cvat_integration/assignee.py`
