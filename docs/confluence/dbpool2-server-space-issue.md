# DBpool2 server space issue
# Confluence ID: 286753318
# URL: https://redhat.atlassian.net/wiki/spaces/RHPDS/pages/286753318

This document explains process on clean up of FS on DBpool server. Alert example : root file system hits 93%, Please follow below steps to fix 1) login to the server using VIP # ssh root@150.239.16.64 -p 65220 -i .ssh/opentlc_admin_backdoor.pem 2) check the FS status using df -h 3) Under root home directory find script with name cleanarchive.sh 4) Run the script as root user , Script will cleanup old archive files [root@dbpool02 ~]# ./cleanarchive.sh Please refer dbpool wiki page to understand more about pgpools. https://wiki.wdc.infra.opentlc.com/index.php?title=PostgreSQL_Database_Architecture
