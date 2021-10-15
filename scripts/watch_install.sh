#!/bin/bash
############################################################################
# Script to monitor the installation status of an OpenShift cluster
############################################################################

if [ $# -lt 1 ] ; then
    cat <<EOF
Usage $0 <clusterName>
EOF
    exit 1
fi

if [[ "${KUBECONFIG}" == "" ]] ; then
    echo "KUBECONFIG must point to the kubeconfig file for the hub cluster performing the install"
    exit 1
fi

export clusterName=$1
# Sometimes the installation CRs are in <name>-installer, check there first
ns=$1-installer
events=$( oc get agentclusterinstall -n $ns $1 -o jsonpath="{.status.debugInfo.eventsURL}" 2>/dev/null )
if [ "${events}" == "" ] ; then
  ns=$1
  events=$( oc get agentclusterinstall -n $ns $1 -o jsonpath="{.status.debugInfo.eventsURL}" )
fi
if [ "${events}" == "" ] ; then
    echo -e "\nFailed to retrieve events URL for $1"
    exit 1
fi
header(){
    echo -ne "\033[0;32m  Cluster: $clusterName   "
    TZ=UTC date +"%Y-%m-%d %H:%M:%S %Z" | tr -d '\n'
    echo -e "   (ctrl-c to stop monitoring)\033[0;1m"
}
events() {
    curl -s -k $events | jq -C '.[-4:] | .[] | {event_time,message}'
}
conditions() {
     oc get agentclusterinstall -n $ns $clusterName -o jsonpath='{.status.conditions}' | jq -C '.[] | select(.status=="False" or ( (.type=="Completed" or .type=="Failed" or .type=="Stopped") and .status=="True") ) | {lastTransitionTime, message, reason}'
}

export -f header
export -f events
export -f conditions
export events
export ns
export clusterName

watch -t --color -n 5 " header ; events ; echo ========; conditions"

