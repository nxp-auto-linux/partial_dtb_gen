# MIT License

# Copyright 2021 NXP

# Permission is hereby granted, free of charge, to any person obtaining a
# copy of this software and associated documentation files (the "Software"),
# to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense,
# and/or sell copies of the Software, and to permit persons to whom the
# Software is furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
# OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
# FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.

"""
This tool generates partial DT files used for device passthrough in Xen
Dom0less VMs.
"""

import argparse
import re
import sys

# Check for Python >= 3.5
if sys.version_info.major < 3 or sys.version_info.minor < 5:
    raise Exception("Python version should be at least 3.5")

try:
    from pip import main as pipmain
except ImportError:
    from pip._internal import main as pipmain

try:
    import fdt
except ImportError:
    pipmain(['install', '--user', 'fdt'])
    import fdt


ADDRESS_CELLS_DEFAULT = 2
SIZE_CELLS_DEFAULT = 2
PAGE_SIZE = 0x1000

LINUX_DT = None
PARTIAL_DT = None

def page_round_up(num: int):
    """
    Rounds up the provided int number to the next PAGE_SIZE multiple.

    :param num: Provided int number to align up to PAGE_SIZE
    """
    return (num + PAGE_SIZE - 1) & ~(PAGE_SIZE - 1)

def page_round_down(num: int):
    """
    Rounds down the provided int number to the next PAGE_SIZE multiple.

    :param num: Provided int number to align down to PAGE_SIZE
    """
    return num & ~(PAGE_SIZE - 1)

def parse_memory_region_prop(target_node, reg):
    """
    Parses "memory-region" property of a node, finds and returns
    all associated memory nodes from Linux DT, with a matching phandle.

    :param target_node: Source node to get "memory-region" from
    :param reg: Reference to the "reg" property of the node,
                to which memory-regions "reg" properties will be appended.
    """
    mem_reg_nodes = []

    # Check if node has a "memory-region" property
    mem_reg = target_node.get_property("memory-region")
    if mem_reg:
        # Get all nodes with "phandle" property from Linux DT
        phandle_props = LINUX_DT.search(name="phandle",
                                        itype=fdt.ItemType.PROP_WORDS,
                                        path='/')
        for phandle_prop in phandle_props:
            # Phandle ID match
            if phandle_prop.data[0] in mem_reg:
                mem_reg_node = phandle_prop.parent
                # Add memory-region nodes with matching phandles to list
                mem_reg_nodes.append(mem_reg_node)
                # Append "reg" values to list
                for value in mem_reg_node.get_property("reg"):
                    reg.append(value)

    return mem_reg_nodes

def search_size_cells(target_node):
    """
    Looks for "size_cells" attribute of a node from current
    node towards parent.

    :param target_node: Current node
    """
    size_cells = target_node.get_property("#size-cells")
    if not size_cells:
        if target_node.parent:
            size_cells = search_size_cells(target_node.parent)
        else:
            return SIZE_CELLS_DEFAULT

    return size_cells

def search_address_cells(target_node):
    """
    Looks for "address_cells" attribute of a node from current
    node towards parent.

    :param target_node: Current node
    """
    address_cells = target_node.get_property("#address-cells")
    if not address_cells:
        if target_node.parent:
            address_cells = search_address_cells(target_node.parent)
        else:
            return ADDRESS_CELLS_DEFAULT

    return address_cells

def convert_to_xen_reg_prop(reg, address_cells, size_cells):
    """
    Parses a "reg" array and coverts it to "xen,reg" property
    format.
    (e.g. [<address_cells1> <size_cells1> ...] =>
          [<address_cells1> <size_cells1> <address_cells1> ...])

    :param reg: Reference to the "reg" array
    """
    # Check if reg contains memory range
    if size_cells == 0:
        return []

    idx = 0
    xen_reg = []
    while idx < len(reg):
        # Get '#address-cells' values, add them to xen_reg list
        address_cells_list = reg[idx:idx+address_cells]
        for i, val in enumerate(address_cells_list):
            address_cells_list[i] = page_round_down(val)

        xen_reg.extend(address_cells_list)
        idx += address_cells

        # Get '#size-cells' values, add them to xen_reg list
        # Round them up to PAGE_SIZE, so Xen can map it
        size_cells_list = reg[idx:idx+size_cells]
        for i, val in enumerate(size_cells_list):
            size_cells_list[i] = page_round_up(val)

        xen_reg.extend(size_cells_list)
        idx += size_cells

        # Append the address once again, as per "xen,reg" format
        xen_reg.extend(address_cells_list)

    return xen_reg

