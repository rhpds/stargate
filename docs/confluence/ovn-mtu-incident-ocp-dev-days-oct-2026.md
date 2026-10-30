# OVN MTU Incident — ocp-dev-days Workshop Clusters (Oct 2026)
# Confluence ID: 506888435
# URL: https://redhat.atlassian.net/wiki/spaces/RHPDS/pages/506888435

Summary

 Date: October 21, 2026
 Severity: High (active White Glove workshop impacted)
 Status: Resolved
 Jira: RHDPOPS-24585 | RHDPSPPT-1158 

 DevSpaces Maven installs were hanging and Tekton pipeline image builds were taking 20+ minutes on ocp-dev-days-rdshw workshop clusters. Reported by Evan Shortiss (White Glove workshop vq2d86) and Cgruver (dev combined environment).

 Symptoms

 DevSpaces workspaces: Maven dependency downloads hang indefinitely during Camel lab startup

 Tekton pipelines: Single image build took >20 minutes (pod startup alone took 12 minutes)

 Affected: all ocp-dev-days-rdshw clusters with OVN-Kubernetes networking

 Root Cause

 Workshop clusters are provisioned on infrastructure with jumbo-frame NICs ( physical MTU 8900 ). The OVN-Kubernetes network operator was configured with mtu: 1400 — which is correct for standard 1500 MTU paths, but incorrect when the underlying physical interface runs at 8900.

 With this mismatch, the Geneve tunnel overhead calculation is wrong: OVN advertises the correct pod MTU to workloads, but the tunnel itself can handle much larger frames. This causes TCP Path MTU Discovery (PMTUD) failure : large TCP segments are silently dropped inside the Geneve overlay, causing connections to hang rather than recover. Maven downloads and container image pulls are particularly sensitive because they transfer large files over a single persistent TCP connection.

 Reference: Red Hat Solutions article 7136819 (hpbu-rhdp-roadshow-overhaul Slack, Aug 2026)

 Fix

 Patch the OVN-Kubernetes network operator to set mtu: 8800 (= 8900 physical − 100 bytes Geneve overhead):

 oc patch network.operator.openshift.io/cluster --type=merge \
 -p '{"spec":{"defaultNetwork":{"ovnKubernetesConfig":{"mtu":8800}}}}'

 OVN-K performs a rolling node restart automatically after this patch. Network performance recovers within ~15 minutes.

 Clusters Affected (workshop vq2d86 / z9qkt)

 GUID 
 Action 
 Result 

 gmmrr 
 Patched 1400 → 8800 
 Fixed 

 l669p 
 Patched 1400 → 8800 
 Fixed 

 x2jpk 
 Patched 1400 → 8800 
 Fixed 

 w5klv 
 Patched 1400 → 8800 
 Fixed (cgruver dev) 

 lnpjb 
 Already at 8800 
 No action needed 

 tptfg 
 Already at 8800 
 No action needed 

 ndslg 
 Already at 8800 
 No action needed 

 5k8vc 
 OpenShiftSDN 
 Fix not applicable 

 4nmm8 
 OpenShiftSDN 
 Fix not applicable 

 r5b4h 
 Provision failed 
 No cluster to fix 

 jcdmp 
 Provision failed 
 No cluster to fix 

 Prevention

 When provisioning new ocp-dev-days clusters on infrastructure with jumbo-frame NICs (8900 MTU), ensure the agnosticv/agnosticd configuration sets:

 ovn_kubernetes_mtu: 8800

 This prevents the default OVN MTU calculation (which assumes 1500 physical MTU) from being used incorrectly in jumbo-frame environments.

 Timeline

 Time (UTC) 
 Event 

 ~15:00 
 Cgruver reports 20+ minute Tekton build times on dev cluster 

 ~15:32 
 Evan Shortiss reports DevSpaces Maven hangs on White Glove workshop 

 ~16:00 
 Root cause identified: OVN MTU 1400 on 8900 MTU physical NICs 

 ~16:10 
 Fix applied to gmmrr (first cluster) 

 ~16:15 
 Fix rolled out to all remaining applicable clusters via parallel agents 

 ~16:30 
 All clusters patched; OVN rolling restart in progress
