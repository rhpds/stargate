# Controller Scheduler Migration Complete: 193 Catalog Items Migrated in 2 Days
# Confluence ID: 442568451
# URL: https://redhat.atlassian.net/wiki/spaces/RHPDS/pages/442568451

Date : 2026-07-31

 Epic : RHDPOPS-23873 

 Team : RHDP Operations
 Summary
 The RHDP Operations team successfully completed the controller-scheduler migration, moving all 193 catalog items from static controller assignment to intelligent, metrics-based load balancing. The migration was completed in 2 days—21x faster than the original 6-week estimate.
 What Changed
 Before: Static Controller Assignment
 Catalog items were manually assigned to specific AAP2 controllers:
 aap2-prod-us-west-2.aap.infra.demo.redhat.com 

 aap2-prod-us-east-2.aap.infra.demo.redhat.com 

 Configuration required explicit controller lists in prod_controllers_lb.yaml and event_controllers_lb.yaml .
 After: Intelligent Load Balancing
 All catalog items now use the controller-scheduler service, which:
 Automatically selects controllers based on real-time Prometheus metrics

 Load balances across multiple on-prem controllers:

 prod0 (Dallas) and prod1 (Washington DC) for production workloads

 event0 (Dallas) and event1 (Washington DC) for event workloads

 Provides automatic failover when controllers have issues

 Monitors : capacity, failure rate, availability, and pending job queue

 Configuration is now centralized in controller-scheduler.yaml and controller-scheduler-event.yaml with automatic controller selection.
 Migration Stats
 Metric
 Value

 PRs Merged 
 16/16 (100%)

 Catalog Items 
 193/193 (100%)

 Accounts Migrated 
 19/19 (100%)

 Timeline 
 2 days (Jul 30-31)

 Original Estimate 
 6 weeks

 Acceleration 
 21x faster

 Production Incidents 
 0

 Benefits
 1. Automatic Load Balancing
 Controllers are selected based on current capacity and health metrics, preventing overload on any single controller.
 2. Intelligent Failover
 If a controller fails health checks or reaches capacity limits, the scheduler automatically routes new jobs to healthy controllers.
 3. Reduced Operational Overhead
 No manual controller assignment required. The system adapts to changing conditions automatically.
 4. Better Resilience
 Geographic distribution across Dallas and Washington DC data centers (prod0/prod1 and event0/event1) provides better fault tolerance.
 5. Metrics-Driven Decisions
 Real-time Prometheus metrics (job queue depth, failure rate, response time) inform routing decisions.
 Technical Approach
 Migration Pattern
 Old configuration (static):

 #include /includes/ansible_control_plane/prod_controllers_lb.yaml
#include /includes/ansible_control_plane/event_controllers_lb.yaml

 New configuration (dynamic):

 #include /includes/ansible_control_plane/controller-scheduler.yaml
#include /includes/ansible_control_plane/controller-scheduler-event.yaml

 The new includes:
 Query the controller-scheduler API for the best available controller

 Fall back to hardcoded lists (prod0/prod1 or event0/event1) if the API is unavailable

 Support label-based controller requirements (e.g., env=event )

 Testing Strategy
 All 193 catalog items were:
 Deployed to the integration cluster

 Tested for successful provisioning

 Verified for correct controller routing

 Documented with AAP2 job URLs and controller evidence

 Integration test evidence was posted to all 16 pull requests before merge.
 Challenges Overcome
 1. AgnosticV Operator Timeout
 Issue : 8 PRs failed CI checks with operator timeout errors.

 Root Cause : AgnosticV operator deployment scaled to 0 replicas.

 Fix : Scaled operator to 1 replica, unblocking 116 catalog items.
 2. Poolboy Resource Bottleneck
 Issue : Concurrent deployment of 200+ items caused resource assignment queue overload.

 Solution : Deployed in 5-10 item batches to prevent resource pool exhaustion.
 3. Large Dependency Chains
 Issue : summit-2026 folder (81 items) had complex cluster→tenant dependencies.

 Solution : Deployed as separate PR with careful dependency ordering.
 Team Effort
 This migration was a team effort across the entire RHDP Operations group:
 Billy Bethell : Migration planning, deployment, testing, automation, Jira tracking

 Perry Rivera : PR reviews and merging all 16 PRs

 Dibyendu Jana : PR reviews and approvals

 Kadeem Lewis : Testing support and validation

 Josh Disraeli : Original controller-scheduler design and PR creation

 Additional support and collaboration from the entire RHDP Ops team: Victor Aguilera, Ahsen Shah, Chandrabose Bomman, and Harsh Arora.
 Looking Forward
 Immediate Benefits
 All catalog items now benefit from automatic load balancing

 Controller health issues will be mitigated automatically

 Operations team freed from manual controller assignment

 Future Enhancements
 Potential areas for improvement:
 Add more controllers to the pool for increased capacity

 Implement predictive scaling based on historical patterns

 Expand metrics collection for better routing decisions

 Add automated alerts for scheduler API health

 Documentation
 Epic : RHDPOPS-23873 

 Completion Report : /home/bbethell/projects/2026-07-30-controller-migration-dj-plan/MIGRATION_COMPLETE.md 

 Confluence : /wiki/spaces/RHPDS/pages/437355598 

 All 16 PRs : Integration test evidence in PR comments

 Related Work
 RHDPOPS-23606 : AAP2 LB migration (300+ items, previous similar effort)

 Controller-scheduler service : Built by Josh Disraeli

 Integration testing framework : Developed during migration

 Tags: rhdp, operations, automation, aap2, controller-scheduler, migration, infrastructure
