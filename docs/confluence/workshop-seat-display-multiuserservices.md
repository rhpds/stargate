# Fixing Workshop Seat Display (0/0 Users) - multiuserServices Issue
# Confluence ID: 418452816
# URL: https://redhat.atlassian.net/wiki/spaces/RHPDS/pages/418452816

Fixing Workshop Seat Display (0/0 Users)
 Problem: Workshop shows 0/0 seats/users when it should show actual user count (e.g., 110/110)
 Root Cause: Missing or false multiuserServices setting in workshop spec
 Fix Time: ~2 minutes (30-60 seconds after patching)

 When to Use This Fix
 Use this procedure when a workshop displays 0/0 for user/seat count but:
 The workshop should be multiuser (e.g., 50+ seats)

 ResourceClaims exist and are Ready

 WorkshopUsers exist in the namespace

 The catalog item is configured as multiuser

 This commonly happens when:
 Workshop was deployed without multiuserServices: true 

 Catalog item configuration was missing the multiuser flag

 Workshop was migrated from single-user to multiuser

 The Fix
 Automated Script (Recommended)
 Use the fix_multiuser_seats.sh script available on the ops bastion:

 ./fix_multiuser_seats.sh <namespace> <workshop-id>

# Example:
./fix_multiuser_seats.sh user-kherath-redhat-com a7uqj6

 The script will:
 Find the workshop by ID

 Set multiuserServices: true on the workshop

 Patch all ResourceClaims to trigger reconciliation

 Display verification commands

 Manual Steps (If Script Unavailable)
 If you need to fix it manually:
 Step 1: Enable multiuserServices on Workshop

 # Find the workshop
NAMESPACE="user-kherath-redhat-com"
WORKSHOP_ID="a7uqj6"

WORKSHOP_NAME=$(oc get workshops -n "$NAMESPACE" \
 -l "babylon.gpte.redhat.com/workshop-id=$WORKSHOP_ID" \
 -o name | head -1)

# Patch workshop to enable multiuserServices
oc patch "$WORKSHOP_NAME" -n "$NAMESPACE" \
 --type=merge \
 --patch='{"spec":{"multiuserServices":true}}'

 Step 2: Trigger ResourceClaim Reconciliation

 # Patch all ResourceClaims for this workshop
for RC in $(oc get resourceclaim -n "$NAMESPACE" \
 -l "babylon.gpte.redhat.com/workshop-id=$WORKSHOP_ID" \
 -o name); do
 oc patch -n "$NAMESPACE" \
 --type=merge \
 --patch='{"metadata":{"labels":{"touch":"now"}}}' \
 "$RC"
done

 Step 3: Verify the Fix

 # Wait 30-60 seconds, then check workshop status
oc get workshops -n "$NAMESPACE" \
 -l "babylon.gpte.redhat.com/workshop-id=$WORKSHOP_ID"

# Should now show correct user count (e.g., 110/110)

# Verify users are assigned
oc get workshopusers -n "$NAMESPACE" \
 -l "babylon.gpte.redhat.com/workshop-id=$WORKSHOP_ID" | wc -l

 What This Does
 The fix works by:
 Setting multiuserServices flag: Tells workshop-manager to enable multiuser mode, which activates user assignment and seat counting

 Triggering reconciliation: Patching ResourceClaims with a new label forces workshop-manager to recalculate workshop state

 Automatic propagation: workshop-manager updates seat counts based on existing WorkshopUsers

 Expected Behavior After Fix
 READY Workshop status shows actual user count (e.g., 110/110)

 READY Users can access their assigned environments

 READY UI displays correct seat utilization

 Troubleshooting
 Still showing 0/0 after 2 minutes
   Possible causes and fixes 
 No WorkshopUsers exist: Check oc get workshopusers -n $NAMESPACE 

 Workshop-manager not running: Check operator logs in babylon-events-prod 

 ResourceClaims not Ready: Check oc get resourceclaims -n $NAMESPACE 

 User count shows but is incorrect
   Possible causes and fixes 
 Stale WorkshopUser objects: Clean up old WorkshopUsers that should have been deleted

 Duplicate assignments: Check for duplicate WorkshopUser objects per user

 Script Location
 The script is available at:
 Ops bastion: /home/bbethell/fix_multiuser_seats.sh 

 Git repo: rhpds-utils/scripts/fix_multiuser_seats.sh (if committed)

 Related Issues
 RHDP Workshop Automation — Ops Runbook 

 Original fix by @kherath for workshop rh-workshop-2026-03-05-experience-openshift-virtualization-with-aro-110-users 

 Contact
 For questions or issues with this procedure:
 Slack: #rhdp-ops 

 Maintainer: Unlicensed user 

 Last updated: 2026-06-10 | Status: Active
