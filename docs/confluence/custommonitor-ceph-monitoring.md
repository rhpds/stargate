# CustomMonitor Ceph Monitoring
# Confluence ID: 286753946
# URL: https://redhat.atlassian.net/wiki/spaces/RHPDS/pages/286753946

[data-colorid=qxju3rvnc3]{color:#666666} html[data-color-mode=dark] [data-colorid=qxju3rvnc3]{color:#999999}[data-colorid=ldz7s4ps63]{color:#666666} html[data-color-mode=dark] [data-colorid=ldz7s4ps63]{color:#999999}[data-colorid=o3ipuw9pk0]{color:#666666} html[data-color-mode=dark] [data-colorid=o3ipuw9pk0]{color:#999999}[data-colorid=p17vr4as3g]{color:#666666} html[data-color-mode=dark] [data-colorid=p17vr4as3g]{color:#999999}[data-colorid=mvw7bwyr8f]{color:#666666} html[data-color-mode=dark] [data-colorid=mvw7bwyr8f]{color:#999999}[data-colorid=v8sse4ykv2]{color:#666666} html[data-color-mode=dark] [data-colorid=v8sse4ykv2]{color:#999999}[data-colorid=lkx60utk5m]{color:#666666} html[data-color-mode=dark] [data-colorid=lkx60utk5m]{color:#999999}[data-colorid=u4esmqjceg]{color:#666666} html[data-color-mode=dark] [data-colorid=u4esmqjceg]{color:#999999}[data-colorid=ksstn9udt6]{color:#666666} html[data-color-mode=dark] [data-colorid=ksstn9udt6]{color:#999999} Description and purpose 
 This monitor checks the a ceph cluster using a read-only user. This uses the ceph cluster monitors setup instructions from:
 https://access.redhat.com/documentation/en-us/red_hat_ceph_storage/4/html-single/monitoring_ceph_with_nagios_guide/index 

 Dependencies 
 Must have a cephx user created with mon read permissions using the following command. For icinga, I would recommend using "icinga" so that we know exactly which tool is supposed to be accessing the cluster.
 # ceph auth get-or-create client.icinga mon 'allow r' > ceph.client.icinga.keyring 
 The client key and the ceph.conf must be installed into the host executing the commands such that the scripts are accessible. By default, this is in the ~/secrets directory of the icinga user.
 Packages and Binaries 
 The following RPM's must be installed on the host.
 ceph-common
 make
 openssl
 openssl-devel
 gcc
 make
 git
 python2-requests
 Configuration 
 Each host executing these commands must have the ceph.conf from the target ceph-cluster with only the sections listed as '[global]' and '[osd]'. However, depending on the system you must ensure that the ceph.conf's   mon host =   is correct for the version of the ceph client on that RHEL version.
 For RHEL 8, the system can handle newer ceph.conf variation and it can be copied directly as per below
 mon host = [v2:10.0.0.3:3300,v1:10.0.0.3:6789],[v2:10.0.0.4:3300,v1:10.0.0.4:6789],[v2:10.0.0.5:3300,v1:10.0.0.5:6789]
 For a RHEL 7 host, be sure that ONLY ONE IP Address is listed in the conf file, and the port for v1, for example:
 mon host = 10.0.0.3:6789,10.0.0.4:6789,10.0.0.5:6789

Note: each host must have 2 files: the ceph.conf and the keyring for the readonly user.
 For networking, the host executing the script must have IP-access to the mon nodes for the cluster.
 ./check_ceph_health -c ~/secrets/.ceph.<location>.conf -i icinga -k ~/secrets/.cephclient.icinga.keyring</code>
 [ -w operator count degraded ] #(int between 0 and n) -defaults to 0 
 [ -c ceph conf file ] #(int between 0 and n) - defaults to 0
 [ -f remote_host ]
 [ -s remote_user ]

 Execution should look something like this:
 [ icinga@mon01 src ] $ ./check_ceph_health -c ~/secrets/.ceph-dal.conf -i icinga -k ~/secrets/.ceph.client.icinga.keyring 
WARNING: MANY_OBJECTS_PER_PG ( 1 pools have many more objects per pg than average ) 
WARNING: MON_DISK_BIG ( mons dal10-mon-01,dal10-mon-02 are using a lot of disk space ) 
 [ icinga@mon01 src ] $

 Credentials 
 The following files must be available on the host executing teh script:
 ceph.client.icinga.keyring
 ceph.conf (updated as per the instructions in the "Configuration" section)
 Code repository 
 https://github.com/ceph/ceph-nagios-plugins 
 Monitoring System 
 This is deployed in   RHPDS_Icinga   , but the hosts on which it executes must be able to access the mon-hosts of the ceph cluster directly. If the nodes cannot, then by_ssh must be configured, or else a satellite built in the relevant environment.
 Configuring and Installing the Monitor 
 https://github.com/redhat-gpte/gpte-monitoring-config/tree/icinga-prod/zones.d/master/ 
 Any Additional Monitoring Server Configuration 
 N/A
