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
from litex.soc.interconnect import csr_eventmanager as ev

proc_set_version = """
proc proc_set_version { {version_number "1.0"} {core_revision_number "0"} {display_name "display TBD"} {description "description TBD"} } {
  # Management of version/revision
  set_property version $version_number [ipx::current_core]
  set_property core_revision  $core_revision_number [ipx::current_core]
  set_property display_name $display_name [ipx::current_core]
  set_property description $description [ipx::current_core]

}
"""

proc_archive_ip = """
proc proc_archive_ip { vendor_name ip_name {version_number "1.0"} } {
  # Management of archiving of the IP
  set archive_name "./"
  append archive_name $vendor_name "_" $ip_name "_" $version_number ".zip"
  ipx::archive_core $archive_name [ipx::current_core]
}
"""

proc_declare_interrupt = """
proc proc_declare_interrupt { irq_name } {
  # declaration of the interrupt
  ipx::infer_bus_interface $irq_name xilinx.com:signal:interrupt_rtl:1.0 [ipx::current_core]
}
"""

proc_add_bus_clock = """
proc proc_add_bus_clock {clock_signal_name bus_inf_name {reset_signal_name ""} {reset_signal_mode "slave"}} {
  set bus_inf_name_clean [string map {":" "_"} $bus_inf_name]
  set clock_inf_name [format "%s%s" $bus_inf_name_clean "_signal_clock"]
  set clock_inf [ipx::add_bus_interface $clock_inf_name [ipx::current_core]]
  set_property abstraction_type_vlnv "xilinx.com:signal:clock_rtl:1.0" $clock_inf
  set_property bus_type_vlnv "xilinx.com:signal:clock:1.0" $clock_inf
  set_property display_name $clock_inf_name $clock_inf
  set clock_map [ipx::add_port_map "CLK" $clock_inf]
  set_property physical_name $clock_signal_name $clock_map

  set assoc_busif [ipx::add_bus_parameter "ASSOCIATED_BUSIF" $clock_inf]
  set_property value $bus_inf_name $assoc_busif

  if { $reset_signal_name != "" } {
    set assoc_reset [ipx::add_bus_parameter "ASSOCIATED_RESET" $clock_inf]
    set_property value $reset_signal_name $assoc_reset

    set reset_inf_name [format "%s%s" $bus_inf_name_clean "_signal_reset"]
    set reset_inf [ipx::add_bus_interface $reset_inf_name [ipx::current_core]]
    set_property abstraction_type_vlnv "xilinx.com:signal:reset_rtl:1.0" $reset_inf
    set_property bus_type_vlnv "xilinx.com:signal:reset:1.0" $reset_inf
    set_property display_name $reset_inf_name $reset_inf
    set_property interface_mode $reset_signal_mode $reset_inf
    set reset_map [ipx::add_port_map "RST" $reset_inf]
    set_property physical_name $reset_signal_name $reset_map

    set reset_polarity [ipx::add_bus_parameter "POLARITY" $reset_inf]
    if {[string match {*[Nn]} $reset_signal_name] == 1} {
      set_property value "ACTIVE_LOW" $reset_polarity
    } else {
      set_property value "ACTIVE_HIGH" $reset_polarity
    }
  }
}
"""

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

    def generate_package(self, build_name):

        version_number = "1.3"
        # Create package directory
        package = "package_{}".format(build_name)
        shutil.rmtree(package, ignore_errors=True)
        os.makedirs(package)

        # Copy core files to package
        os.system("cp build/{}.v {}".format(build_name, package))

        # Prepare Vivado's tcl core packager script
        tcl = []
        # Declare Procedures
        tcl.append(proc_add_bus_clock)
        tcl.append(proc_declare_interrupt)
        tcl.append(proc_set_version)
        tcl.append(proc_archive_ip)
        # Create projet and send commands:
        tcl.append("create_project -force -name {}_packager".format(build_name))
        tcl.append("ipx::infer_core -vendor Enjoy-Digital -library user ./")
        tcl.append("ipx::edit_ip_in_project -upgrade true -name {} -directory {}.tmp component.xml".format(build_name, build_name))
        tcl.append("ipx::current_core component.xml")
        #SEBO: How to retrieve from LiteX the clock, reset and interface names?
        tcl.append("proc_add_bus_clock \"{}\" \"{}\" \"{}\"".format("axis_clk", "axis_in:axis_out", "axis_rst"))
        tcl.append("proc_add_bus_clock \"{}\" \"{}\" \"{}\"".format("axilite_clk", "axilite_in", "axilite_rst"))
        tcl.append("proc_declare_interrupt \"{}\"".format("irq"))
        tcl.append("ipx::update_checksums [ipx::current_core]")
        tcl.append("proc_set_version \"{}\" \"{}\" \"{}\"".format(version_number, "0", "axi_converter IP (Packaging Proof of Concept)"))
        tcl.append("ipx::save_core [ipx::current_core]")
        tcl.append("proc_archive_ip \"{}\" \"{}\" \"{}\"".format("Enjoy-Digital", build_name, version_number))
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
