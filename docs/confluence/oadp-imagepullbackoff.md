# OADP setup-oadp-credentials Job stuck in ImagePullBackOff
# Confluence ID: 492929166
# URL: https://redhat.atlassian.net/wiki/spaces/RHPDS/pages/492929166

Applies to GPTE OADP labs ( oadp-user1 .. oadp-userN , typically 20 namespaces per cluster) deployed via ArgoCD from the oadp Helm chart in redhat-gpte-devopsautomation/agnosticd_workload_helm_charts . Confirmed on two separate clusters (2026-09-30 / 2026-10-01), 20/20 namespaces affected on each. Treat as cluster-wide the moment you see it on one namespace.

 Symptom
 User reports OADP/Velero backups not configured, or the oadp-dpa DataProtectionApplication never reconciles. The one-time setup Job that writes backup credentials and patches the DPA never completes.
 Step 1 — Confirm the diagnosis

 oc get pods -n oadp-userN -l job-name=setup-oadp-credentials

 If the pod shows ImagePullBackOff , confirm with events:

 oc describe pod -n oadp-userN -l job-name=setup-oadp-credentials | tail -20

 Expect to see:

 Back-off pulling image "registry.redhat.io/openshift4/ose-cli:latest"

 Root cause: registry.redhat.io requires authenticated pull credentials, and the Job's service account ( cli-job-sa ) only carries the auto-generated internal-registry pull secret — nothing for registry.redhat.io . Do not just swap in a different tag of the same image (e.g. registry.redhat.io/openshift4/ose-cli-rhel9:v4.17 ) — same registry, same missing-credential problem.
 Step 2 — Check scope across the cluster
 This chart deploys one setup-oadp-credentials Job per user namespace. Check all of them before fixing just one — this has so far always been a cluster-wide chart bug, not a single-user issue:

 for n in $(seq 1 20); do
 ns="oadp-user${n}"
 img=$(oc get job setup-oadp-credentials -n "${ns}" -o jsonpath='{.spec.template.spec.containers[0].image}' 2>/dev/null)
 echo "${ns}: ${img:-not found}"
done

 Step 3 — Confirm the internal replacement image exists

 oc get is cli -n openshift -o jsonpath='{.status.dockerImageRepository}{"\n"}'
# expect: image-registry.openshift-image-registry.svc:5000/openshift/cli

 This cli imagestream (plain oc CLI image) exists on every standard OpenShift cluster in the openshift namespace, and is pullable by any authenticated service account via the default system:image-puller binding — no extra secret or RBAC change needed.
 Step 4 — Apply the fix, per namespace
 Job.spec.template is immutable — you cannot oc patch the image on an existing Job. It must be deleted and recreated.

 Save this jq filter once as /tmp/fix-oadp-job.jq :

 {
 apiVersion: "batch/v1",
 kind: "Job",
 metadata: {
 name: .metadata.name,
 namespace: .metadata.namespace,
 annotations: { "argocd.argoproj.io/tracking-id": .metadata.annotations["argocd.argoproj.io/tracking-id"] }
 },
 spec: {
 backoffLimit: .spec.backoffLimit,
 completions: .spec.completions,
 parallelism: .spec.parallelism,
 template: {
 spec: {
 containers: [ (.spec.template.spec.containers[0] | .image = "image-registry.openshift-image-registry.svc:5000/openshift/cli:latest" | {command, image, imagePullPolicy, name}) ],
 dnsPolicy: .spec.template.spec.dnsPolicy,
 restartPolicy: .spec.template.spec.restartPolicy,
 serviceAccount: .spec.template.spec.serviceAccount,
 serviceAccountName: .spec.template.spec.serviceAccountName,
 terminationGracePeriodSeconds: .spec.template.spec.terminationGracePeriodSeconds
 }
 }
 }
}

 Then loop over every affected namespace found in Step 2 (example covers 1–20):

 for n in $(seq 1 20); do
 ns="oadp-user${n}"
 echo "=== ${ns} ==="

 current_image=$(oc get job setup-oadp-credentials -n "${ns}" -o jsonpath='{.spec.template.spec.containers[0].image}' 2>/dev/null)
 if [[ -z "${current_image}" ]]; then
 echo " SKIP: job not found in ${ns}"
 continue
 fi
 if [[ "${current_image}" != *registry.redhat.io* ]]; then
 echo " SKIP: image already fixed (${current_image})"
 continue
 fi

 oc get job setup-oadp-credentials -n "${ns}" -o json | jq -f /tmp/fix-oadp-job.jq > "/tmp/job-${ns}-fixed.json"
 oc delete job setup-oadp-credentials -n "${ns}"
 oc apply -f "/tmp/job-${ns}-fixed.json"
