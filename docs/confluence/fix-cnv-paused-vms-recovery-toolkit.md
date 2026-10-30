# Fix CNV Paused VMs — Recovery Toolkit
# Confluence ID: 382581079
# URL: https://redhat.atlassian.net/wiki/spaces/RHPDS/pages/382581079

Complete toolkit for recovering paused VMs and investigating Ceph OSD issues in OpenShift Virtualization environments.
 Repo: rhpds/fix-cnv-paused-vms 
 Scripts
 Script
 Purpose

 fix-paused-vms.sh 
 Recovers VMs paused due to Ceph blocklist issues

 monitor-vms-and-ceph.sh 
 Continuous monitoring with automated alerting

 diagnose-node.sh 
 Deep diagnostic analysis of node health

 investigate-incident.sh 
 Automated post-mortem analysis

 Prerequisites
 oc CLI with cluster-admin access

 jq command-line JSON processor

 OpenShift Virtualization (KubeVirt) + Ceph/ODF storage

 VM Recovery ( fix-paused-vms.sh )

 # Basic usage (interactive)
./fix-paused-vms.sh

# Automated (no prompts)
./fix-paused-vms.sh -y

# Conservative (production)
./fix-paused-vms.sh -b 5 -d 120

# Aggressive (dev/test)
./fix-paused-vms.sh -b 20 -d 30 -y

 What it does:
 Finds all paused VMs

 Identifies nodes hosting paused VMs

 Clears Ceph blocklist ONLY for affected nodes (safe)

 Restarts VMs in batches

 Verifies recovery

 Options: -b batch size (default 10), -d delay between batches (default 60s), -n namespace filter, -y skip confirmations.
 Continuous Monitoring ( monitor-vms-and-ceph.sh )

 # One-time check
./monitor-vms-and-ceph.sh

# Continuous (every 5 minutes)
./monitor-vms-and-ceph.sh --loop 300

# With Slack alerts
./monitor-vms-and-ceph.sh --loop 300 --webhook https://hooks.slack.com/your-webhook

 Monitors: paused VMs, Ceph cluster health, OSD crashes, blocklist growth, OSD status, problem node health.
 Incident Response Runbook
 Check scope: oc get vmi --all-namespaces | grep False 

 Verify Ceph: oc exec -n openshift-storage deploy/rook-ceph-tools -- ceph -s 

 Run recovery: ./fix-paused-vms.sh 

 Verify: oc get vmi --all-namespaces | grep False 

 Node Diagnostics ( diagnose-node.sh )

 ./diagnose-node.sh <node-name>

 Collects: node info, system logs, hardware health (SMART, memory, CPU), network stats, OSD metrics. Creates node-diagnostics-TIMESTAMP/ with 30+ diagnostic files.
 Background
 Built from the 2026-01-28 incident where a single node failure (ocp-virt4-ceph7) caused 21 OSD crashes in 7 hours, affecting 124 VMs cluster-wide. Root cause: BlueStore::handle_watch_timeout likely from disk I/O issues + CPU overcommit (226%). See ROOT-CAUSE-ANALYSIS.md for full details.
