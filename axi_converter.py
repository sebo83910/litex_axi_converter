#!/usr/bin/env python3

import os
import shutil
import argparse

from migen import *

from litex.build import tools
from litex.build.generic_platform import *
from litex.build.xilinx import XilinxPlatform

from litex.soc.interconnect import stream
from litex.soc.interconnect.axi import *

# IOs/Interfaces -----------------------------------------------------------------------------------

def get_clkin_ios():
    return [
        ("axi_clk",  0, Pins(1)),
        ("axi_rst",  0, Pins(1)),
    ]

# AXIConverter -------------------------------------------------------------------------------------

class AXIConverter(Module):
    def __init__(self, platform, input_width=64, output_width=64, user_width=0, reverse=False):
        # Clocking ---------------------------------------------------------------------------------
        platform.add_extension(get_clkin_ios())
        self.clock_domains.cd_sys  = ClockDomain()
        self.comb += self.cd_sys.clk.eq(platform.request("axi_clk"))
        self.comb += self.cd_sys.rst.eq(platform.request("axi_rst"))

        # Input AXI --------------------------------------------------------------------------------
        axi_in = AXIStreamInterface(data_width=input_width, user_width=user_width)
        platform.add_extension(axi_in.get_ios("axi_in"))
        self.comb += axi_in.connect_to_pads(platform.request("axi_in"), mode="slave")

        # Output AXI -------------------------------------------------------------------------------
        axi_out = AXIStreamInterface(data_width=output_width, user_width=user_width)
        platform.add_extension(axi_out.get_ios("axi_out"))
        self.comb += axi_out.connect_to_pads(platform.request("axi_out"), mode="master")

        # Converter --------------------------------------------------------------------------------
        converter = stream.StrideConverter(axi_in.description, axi_out.description, reverse=reverse)
        self.submodules += converter
        self.comb += axi_in.connect(converter.sink)
        self.comb += converter.source.connect(axi_out)

    def generate_package(self, build_name):
        # Create package directory
        package = "package_{}".format(build_name)
        shutil.rmtree(package, ignore_errors=True)
        os.makedirs(package)

        # Copy core files to package
        os.system("cp build/{}.v {}".format(build_name, package))

        # Prepare Vivado's tcl core packager script
        tcl = []
        tcl.append("create_project -force -name {}_packager".format(build_name))
        tcl.append("ipx::infer_core -vendor Enjoy-Digital -library user ./")
        tcl.append("ipx::edit_ip_in_project -upgrade true -name {} -directory {}.tmp component.xml".format(build_name, build_name))
        tcl.append("ipx::current_core component.xml")
        tcl.append("ipx::update_checksums [ipx::current_core]")
        tcl.append("ipx::save_core [ipx::current_core]")
        tcl.append("close_project")
        tcl.append("exit")
        tools.write_to_file(package + "/packager.tcl", "\n".join(tcl))

        # Run Vivado's tcl core packager script
        os.system("cd {} && vivado -mode batch -source packager.tcl".format(package))

    def generate_project(self, build_name):
        part = "XC7Z010-CLG225-1"

        # Create project directory
        project = "project_{}".format(build_name)
        
        shutil.rmtree(project, ignore_errors=True)
        os.makedirs(project)

        # Prepare Vivado's tcl core packager script
        tcl = []
        tcl.append("set project_dir \"{}\"".format(project))
        tcl.append("set design_name \"{}\"".format(build_name))
        # set up IP repo
        tcl.append("set lib_dirs  [list  .. ]")
        tcl.append("set_property ip_repo_paths $lib_dirs [current_fileset]")
        tcl.append("update_ip_catalog")
        # set up bd design
        tcl.append("create_bd_design $design_name")
        #build the BD
        tcl.append("create_bd_cell -type ip -vlnv Enjoy-Digital:user:axi_converter_128b_to_64b:1.0 axi_converter_128b_t_0")
        tcl.append("apply_bd_automation -rule xilinx.com:bd_rule:clkrst -config {Clk \"New Clocking Wizard (100 MHz)\" }  [get_bd_pins axi_converter_128b_t_0/axi_clk]")
        tcl.append("make_bd_pins_external  [get_bd_pins clk_wiz/reset]")
        tcl.append("make_bd_pins_external  [get_bd_pins clk_wiz/clk_in1]")
        tcl.append("make_bd_intf_pins_external  [get_bd_intf_pins axi_converter_128b_t_0/axi_in]")
        tcl.append("make_bd_intf_pins_external  [get_bd_intf_pins axi_converter_128b_t_0/axi_out]")
        #Validate the design
        tcl.append("validate_bd_design")
        tcl.append("regenerate_bd_layout")
        tcl.append("save_bd_design")

        tools.write_to_file(project + "/project.tcl", "\n".join(tcl))

        # Run Vivado's tcl core packager script
        os.system("cd {} && vivado -source project.tcl".format(project))


# Build --------------------------------------------------------------------------------------------

def main():
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
    input_width  = int(args.input_width)
    output_width = int(args.output_width)
    user_width   = int(args.user_width)
    platform   = XilinxPlatform("", io=[], toolchain="vivado")
    module     = AXIConverter(platform,
        input_width  = input_width,
        output_width = output_width,
        user_width   = user_width,
        reverse      = args.reverse)
    build_name = "axi_converter_{}b_to_{}b".format(input_width, output_width)
    if args.build:
        platform.build(module, build_name=build_name, run=False, regular_comb=False)
    if args.package:
        module.generate_package(build_name)
    if args.project:
        module.generate_project(build_name)

if __name__ == "__main__":
    main()