def add_xen_reg_prop(target_node):
    """
    Creates the "xen,reg" property for a node based on
    its "reg" property. Called recursively for all subnodes.

    :param target_node: Source node to create "xen,reg" for
    """

    print(target_node)
    reg = target_node.get_property("reg")
    if not reg:
        reg = []

    mem_reg_nodes = parse_memory_region_prop(target_node=target_node, reg=reg)

    # Convert "reg" array to "xen,reg"
    address_cells = search_address_cells(target_node.parent).data[0]
    size_cells = search_size_cells(target_node.parent).data[0]
    xen_reg = convert_to_xen_reg_prop(reg, address_cells, size_cells)

    # Add "xen,reg" property
    if xen_reg:
        target_node.set_property('xen,reg', xen_reg)

    # Repeat for all children recursively
    for subnode in target_node.nodes:
        mem_reg_nodes.extend(add_xen_reg_prop(subnode))

    return mem_reg_nodes

def arg_parse_error(err_msg, parser):
    """
    Helper function to print an error message in case that a required
    argument is missing.

    :param err_msg: Error message to print
    :param parser: Reference to ArgumentParser used
    """
    print(err_msg)
    parser.print_help()
    parser.exit(1)

def main():
    """
    Main function of the program, parses the options given as parameters,
    reads the DT files, takes the specified node from the Linux DT and adds
    it to the template DT, along with constructing its xen-specific properties.
    """
    global LINUX_DT, PARTIAL_DT

    parser = parse_args()
    arguments = parser.parse_args()
    if arguments.linux_dt is None:
        arg_parse_error("No Linux DT passed as argument.",
                        parser)
    if arguments.template_dt is None:
        arg_parse_error("No Template DT passed as argument.",
                        parser)
    if arguments.passthrough_node is None:
        arg_parse_error("No path to passthrough node passed as argument.",
                        parser)

    # Open Linux DTB
    with open(arguments.linux_dt, "rb") as fdt_file:
        LINUX_DT = fdt.parse_dtb(fdt_file.read())

    # Open Template DTS/DTB
    if "dtb" in arguments.template_dt.split('.')[-1]:
        with open(arguments.template_dt, "rb") as fdt_file:
            PARTIAL_DT = fdt.parse_dtb(fdt_file.read())
    elif "dts" in arguments.template_dt.split('.')[-1]:
        with open(arguments.template_dt, "r") as fdt_file:
            PARTIAL_DT = fdt.parse_dts(fdt_file.read())
    else:
        raise Exception("Please provide a Template \".dts\" or \".dtb\"" +
                        "-terminated file, accordingly.")

    # Search for wanted node in Linux DTB
    passthrough_node = arguments.passthrough_node.split('/')[-1]
    target_node_list = LINUX_DT.search(name=passthrough_node,
                                       itype=fdt.ItemType.NODE,
                                       path='/')
    if not target_node_list:
        raise Exception("Requested node not found")
    target_node = target_node_list[0]

    # Modify attributes of wanted node
    # Add "xen,path" attribute
    target_node.append(fdt.PropStrings('xen,path', arguments.passthrough_node))

    # Add "xen,force-assign-without-iommu" attribute
    target_node.append(fdt.Property('xen,force-assign-without-iommu'))

    # Add "xen,reg" attribute
    mem_reg_nodes = add_xen_reg_prop(target_node)

    # Add memory region nodes to new DT
    for mem_reg_node in mem_reg_nodes:
        PARTIAL_DT.add_item(mem_reg_node, path='/passthrough')

    # Remove unwanted properties
    pattern = re.compile("pinctrl-.*")
    found_props = []
    for prop in target_node.props:
        if re.search(pattern, prop.name):
            found_props.append(prop.name)

    for prop in found_props:
        target_node.remove_property(prop)

    # Add passthrough node in new DT
    template_node_list = PARTIAL_DT.search(name=passthrough_node,
                                    itype=fdt.ItemType.NODE,
                                    path='/')
    if not template_node_list:
        # Node doesn't already exist => Add full node
        PARTIAL_DT.add_item(target_node, path='/passthrough')
    else:
        # Get node from new DT
        template_node = template_node_list[0]

        # Merge node attributes (template <- template | original)
        template_node.merge(target_node, replace=False)

    with open("passthrough.dts", "w") as fdt_file:
        fdt_file.write(PARTIAL_DT.to_dts())

def parse_args():
    """
    ArgumentParser initialization function.
    """
    parser = argparse.ArgumentParser(
        description="This tool generates partial DT files used for " +
                    "device passthrough in Xen Dom0less VMs")

    parser.add_argument('-i', '--input_dt', dest='linux_dt',
                        help='''Path to Linux DTB file (e.g.
                                fsl-s32g274a-evb.dtb)''')
    parser.add_argument('-t', '--template_dt', dest='template_dt',
                        help='''Path to Template DTS/DTB file, based on which
                                the tool generates the Partial DTB''')
    parser.add_argument('-n', '--passthrough_node', dest='passthrough_node',
                        help='''Full path of node to be passthroughed, taken
                                from Linux DT as-is (e.g. "/ethernet@4033c000")
                        ''')

    return parser

main()
