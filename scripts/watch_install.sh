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
watch --color -n 5 "curl -s -k $events | jq -C '.[-4:] | .[] | {event_time,message}' && echo '=========' && oc get agentclusterinstall -n $ns $1 -o jsonpath='{.status.conditions}' | jq -C '.[] | select(.status==\"False\" or ( (.type==\"Completed\" or .type==\"Failed\" or .type==\"Stopped\") and .status==\"True\") ) | {lastTransitionTime, message, reason}'"