done

 Step 5 — Verify
 For every namespace touched, confirm all three conditions:

 for n in $(seq 1 20); do
 ns="oadp-user${n}"
 job=$(oc get job setup-oadp-credentials -n "${ns}" -o jsonpath='{.status.succeeded}' 2>/dev/null)
 secret=$(oc get secret cloud-credentials -n "${ns}" >/dev/null 2>&1 && echo exists || echo MISSING)
 reconciled=$(oc get dataprotectionapplication oadp-dpa -n "${ns}" -o jsonpath='{.status.conditions[?(@.type=="Reconciled")].status}' 2>/dev/null)
 echo "${ns}: job_succeeded=${job:-0} secret=${secret} dpa_reconciled=${reconciled:-unknown}"
done

 Expect job_succeeded=1 , secret=exists , dpa_reconciled=True everywhere. If any namespace fails, check that its obc-backups secret/configmap and oadp-dpa DataProtectionApplication both exist first — the Job waits on both independently of the image fix, and will hang on that instead if they're missing.
 Notes
 ArgoCD's sync policy on these Applications is automated: {} with no explicit selfHeal: true , so this live fix is not immediately reverted by ArgoCD.

 This is a temporary, per-cluster, live workaround . The actual bug is in the upstream Helm chart template job_setup_odpa_credentials.yaml in redhat-gpte-devopsautomation/agnosticd_workload_helm_charts , which hardcodes image: registry.redhat.io/openshift4/ose-cli:latest . Any new deploy of this chart — a new cluster, or a namespace added later — will hit the same bug until that template is patched upstream. Remove this page once the upstream fix has shipped and been confirmed on a fresh deploy.

 Upstream fix status
 Upstream PR opened: agnosticd_workload_helm_charts#24 — swaps the hardcoded image for the in-cluster openshift/cli imagestream, same fix as Step 4 above. Not yet merged.
 Known AgnosticD role consuming this chart: ocp4_workload_oadp_gitops ( redhat-cop/agnosticd , ansible/roles_ocp_workloads/ocp4_workload_oadp_gitops ). Its defaults point the ArgoCD ApplicationSet source straight at this chart with no pin :

 ocp4_workload_oadp_gitops_repo: https://github.com/redhat-gpte-devopsautomation/agnosticd_workload_helm_charts.git
ocp4_workload_oadp_gitops_repo_tag: main
ocp4_workload_oadp_gitops_repo_path: oadp

 Known catalog item hit by this bug: Experience OpenShift Virtualization Roadshow (2026) ( openshift_cnv/ocp-virt-roadshow-2026 in AgnosticV). Its common.yaml only sets ocp4_workload_oadp_gitops_storage: odf (the setting that gates the broken Job template) and never overrides the repo/tag — so it inherits the main -tracking default above.
 Once PR #24 merges: every future provision of any catalog item using ocp4_workload_oadp_gitops with default settings (including Virt Roadshow 2026) automatically gets the fix. No AgnosticV/catalog-item change is required.

 Merging the PR will NOT retroactively heal an already-stuck environment. This role's ApplicationSet sets an explicit syncPolicy.automated: {prune: false, selfHeal: false} . Since the Job's image field is immutable, ArgoCD's next auto-sync attempt against an existing broken Job will error on the immutable-field diff rather than silently delete-and-recreate it. Any environment that is already stuck — beyond the two already fixed live on 2026-09-30/2026-10-01 — still needs the manual Steps 1-5 above after the merge, not just the merge itself.

 Testing before merge
 To validate the fix end-to-end before merging, the dev stage of openshift_cnv/ocp-virt-roadshow-2026 ( dev.yaml ) has been temporarily pointed at the fork branch instead of main :

 ocp4_workload_oadp_gitops_repo: https://github.com/andrew-jones/agnosticd_workload_helm_charts.git
ocp4_workload_oadp_gitops_repo_tag: fix/oadp-cli-imagepullbackoff

 Remove this override from dev.yaml once PR #24 merges and testing is complete , so dev reverts to tracking main like the other stages ( test.yaml / prod.yaml were never touched).
