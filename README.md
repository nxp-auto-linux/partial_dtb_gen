# Introduction
The partial_dtb_gen tool is a simple tool for creating partial DT files used
for passthrough of devices to Dom0less-DomUs running over Xen. The script
takes as input a complete Linux DTB file, a Template DTS/DTB file and a node
which to transfer from the former to the latter, updating its properties
with respect to the xen passthrough format. Also, the script will add all
the referenced memory-regions of the node to the output DTS file. The
output of the script is a "passthrough.dts" file, which will contain the
aforementioned characteristics.

# How to use
The tool takes the following (required) parameters:
* -i (--input_dt) <path_to_linux_dtb> - Path to a complete Linux DTB file,
        where the requested node's attributes/subnodes will be taken from
* -t (--template_dt) <path_to_template_dt> - Path to a baseline DTS file,
        which will be the starting point of the final product of the script.
        The node from the input DT will be merged with the already-existing
        node in the template DT, without overwriting its properties.
        Therefore, if we want to set some properties to the node, we should do
        it in the template DT, before the script is run.
* -n (--passthrough_node) <path_to_node> - Full path to the node we want
        to have in the script's output DT, along with its subnodes and
        memory-region references.

# Running example
Let's say we want to passthrough the '/ethernet@4033c000' node. We can run
the following command:
```shell
python3 partial_dtb_gen.py -i <path_to_linux_DTB> -t examples/template.dts -n "/ethernet@4033c000"
```