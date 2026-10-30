# Monitor: rhdp-aap2-jobs-status
# Confluence ID: 286753729
# URL: https://redhat.atlassian.net/wiki/spaces/RHPDS/pages/286753729

Description 
 This monitor makes 6 calls to the AAP2 cluster in question using a username and password (Stored in a secrets folder).
 Setup 
 In order to setup this monitor, the following must be done
 A monitoring user must be created in the AAP2 cluster (read only access to the system and the API)
 On the Icinga monitoring host, place the secret in ~icinga/secrets.<base url>.txt.
 Ensure the aap2_job_monitor.py script is in the correct location for custom monitors in Icinga
 Determine the levels that count as a warn or a crit for the following job types: running
 pending
 waiting

 Configure Icinga services

 Create a host and service entry stanza for the AAP2 system and service 
 In a host conf fine in the primary master's Icinga directory, create a generic entry for the master. It will use the dummy check command, as we're not actually checking a host, but we need a host which holds the service itself which receives the passive checks. Then create a service underneath that host in a service.conf file.
 Host entry 
 object Host "controller.aap5ao6oghnkg6u4.ansiblecloud.redhat.com" {
 check_command = "dummy"
 display_name = "Azure Dark Controller"
 vars.address = "controller.aap5ao6oghnkg6u4.ansiblecloud.redhat.com"
 vars.dummy_state = 0
 vars.client_endpoint = name
 #vars.ssh_port = 22
 vars.hostenv = "production"
 vars.hosttype = "linux"
 vars.notification.mail.groups = [ "icingaadmins" ]
}
 Service for Check 
 object Service "rhdp-aap2-jobs-status" {
 import "generic-service"
 host_name = "controller.aap5ao6oghnkg6u4.ansiblecloud.redhat.com"
 display_name = "AAP2 Job status"
 check_command = "check_aap2_job_counts"
 icon_image = "custom/api.png"
 max_check_attempts = 2
 check_interval = 15m
 retry_interval = 2m
 vars.aap2_url = "$host_name$"
 vars.secret_file = LocalSecretsDir + "/." + host_name + ".txt"
 vars.username = "monitor"
 vars.level_warn_pending = 10
 vars.level_crit_pending = 20
 vars.level_warn_running = 30
 vars.level_crit_running = 40
 vars.level_warn_waiting = 10
 vars.level_crit_waiting = 20
 notes_url = "https://wiki.wdc.infra.opentlc.com/index.php?title=Monitor:_$service.name$"
 notes = {{{To resolve this..
 * Login to the Babylon cluster in question
 * Based on what the error is, find that entity related to the workshop provision and resolve..
 * If not obvious, contact AnarchyDevs for assistance
 * Documentation is available here: <a href="https://wiki.wdc.infra.opentlc.com/index.php?title=Monitor:_rhdp-aap2-jobs-status">Monitor: rhdp-aap2-jobs-status</a> }}}
}
 Note, due to the heaviness of the AAP2 API calls (all extra vars for the first job are returned (!), we have limited the returned list to a single entry - but we cannot return 0 entries. So, one calls can return up to 1MB of data from the extra_vars. But, due to this, I am setting the monitor to only run every 15 minutes due to the heaviness of the run.
 Confirm the execution works from the command line as the user 
 From the command line, make the call to the to API from each host and confirm that the passive checks work properly.
 This curl command will send a request using the relevant ca files with the check results
 monitor command 
 $ python3 aap2_job_monitor.py -a controller.example.com -s /home/user/secrets/secret.txt -u monitor -p 0 -q 10 -r 0 -t 10 -w 0 -v 10
