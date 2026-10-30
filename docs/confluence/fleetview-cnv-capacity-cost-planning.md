# FleetView - CNV Capacity & Cost Planning Tool
# Confluence ID: 407144931
# URL: https://redhat.atlassian.net/wiki/spaces/RHPDS/pages/407144931

FleetView
 Standalone CNV Capacity and Cost Planning Tool 
 Jira Epic: RHDPOPS-23462 
 Status: v0.7.0 Deployed to Dev | Owner: Josh Disraeli | Target Cluster: ocpv-infra01.dal12.infra.demo.redhat.com | Namespace: fleetview-dev
 Dev URL: https://fleetview-dev.apps.ocpv-infra01.dal12.infra.demo.redhat.com 
 Overview
 FleetView is a read-only CNV observability and capacity planning tool extracted from the Labagator monolith. It probes real OpenShift Virtualization clusters, predicts workload bin-packing placements, and calculates infrastructure costs. FleetView has zero knowledge of Labagator's domain (events, labs, sessions) -- it speaks only in generic terms: clusters , workloads , and placements .
 This is the first module extracted from Labagator following Unix design principles -- single-purpose, composable, fault-isolated. If FleetView fails, Labagator continues operating unaffected, and vice versa.
 Problem Statement
 CNV capacity and cost calculations are deeply embedded in Labagator's monolithic codebase across multiple service files ( capacity.py , pricing.py , cnv_probe.py). This creates several problems:
 A bug in capacity calculations can destabilize the entire scheduling application

 CNV observability requires the full Labagator stack to be running

 The capacity logic cannot be reused by other tools or teams

 Development and testing of capacity features is coupled to the event scheduling domain

 Architecture
 Technology Stack
 Layer
 Technology

 Backend
 FastAPI + SQLAlchemy + Alembic

 Frontend
 Next.js 15 + React 19 + PatternFly 6 (dark mode) + Recharts

 Database
 PostgreSQL 15

 Deployment
 Helm charts on OpenShift

 Auth
 OpenShift OAuth proxy + K8s group API RBAC

 CLI
 Typer + Rich (separate branch)

 Python packaging
 pyproject.toml

 Env prefix
 FLEETVIEW_

 Key Design Decisions
 Helm over Ansible -- portable, pluggable, lightweight; can deploy to any OCP cluster without Ansible dependencies

 Generic domain model -- Clusters, Workloads, Placements (not Events, Labs, Sessions)

 OAuth from day one -- same OpenShift OAuth proxy pattern as Labagator, no retrofitting

 Client-side overcommit toggle -- bin-packing reruns in browser when overcommit changes, no server round-trip

 Three-tier RBAC -- view/write/admin roles enforced via K8s group API queries with SA token auth and 60s cache

 Future wiring via API -- Labagator can call FleetView's POST /api/v1/capacity/calculate instead of running its own bin-packing

 Service Dependency Graph

 FleetView (standalone)
 +-- pricing.py (pure math: cost formula, rate lookups)
 +-- bin_packer.py (pure function: first-fit decreasing algorithm)
 +-- selector.py (pure function: JSONB containment matching)
 +-- probe.py (K8s API + Thanos queries for node capacity)
 +-- sandbox_db.py (read-only external DB for cluster annotations)
 +-- audit.py (mutation logging with before-state capture)

 RBAC (v0.7.0)
 Three-tier role-based access control:
 Role
 Access
 Groups

 admin
 Full access (all endpoints)
 FLEETVIEW_ADMIN_GROUPS

 write
 Read + mutating operations (create, update, delete clusters, change settings)
 FLEETVIEW_WRITE_GROUPS

 view
 Read-only (list clusters, view capacity, analytics)
 All authenticated users

 Authentication uses the OpenShift OAuth proxy. Authorization queries user.openshift.io/v1/groups via the ServiceAccount token (not X-Forwarded headers). Group membership is cached for 60 seconds.
 GET /api/v1/health/whoami returns the authenticated user's email and role.
 Core API
 Endpoints
 Method
 Path
 Description

 GET
 /api/v1/clusters
 List all clusters with capacity metrics

 POST
 /api/v1/clusters
 Register a new cluster

 PATCH
 /api/v1/clusters/{id}
 Update overcommit, online toggle, name

 DELETE
 /api/v1/clusters/{id}
 Remove a cluster

 POST
 /api/v1/clusters/{id}/probe
 Re-probe via K8s + Thanos

 POST
 /api/v1/clusters/probe-all
 Probe all clusters with kubeconfigs

 POST
 /api/v1/clusters/{id}/kubeconfig
 Upload kubeconfig file

 POST
 /api/v1/clusters/sync-annotations
 Refresh from sandbox DB

 POST
 /api/v1/capacity/calculate
 Bin-pack workloads + cost calculation

 GET
 /api/v1/capacity/current
 Fleet-wide capacity snapshot

 GET
 /api/v1/snapshots
 Capacity time-series data (cluster/date/limit filters)

 GET
 /api/v1/audit
 Audit trail (entity type/action/user filters)

 GET
 /api/v1/settings/rates
 Current cost rates

 PATCH
 /api/v1/settings/rates
 Update cost rates

 GET
 /api/v1/health
 Basic health check

 GET
 /api/v1/health/deep
 DB connectivity check

 GET
 /api/v1/health/whoami
 Authenticated user email + RBAC role

 Calculate Endpoint (POST /api/v1/capacity/calculate)
 Accepts a list of workload definitions and returns bin-packing placements with cost estimates.
 Request: 

 {
 "workloads": [
 {
 "name": "Workshop A",
 "cpu_per_deploy": 16,
 "memory_per_deploy": 64,
 "deploy_count": 25,
 "cloud_selector": {"purpose": "production"},
 "storage_gb": 100
 }
 ],
 "use_overcommit": true,
 "hours": 8,
 "include_cost": true
}

 Response: 

 {
 "placements": [{
 "workload_name": "Workshop A",
 "placements": {"ocpv04": 10, "ocpv05": 10, "ocpv06": 5},
 "unplaced": 0,
 "total_cpu": 400,
 "total_memory_gb": 1600,
 "cost": "2843.20"
 }],
 "fleet_summary": {
 "total_schedulable_cpu": 3840,
 "total_schedulable_mem": 9216.0,
 "total_placed_cpu": 400,
 "total_unplaced": 0,
 "total_cost": "2843.20"
 }
}

 CLI Tool
 Available on the cli branch. Install with pip install .[cli] .
 Command
 Description

 fleetview probe <kubeconfig> 
 Probe a single cluster for node capacity and baseline usage

 fleetview calculate <workloads.json> <clusters.json> 
 Run bin-packing and cost calculation

 fleetview fleet <kubeconfig-dir> 
 Probe all clusters in a directory

 fleetview cost <cpu> <memory> [--hours] [--storage] 
 Quick CNV cost estimate

 All commands support --json for pipe-friendly JSON output and rich tables for interactive use.
 CNV Cost Formula
 Resource
 Default Rate (per hour)

 CPU
 $0.0710600 per core

 Memory
 $0.0017500 per GB

 Storage
 $0.0001200 per GB

 Formula: (cpu * cpu_rate + memory_gb * mem_rate + storage_gb * stor_rate) * hours 
 Rates are configurable via the Settings API and UI.
 Frontend Pages
 Page
 Description

 Analytics (Current State)
 Fleet capacity stat cards (clusters, CPU, memory, schedulable, available) + utilization bars + overcommit toggle

 Analytics (History)
 Recharts LineCharts for CPU and Memory trends. Toolbar with date range selector (24h/7d/30d/90d), cluster filter, metric selector (schedulable/baseline/total/utilization)

 Clusters
 Sortable table with capacity metrics, probe button, sync annotations, kubeconfig status

 Planner
 Workload form + bin-packing calculation + placement results table + cost summary + overcommit toggle

 Settings
 Editable cost rates (CPU, memory, storage per hour) with reset to defaults

 Helm Chart
 22 templates covering the full OCP deployment stack:
 Resource Type
 Templates

 Compute
 StatefulSet (PostgreSQL), 3 Deployments (backend, frontend, oauth-proxy)

 Network
 4 Services, 2 Routes (frontend via OAuth, direct API)

 Build
 2 BuildConfigs (Docker strategy), 2 ImageStreams

 Auth
 ServiceAccount, ClusterRole, ClusterRoleBinding, OAuthClient

 Config
 ConfigMap (with RBAC group vars), 3 Secrets (DB, OAuth, webhook)

 Namespace
 Namespace

 Deploy with:

 helm upgrade --install fleetview-dev helm/fleetview -n fleetview-dev --create-namespace -f helm/fleetview/values-dev.yaml

 Implementation Phases
 Phase
 Scope
 Status
 Version

 Phase 1
 Core calculation engine (pricing, bin-packing, selector) + 37 unit tests
 Complete
 v0.1.0

 Phase 2
 Database models + Alembic migrations + K8s/Thanos cluster probing + 23 tests
 Complete
 v0.2.0

 Phase 3
 REST API (FastAPI endpoints, auth, health checks) + 15 API tests
 Complete
 v0.3.0

 Phase 4
 Frontend (Next.js 15 + PatternFly 6 dark mode UI)
 Complete
 v0.4.0

 Phase 5
 Helm charts + OCP deployment with OAuth proxy (22 templates)
 Complete
 v0.5.0

 Phase 6
 CLI tool (Typer-based, separate branch, pipe-friendly JSON output)
 Complete
 cli branch

 v0.7.0
 RBAC (3-tier via K8s group API) + capacity snapshots + audit trail + analytics page (Recharts) + GitHub webhooks for dev auto-build
 Complete
 v0.7.0

 Total: 84 backend tests passing, TypeScript clean, Helm templates validate clean 
 v0.7.0 -- RBAC, Snapshots, Audit Trail, Analytics (2026-05-19)
 Three feature branches merged to main:
 RBAC: 
 Three-tier access control: view (read-only), write (mutations), admin (full access)

 K8s group API queries via ServiceAccount token with 60s cache

 Replaces X-Forwarded header trust (security improvement)

 User model with email, role, last_login tracking

 GET /api/v1/health/whoami returns authenticated user email + role

 Alembic migration 002: users table

 Capacity Snapshots + Audit Trail: 
 capacity_snapshots table for time-series fleet/cluster metrics

 audit_logs table captures before-state for all PATCH/DELETE mutations

 GET /api/v1/snapshots with cluster_id, start/end date, and limit filters

 GET /api/v1/audit with entity type, action, and user filters

 Alembic migration 003: capacity_snapshots + audit_logs tables

 Analytics: 
 Dashboard page replaced with Analytics page

 Current State tab: stat cards, utilization bars, overcommit toggle (same as old Dashboard)

 History tab: Recharts LineCharts for CPU and Memory trends

 Toolbar: date range selector (24h/7d/30d/90d), cluster filter dropdown, metric selector (schedulable/baseline/total/utilization)

 Colors: #0066CC schedulable, #009596 baseline, #EE0000 total

 DevOps: 
 GitHub webhooks registered for backend + frontend BuildConfigs on dev

 Push to main auto-triggers OCP builds with ImageStream auto-rollout

 Deployed to fleetview-dev namespace on ocpv-infra01

 Phase 5 -- Helm + OCP Deployment (v0.5.0)
 22 Helm chart templates for full OCP deployment.
 Namespace, ServiceAccount with OAuth redirect annotation, ClusterRole + binding for group lookup

 PostgreSQL 15 StatefulSet with PVC, liveness/readiness probes

 Backend and frontend Deployments with ImageStream trigger annotations for auto-rollout

 OAuth proxy Deployment with TLS cert mount, pass-user-headers, cookie/session secrets

 Services for backend (8080), frontend (3000), postgresql (5432), oauth-proxy (4180)

 Routes: frontend via OAuth proxy (reencrypt TLS), direct API (edge TLS)

 BuildConfigs: Docker strategy for backend (UBI9 Python 3.11) and frontend (UBI9 Node.js 20)

 ImageStreams for backend and frontend

 OAuthClient CR for OpenShift OAuth integration

 Secrets for DB credentials, OAuth client/cookie/session, webhook

 ConfigMap for CORS, allowed groups, debug, sandbox DB URL

 All templates validate clean via helm template 

 Phase 4 -- Frontend (v0.4.0)
 Web UI with Next.js 15 + PatternFly 6 dark mode.
 Dashboard: fleet capacity cards + utilization progress bars

 Clusters: sortable table with probe actions + kubeconfig status

 Planner: workload form + bin-packing + placement results + cost summary + overcommit toggle

 Settings: editable cost rates with reset to defaults

 Components: ClusterTable, CapacityBar, PlacementResults, WorkloadForm, OvercommitToggle

 Infrastructure: typed API client (15s timeout), useApi hook, TypeScript types

 Phase 3 -- REST API (v0.3.0)
 Fully functional API endpoints with OpenShift OAuth RBAC.
 clusters.py : Full CRUD + probe + kubeconfig upload/delete + sync-annotations

 capacity.py : POST calculate (bin-pack + cost) + GET current fleet snapshot

 settings.py : GET/PATCH cost rates with DB persistence

 health.py : Basic + deep DB connectivity check

 auth.py : OpenShift OAuth RBAC via X-Forwarded-User/Groups headers

 Pydantic v2 schemas for all request/response models

 15 new API tests

 Phase 2 -- Database + Cluster Probing (v0.2.0)
 Persistent cluster state, live K8s/Thanos probing.
 Cluster model (19 fields), GlobalSetting key/value store

 Alembic migration for clusters + global_settings tables

 K8s/Thanos cluster probing (lifted from Labagator, zero changes)

 Sandbox DB annotation sync, DB-backed cost rate overrides

 23 new tests

 Phase 1 -- Core Calculation Engine (v0.1.0)
 Pure-math algorithms with tests. No DB, no K8s, no network calls.
 pricing.py : CNV cost constants and formula, instance type parser

 bin_packer.py: First-fit decreasing algorithm

 selector.py : JSONB containment matching

 37 unit tests, project scaffolding

 Phase 6 -- CLI (cli branch)
 Typer-based CLI for terminal usage, installed via pip install .[cli] .
 probe, calculate, fleet, cost commands

 --json for pipe-friendly output, rich tables for interactive use

 Reuses the same pure-function service modules as the web application

 Source Mapping
 Modules extracted from Labagator (labagator codebase remains unchanged):
 FleetView Module
 Labagator Source
 Extraction Scope

 services/pricing.py
 services/pricing.py
 CNV constants, formula, instance type parser

 services/bin_packer.py
 services/capacity.py
 Bin-packing algorithm, schedulable helpers

 services/selector.py
 services/capacity.py
 _selector_matches function

 services/probe.py
 services/cnv_probe.py
 Complete file (zero labagator imports)

 services/sandbox_db.py
 services/sandbox_db.py
 Complete file (env var prefix change)

 models/cluster.py
 models/cloud.py
 CnvCluster class (renamed to Cluster)

 models/settings.py
 models/global_settings.py
 Key/value JSONB store

 frontend repackWorkloads
 capacity/page.tsx
 Client-side bin-packing function

 Future Integration
 When ready, Labagator's capacity.py can call FleetView's POST /api/v1/capacity/calculate instead of running its own bin-packing. Labagator transforms its Lab/RoomSession objects into generic Workload definitions before calling. This is API integration -- cleanest decoupling, no shared database.
 Repository
 GitHub: rhpds/fleetview 
 Local: /Users/joshuadisraeli/repos/fleetview
 Target cluster: api.ocpv-infra01.dal12.infra.demo.redhat.com:6443 
 Dev namespace: fleetview-dev
 Dev URL: https://fleetview-dev.apps.ocpv-infra01.dal12.infra.demo.redhat.com
