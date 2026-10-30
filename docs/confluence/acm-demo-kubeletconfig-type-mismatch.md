# ACM Demo — Pods stuck Pending due to KubeletConfig type mismatch
# Confluence ID: 481362807
# URL: https://redhat.atlassian.net/wiki/spaces/RHPDS/pages/481362807

Summary

 If you provision the ocp4-acm-demo catalog item and find a large number of pods stuck in Pending , the cause may not be resource exhaustion — it could be a failed KubeletConfig that never applied.

 Symptom

 20+ pods Pending across open-cluster-management , openshift-lightspeed , openshift-storage , openshift-cnv 

 Unable to provision managed clusters via ACM

 oc get kubeletconfig -o yaml shows a Failure condition:

 Error: KubeletConfig could not be unmarshalled, err: json: cannot
unmarshal string into Go struct field KubeletConfiguration.maxPods of type int32

 Root Cause

 maxPods and/or podsPerCore were defined as quoted strings ( "500" ) instead of integers ( 500 ) in the KubeletConfig spec. The config fails silently at apply time, leaving the node's pod ceiling at the OCP default — too low for the full ACM + OLS + CNV workload stack.

 Fix

 agnosticv PR #28128 corrects the type. After merge, new provisions will not hit this.

 Workaround (existing broken environments)

 Reprovision — there is no clean in-place fix once KubeletConfig has failed to apply.

 References

 agnosticv PR: https://github.com/rhpds/agnosticv/pull/28128 

 JSM ticket: https://redhat.atlassian.net/browse/RHDPSPPT-972 

 Diagnosed by Victor Aguilera, Sep 2026
