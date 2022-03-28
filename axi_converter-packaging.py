#!/usr/bin/env python3

import os
import shutil
import argparse
import re

from migen import *

from litex.build import tools
from litex.build.generic_platform import *
from litex.build.xilinx import XilinxPlatform

from litex.soc.interconnect import stream
from litex.soc.interconnect.axi import *
from litex.soc.interconnect import csr_eventmanager as ev
from litex.soc.interconnect import wishbone

# GUI Interfaces -----------------------------------------------------------------------------------

def get_gui_interface():
    return {
        'AXI Lite' : 
            {
            'order': 0,
            'vars' : 
                {
                'address_width' : 
                    {
                    'order' : 0,
                    },
                },
            },
        'AXI Stream' :
            {
            'order': 1,
            'vars' : 
                {
                'input_width' : 
                    {
                    'order' : 0,
                    },
                'output_width' : 
                    {
                    'order' : 1,
                    },
                'user_width' : 
                    {
                    'order' : 2,
                    },
                },
            },
        'Misc' :
            {
            'order': 2,
            'vars' : 
                {
                'reverse' : 
                    {
                    'order' : 0,
                    },
                },
            },
    }

# Custom Interfaces -------------------------------------------------------------------------------

def get_custom_interface():
    return {
        'wishbone' : 
            {
            'name': 'wishbone_in',
            'type': 'slave',
            'signals' : 
                {
                    'wishbone_in_adr'   : 'wishbone_adr',
                    'wishbone_in_dat_w' : 'wishbone_dat_w',
                    'wishbone_in_dat_r' : 'wishbone_dat_r',
                    'wishbone_in_sel'   : 'wishbone_sel',
                    'wishbone_in_cyc'   : 'wishbone_cyc',
                    'wishbone_in_stb'   : 'wishbone_stb',
                    'wishbone_in_ack'   : 'wishbone_ack',
                    'wishbone_in_we'    : 'wishbone_we',
                    'wishbone_in_cti'   : 'wishbone_cti',
                    'wishbone_in_bte'   : 'wishbone_bte',
                    'wishbone_in_err'   : 'wishbone_err',
                },
            },
    }


def declare_custom_interface():
    return {
        'wishbone' : 
            {
            'signals' : 
                [
                    ("wishbone_adr","30","input"),
                    ("wishbone_dat_w","16","input"),
                    ("wishbone_dat_r","16","output"),
                    ("wishbone_sel","2","input"),
                    ("wishbone_cyc","1","input"),
                    ("wishbone_stb","1","input"),
                    ("wishbone_ack","1","output"),
                    ("wishbone_we","1","input"),
                    ("wishbone_cti","3","input"),
                    ("wishbone_bte","2","input"),
                    ("wishbone_err","1","output"),
                ],
            },
    }

# Interfaces Clock & resets ------------------------------------------------------------------------

def get_interface_clocks():
    return {
        'Wishbone' :
           {
            'clock_domain': 'axilite_clk',
            'reset': 'axilite_rst',
            'interfaces': 'wishbone_in',
            },
        'AXI Stream' :
            {
            'clock_domain': 'axis_clk',
            'reset': 'axis_rst',
            'interfaces': 'axis_in:axis_out',
            },
        'AXI Lite' : 
            {
            'clock_domain': 'axilite_clk',
            'reset': 'axilite_rst',
            'interfaces': 'axilite_in',
            },
    }

# IOs/Interfaces -----------------------------------------------------------------------------------

def get_clkin_ios():
    return [
        ("axis_clk",  0, Pins(1)),
        ("axis_rst",  0, Pins(1)),
        ("axilite_clk",  0, Pins(1)),
        ("axilite_rst",  0, Pins(1)),
        ("irq"    ,  0, Pins(1)),
    ]

# AXIConverter -------------------------------------------------------------------------------------

