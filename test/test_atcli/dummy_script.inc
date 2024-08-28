### Create deployment items
# Infrastructure and software items

litp create -p /infrastructure/networking/networks/ip-range1 -t network -o name=sample-ip-range subnet=10.10.10.0/24
litp create -p /software/profiles/os-profile1 -t os-profile -o name=sample-os-profile path=/var/www/cobbler/ks_mirror/node-iso-x86_64
litp create -p /infrastructure/storage/storage_profiles/storage-profile1 -t storage-profile-base
litp create -p /infrastructure/systems/system1 -t system -o system_name=sample-system1
litp create -p /infrastructure/systems/system1/disks/disk0 -t disk -o name=hd0 size=512G bootable=true uuid="0x5000c50035ca73fe"
litp create -p /infrastructure/systems/system2 -t system -o system_name=sample-system2
litp create -p /infrastructure/systems/system2/disks/disk0 -t disk -o name=hd0 size=512G bootable=true uuid="0x5000c50035ca73fe"

# Deployment and clusters
litp create -p /deployments/litpcds_10168 -t deployment
litp create -p /deployments/litpcds_10168/clusters/cluster_1 -t cluster10168 -o ha_manager=vcs

# Cluster_1 nodes
litp create -p /deployments/litpcds_10168/clusters/cluster_1/nodes/node1 -t node -o hostname=c1-node1
litp create -p /deployments/litpcds_10168/clusters/cluster_1/nodes/node1/network_interfaces/ip1 -t network-interface -o network_name=sample-ip-range
litp inherit -p /deployments/litpcds_10168/clusters/cluster_1/nodes/node1/os -s /software/profiles/os-profile1
litp inherit -p /deployments/litpcds_10168/clusters/cluster_1/nodes/node1/storage_profile -s /infrastructure/storage/storage_profiles/storage-profile1
litp inherit -p /deployments/litpcds_10168/clusters/cluster_1/nodes/node1/system -s /infrastructure/systems/system1

litp create -p /deployments/litpcds_10168/clusters/cluster_1/nodes/node2 -t node -o hostname=c1-node2
litp create -p /deployments/litpcds_10168/clusters/cluster_1/nodes/node2/network_interfaces/ip1 -t network-interface -o network_name=sample-ip-range
litp inherit -p /deployments/litpcds_10168/clusters/cluster_1/nodes/node2/os -s /software/profiles/os-profile1
litp inherit -p /deployments/litpcds_10168/clusters/cluster_1/nodes/node2/storage_profile -s /infrastructure/storage/storage_profiles/storage-profile1
litp inherit -p /deployments/litpcds_10168/clusters/cluster_1/nodes/node2/system -s /infrastructure/systems/system2

litp create -p /software/items/foo1 -t mock-package -o name=foo1

litp inherit -p /deployments/litpcds_10168/clusters/cluster_1/nodes/node1/items/foo1 -s /software/items/foo1
litp inherit -p /deployments/litpcds_10168/clusters/cluster_1/nodes/node2/items/foo1 -s /software/items/foo1

litp create_plan
litp run_plan

# All nodes and clusters should be applied
assertState -p /deployments/litpcds_10168/clusters/cluster_1/nodes/node1 Applied
assertState -p /deployments/litpcds_10168/clusters/cluster_1/nodes/node2 Applied

