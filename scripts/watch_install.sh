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

# Try to get the start time from the events URL
startTime=$( curl -sk $events | jq '.[] | select(.name=="cluster_registration_succeeded").event_time' | sed 's/"//g' )
if [[ "$startTime" == "" ]] ; then
    startTime=$( curl -sk $events | jq '.[0].event_time' | sed 's/"//g' )
fi

header(){
    echo -ne "\033[0;32m  Cluster: $clusterName   "
    #TZ=UTC date +"%Y-%m-%d %H:%M:%S %Z" | tr -d '\n'
    dur=$(( $(date -u +%s) - $(date -u -d $startTime +%s) ))
    hr=$(( $dur / 3600 ))
    min=$(( $(( $dur % 3600 )) / 60 ))
    sec=$(( $dur % 60 ))
    echo -ne " Duration $(printf '%02d:%02d:%02d' $hr $min $sec) "
    echo -e "   (ctrl-c to stop monitoring)\033[0;0m"
}
bmh(){
    echo -n "BareMetalHost: "
    oc get bmh -n $ns -o json | jq -j '.items[-1] |  "provisioning: ", .status.provisioning.state, "   power: ", .status.poweredOn, "   errors: ", .status.errorMessage '
    echo
}

agent(){
    agent=$(oc get agent -n $ns -o jsonpath='{range .items[*]}{.status.conditions[?(@.type=="SpecSynced")].message}{end}')
    if [[ $agent == *"error"* ]] ; then
        echo -e "Agent: \033[0;31m$agent   \033[0;0m "
    else
        echo -e "Agent: $agent   "
    fi
}

events() {
    echo "AgentClusterInstall Events"
    curl -s -k $events | jq -C '.[-4:] | .[] | {event_time,message}'
}
conditions() {
    echo "AgentClusterInstall Status"
    oc get agentclusterinstall -n $ns $clusterName -o jsonpath='{.status.conditions}' | jq -C '.[] | select(.status=="False" or ( (.type=="Completed" or .type=="Failed" or .type=="Stopped") and .status=="True") ) | {lastTransitionTime, message, reason}'
}

export -f header
export -f events
export -f conditions
export -f bmh
export -f agent
export startTime
export events
export ns
export clusterName

watch -t --color -n 5 " header ; bmh; agent; events ; echo ========; conditions"

