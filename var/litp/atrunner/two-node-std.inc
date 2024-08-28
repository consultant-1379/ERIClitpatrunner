#
# Standard 2-node cluster model.
#
# This is intended to be included in most AT scripts, to provide a basic model to which
# plugin-specific stuff can be added.
#
litp create -t os-profile -p /software/profiles/rhel_6 -o name='sample-profile' path='/profiles/node-iso'

litp create -t system -p /infrastructure/systems/sys1 -o system_name='sys1'
litp create -t system -p /infrastructure/systems/sys2 -o system_name='sys2'

litp create -t network -p /infrastructure/networking/networks/nodes -o subnet='10.4.23.0/24' litp_management='true' name='nodes'

litp create -t network-interface -p /ms/network_interfaces/if0 -o network_name='nodes' ipaddress='10.4.23.50'

litp create -t storage-profile-base -p /infrastructure/storage/storage_profiles/profile_1

litp create -t deployment -p /deployments/site1
litp create -t cluster -p /deployments/site1/clusters/cluster1
litp create -t node -p /deployments/site1/clusters/cluster1/nodes/node1 -o hostname='node1'
litp create -t node -p /deployments/site1/clusters/cluster1/nodes/node2 -o hostname='node2'

litp inherit -p /deployments/site1/clusters/cluster1/nodes/node1/system -s /infrastructure/systems/sys1
litp inherit -p /deployments/site1/clusters/cluster1/nodes/node2/system -s /infrastructure/systems/sys2

litp inherit -p /deployments/site1/clusters/cluster1/nodes/node1/os -s /software/profiles/rhel_6
litp inherit -p /deployments/site1/clusters/cluster1/nodes/node2/os -s /software/profiles/rhel_6

litp inherit -p /deployments/site1/clusters/cluster1/nodes/node1/storage_profile -s /infrastructure/storage/storage_profiles/profile_1
litp inherit -p /deployments/site1/clusters/cluster1/nodes/node2/storage_profile -s /infrastructure/storage/storage_profiles/profile_1

litp create -t network-interface -p /deployments/site1/clusters/cluster1/nodes/node1/network_interfaces/if0 -o network_name='nodes' ipaddress='10.4.23.51'
litp create -t network-interface -p /deployments/site1/clusters/cluster1/nodes/node2/network_interfaces/if0 -o ipaddress='10.4.23.52' network_name='nodes'
