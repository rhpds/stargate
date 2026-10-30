# Infrastructure: Monitoring, Alerting, Metrics, Logging and Systems Automation
# Confluence ID: 286754461
# URL: https://redhat.atlassian.net/wiki/spaces/RHPDS/pages/286754461

Project Orion: 2025 Roadmap 
 Vision & Goals 
 To modernize our infrastructure stack, enhance our monitoring capabilities, and establish a robust, automated pipeline for logging, metrics, and alerting. This will improve system reliability, developer efficiency, and operational visibility. 
 Our Tech Stack 
 Here's a quick look at the tools we're using for this project! 
 What's in our toolbox right now (Active): 
 For Automation & CI/CD: We're using a combo of Jenkins , Rundeck , and Ansible to handle our builds and automate tasks. 

 For Keeping Things in Sync: ArgoCD is our go-to for managing cluster configurations with GitOps. 

 For Monitoring & Logging: We're keeping an eye on things with Icinga and Prometheus for alerts and metrics, and Splunk is handling all our logs. 

 For Seeing the Big Picture: Grafana is where we bring it all together with dashboards for our metrics and logs* (tbd). 

 What's on the horizon (Planned): 
 We're planning a big move to OpenShift as our main platform. This will also include bringing in CNV for running VMs and ODF for storage. 

 2025 Roadmap 
 Epic 1: Core Infrastructure & Tooling Modernization 
 Focus: Upgrade foundational tools to their latest, stable versions to improve security, performance, and feature availability. 
 [ ] Update Core Services 
 [ ] Update Icinga 

 [ ] Update Rundeck 

 [ ] Update Jenkins, OS 

 [ ] Sub-Task: Investigate and decide: Deploy new instances vs. in-place upgrades. 

 [ ] Sub-Task: Plan and execute data migration if new instances are deployed. 

 [ ] Update System Packages 
 [ ] Audit and update all necessary OS and application-level packages. 

 Epic 2: New OpenShift Infrastructure Rollout 
 Focus: Build and configure a new, state-of-the-art OpenShift cluster with integrated monitoring, storage, and virtualization. 
 [ ] Setup New Infra Cluster 
 [ ] Provision base cluster resources. 

 [ ] Configure OpenShift Data Foundation (ODF) for persistent storage. 

 [ ] Configure Container-native Virtualization (CNV). 

 [ ] Integrate Cluster Logging with Splunk 
 [ ] Configure and deploy the cluster log forwarder. 

 [ ] Manage configuration with ArgoCD for GitOps workflow. 

 [ ] Setup Prometheus for Metrics 
 [ ] Configure long-term storage and retention policies. 

 [ ] Add new application and infrastructure targets for scraping. 

 [ ] Set up Prometheus as a new data source in Grafana. 

 [ ] Deploy and Test Monitoring on CNV 
 [ ] Validate that monitoring tools are successfully deployed and collecting data from virtualized environments. 

 Epic 3: Monitoring & Alerting Overhaul 
 Focus: Refine our alerting strategy to reduce noise, improve signal quality, and ensure notifications reach the right people through the right channels. 
 [ ] Establish Monitoring Ticket Policy 
 [ ] Define rules and procedures for automatically creating tickets from alerts. 

 [ ] Cleanup & Refine Icinga Alerts 
 [ ] Revamp outdated or inefficient alert checks. 

 [ ] Decommission alerts that are no longer needed or provide low value. 

 [ ] Convert state-based alerts to metric-based (Prometheus) where appropriate. 

 [ ] Implement Modern Notifications 
 [ ] Configure and test Slack notifications for alerts. 

 [ ] Configure and test Email notifications for alerts. 

 Epic 4: Enhanced Visualization & Dashboards 
 Focus: Create clear, intuitive, and actionable dashboards that provide at-a-glance visibility into system health and performance. 
 [ ] Deploy Splunk Plugin for Grafana 
 [ ] Integrate Splunk logs directly into Grafana dashboards for unified views. 

 [ ] Develop New "Component Overview" Dashboard 
 [ ] Design a simplified, high-level dashboard showing the status of all major components. 

 [ ] Ensure the dashboard is highly visible and easy to interpret. 

 [ ] Create New Dashboards per Component 
 [ ] Build detailed, component-specific dashboards for deep-dive analysis. 

 Epic 5: Babylon Security Check Overhaul 
 Focus: Increase the speed and efficiency of our monitoring checks by transitioning from serial to parallel execution and re-architecting for dynamic environments. 
 [ ] Parallelize Ansible Playbook Checks 
 [ ] Refactor core Ansible playbook for environment checks to enable parallel execution. 

 [ ] Test and validate performance improvements. 

 [ ] Roll out the updated check to all environments. 

 [ ] Re-architect Zero Touch (ZT) Lab Monitoring Context: The current approach of creating individual Icinga objects per lab is not scalable for dynamic platforms. A new architecture is needed. 

 [ ] Decouple Inventory: 
 [ ] Create a job to pull lab URLs and IDs from Babylon. 

 [ ] Publish the inventory as a frequently regenerated JSON file (ideally in-memory). 

 [ ] Implement Concurrent Monitoring: 
 [ ] Develop a script for Icinga to concurrently fetch data from all lab URLs in the inventory. 

 [ ] Create an asynchronous handler to process the results efficiently. 

 [ ] Develop Intelligent Event Handling: 
 [ ] Implement logic to filter events for labs below a specific metric threshold. 

 [ ] Generate a qualified event only for labs that exceed the threshold. 

 [ ] Define Flexible Response Actions: 
 [ ] Build an event handler that can trigger different actions based on lab type. 

 [ ] For ZT Labs: Implement actions to terminate the lab and ban the user. 

 [ ] For OpenShift Labs (ROSA): Implement actions to collect required data for InfoSec. 

 Solution Candidate 1: 
 The proposal to decouple the inventory component is a clear path forward. This approach will support both ROSA and ZT labs and can be extended to other types in the future.
 Instead of creating an Icinga object per item (which is too many) or a single object for all items (which is too few), the proposed solution is to adopt the Babylon approach: create one Icinga object per user (namespace) .
 This per-user object model offers several advantages:
 Personalized Alerts: Enables customized notifications for each user.

 Multi-Item Handling: Can manage different items within a single user's namespace.

 Selective Monitoring: Allows for filtering out objects that do not require monitoring within the user's namespace.

 Object Immutability: The user object in Icinga remains constant, even as the user deploys new items.

 Efficient Checks: No alerts, checks, or notifications will be triggered if a user has no active items in their namespace.

 To manage the lifecycle of these objects, a regular cleanup process will be implemented. For instance, an Icinga object could be decommissioned after 90 days of inactivity, similar to Babylon's process for unused namespaces. The host object in Icinga, corresponding to the user namespace, would be created once and persist until this cleanup occurs.
 This leads to a modular architecture with four distinct components:
 Namespace Handler: Manages the creation and cleanup of Icinga objects.
 this would be a new script

 Inventory Handler: Gathers and provides data on active items.
 this would be the current babylon inventory script

 Alert/Notification Handler: Manages the alerting logic.
 this would be a service object in Icinga that runs against the host object (user)

 Response Handler: Executes actions such as terminating a lab or blocking a user.
 this would be an Icinga event that would run as a response to a state change

 Solution Candidate 2: 
 This proposed solution focuses on using an Ansible playbook for checks and centralizing the results in a single Icinga object.
 Decoupled Inventory Generation: 
 An independent process will run periodically to generate and update a list of hosts that require monitoring.

 Parallel Execution: 
 An Ansible playbook will be configured to run checks on all hosts in parallel, significantly reducing execution time.

 Centralized Evaluation in Icinga: 
 The results from the playbook run will be sent to Icinga.

 Icinga will be responsible for evaluating the results to identify which items have critical issues and require intervention.

 A single host object, defined as "ZT items" , will be used in Icinga to represent all monitored entities.

 Event-Driven Remediation: 
 For any items identified as critical, Icinga will trigger an event to run a remediation script (e.g., block the user, terminate the environment).

 Implementation Approaches
 Two alternative approaches are suggested for integrating the Ansible playbook with Icinga:
 Approach 1: Passive Check 
 The Ansible playbook runs independently.

 Upon completion, it pushes its results to Icinga as a passive check.

 Approach 2: Active Check 
 Icinga actively triggers the execution of the Ansible playbook.

 Icinga then sets the status based on the playbook's outcome.

 In both scenarios, the final step is for Icinga to initiate the necessary remediation actions based on the check results.

 Possible blockers:
 Current Icinga events are based on the host object attributes, I am unsure if any solution would allow an Icinga action to target just one specific item.
 Amount of work is to consider given the size of the monitoring team (1) and other possible items to work on.
 Looks like a big project to follow along for the rest of the year.

 Future Roadmap (Beyond 2025) 
 A high-level look at strategic initiatives to build upon the foundation laid in 2025. 
 [ ] Automate Monitoring Deployments 
 Goal: Use Rundeck jobs to automate the deployment and configuration of monitoring agents and checks, potentially leveraging CNV snapshots. 

 [ ] Team & Knowledge Growth 
 Goal: Cross-train another team member to become a subject matter expert on the new monitoring stack. 

 [ ] Investigate New Tools 
 Goal: Continuously research and evaluate emerging tools in the observability space to stay current. 

 [ ] Build a Fully Automated Monitoring Pipeline 
 Goal: Create a zero-touch pipeline from code commit to monitoring-in-production. 

 [ ] Clarify Tool Responsibilities 
 Goal: Solidify and document the distinct role of each tool: 
 Rundeck: Automation & Remediation 

 Icinga: State-based Monitoring & Uptime 

 Prometheus: Metrics & Time-Series Data 

 Splunk: Centralized Logging & Analysis