class AXIConverter(Module):
    def __init__(self, platform, address_width=64, input_width=64, output_width=64, user_width=0, reverse=False):
        # SAve input parameter as generic for later use.
        self.address_width = address_width
        self.input_width   = input_width
        self.output_width  = output_width
        self.user_width    = user_width
        self.reverse       = reverse
        # Clocking ---------------------------------------------------------------------------------
        platform.add_extension(get_clkin_ios())
        self.clock_domains.cd_sys  = ClockDomain()
        self.comb += self.cd_sys.clk.eq(platform.request("axis_clk"))
        self.comb += self.cd_sys.rst.eq(platform.request("axis_rst"))

        self.clock_domains.cd_syslite  = ClockDomain()
        self.comb += self.cd_syslite.clk.eq(platform.request("axilite_clk"))
        self.comb += self.cd_syslite.rst.eq(platform.request("axilite_rst"))

        # Input AXI Lite ---------------------------------------------------------------------------
        axilite_in = AXILiteInterface(data_width=32, address_width=address_width, clock_domain="cd_syslite")
        platform.add_extension(axilite_in.get_ios("axilite_in"))
        self.comb += axilite_in.connect_to_pads(platform.request("axilite_in"), mode="slave")

        # Input AXI --------------------------------------------------------------------------------
        axis_in = AXIStreamInterface(data_width=input_width, user_width=user_width)
        platform.add_extension(axis_in.get_ios("axis_in"))
        self.comb += axis_in.connect_to_pads(platform.request("axis_in"), mode="slave")

        # Output AXI -------------------------------------------------------------------------------
        axis_out = AXIStreamInterface(data_width=output_width, user_width=user_width)
        platform.add_extension(axis_out.get_ios("axis_out"))
        self.comb += axis_out.connect_to_pads(platform.request("axis_out"), mode="master")

        # Custom interface -----------------------------------------------------------------------
        wishbone_in = wishbone.Interface(data_width=16)
        platform.add_extension(wishbone_in.get_ios("wishbone_in"))
        self.comb += wishbone_in.connect_to_pads(platform.request("wishbone_in"), mode="slave")

        self.submodules.ev = ev.EventManager()
        self.ev.my_int1 = ev.EventSourceProcess()
        self.ev.my_int2 = ev.EventSourceProcess()
        self.ev.finalize()

        self.comb += self.ev.my_int1.trigger.eq(0)
        self.comb += self.ev.my_int2.trigger.eq(1)

        self.comb += platform.request("irq").eq(self.ev.irq)

        # Converter --------------------------------------------------------------------------------
        converter = stream.StrideConverter(axis_in.description, axis_out.description, reverse=reverse)
        self.submodules += converter
        self.comb += axis_in.connect(converter.sink)
        self.comb += converter.source.connect(axis_out)

        # ILA ---------------------------------------------------------------------------------------
        platform.add_source("ila/ila.xci")
        probe0 = Signal(2)
        self.comb += probe0.eq(Cat(self.ev.irq, self.ev.my_int1.trigger))
        self.specials += [
            Instance("ila", i_clk=self.cd_sys.clk, i_probe0=probe0),
        ]

    def generate_project(self, build_name):
        part = "xc7z010iclg225-1L"

        # Create project directory
        project = "project_{}".format(build_name)
        # Create package directory
        # package = "package_{}".format(build_name)
        package = "package"
        
        shutil.rmtree(project, ignore_errors=True)
        os.makedirs(project)

        # Prepare Vivado's tcl core packager script
        tcl = []
        # set variable names
        tcl.append("set project_dir \"{}\"".format(project))
        tcl.append("set design_name \"{}\"".format(build_name))
        tcl.append("set part \"{}\"".format(part))
        # set up project
        tcl.append("create_project $design_name $project_dir -part $part -force")
        # set up IP repo
        tcl.append("set lib_dirs  [list  ../{} ../{} ]".format(package, "interfaces"))
        tcl.append("set_property ip_repo_paths $lib_dirs [current_fileset]")
        tcl.append("update_ip_catalog")
        # set up bd design
        tcl.append("create_bd_design $design_name")
        #build the BD
        tcl.append("source ../bd_axi_converter_128b_to_64b.tcl")
        #Validate the design
        tcl.append("validate_bd_design")
        tcl.append("regenerate_bd_layout")
        tcl.append("save_bd_design")

        tools.write_to_file(project + "/project.tcl", "\n".join(tcl))

        # Run Vivado's tcl core packager script
        os.system("cd {} && vivado -source project.tcl".format(project))


# Build --------------------------------------------------------------------------------------------

def main():
    # build_gui()
    # exit()
    parser = argparse.ArgumentParser(description="AXI Converter core")
    parser.add_argument("--input-width",   default=128,         help="AXI input data width  (default=128).")
    parser.add_argument("--output-width",  default=64,          help="AXI output data width (default=64).")
    parser.add_argument("--user-width",    default=0,           help="AXI user width (default=0).")
    parser.add_argument("--reverse",       action="store_true", help="Reverse converter ordering.")
    parser.add_argument("--build",         action="store_true", help="Build core")
    parser.add_argument("--package",       action="store_true", help="Package core")
    parser.add_argument("--project",       action="store_true", help="Create project including the core")
    args = parser.parse_args()

    # Generate core --------------------------------------------------------------------------------

    get_generic_parameters = [
            ("address_width",  64),
            ("input_width",  int(args.input_width)),
            ("output_width", int(args.output_width)),
            ("user_width", int(args.user_width)),
            ("reverse"    ,  args.reverse),
    ]

    input_width  = int(args.input_width)
    output_width = int(args.output_width)
    user_width   = int(args.user_width)
    build_name   = "axi_converter_{}b_to_{}b".format(input_width, output_width)
    platform     = XilinxPlatform("", io=[], toolchain="vivado")
    module       = AXIConverter(platform,
        input_width  = input_width,
        output_width = output_width,
        user_width   = user_width,
        reverse      = args.reverse)
    if args.build:
        platform.build(module, build_name=build_name, run=False)
    if args.package:
        file_list = ["../ila/ila.xci", "../build/"+build_name+".xdc", "../build/"+build_name+".v"]
        platform.packaging.version_number = "1.3"
        # exit()
        platform.package(build_name=build_name, file_list=file_list, 
            clock_domain=get_interface_clocks(),
            generic_parameters=get_generic_parameters,
            gui_description=get_gui_interface(),
            custom_interface=get_custom_interface(),
            declare_interface=declare_custom_interface(),
            interrupt = "irq",
            run=True)
    if args.project:
        module.generate_project(build_name)

if __name__ == "__main__":
    main()
