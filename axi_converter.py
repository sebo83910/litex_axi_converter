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

proc_define_interface = """
proc proc_define_interface { name } {
  
  ipx::create_abstraction_definition Enjoy-Digital.com interface ${name}_rtl 1.0
  ipx::create_bus_definition Enjoy-Digital.com interface $name 1.0

  set_property xml_file_name ${name}_rtl.xml [ipx::current_busabs]
  set_property xml_file_name ${name}.xml [ipx::current_busdef]
  set_property bus_type_vlnv Enjoy-Digital.com:interface:${name}:1.0 [ipx::current_busabs]

  ipx::save_abstraction_definition [ipx::current_busabs]
  ipx::save_bus_definition [ipx::current_busdef]

}
"""

proc_define_interface_port = """
proc proc_define_interface_port {name width dir {type none}} {

  ipx::add_bus_abstraction_port $name [ipx::current_busabs]
  set m_intf [ipx::get_bus_abstraction_ports $name -of_objects [ipx::current_busabs]]
  set_property master_presence required $m_intf
  set_property slave_presence  required $m_intf
  set_property master_width $width $m_intf
  set_property slave_width  $width $m_intf

  set m_dir "in"
  set s_dir "out"
  if {$dir eq "output"} {
    set m_dir "out"
    set s_dir "in"
  }

  set_property master_direction $m_dir $m_intf
  set_property slave_direction  $s_dir $m_intf

  if {$type ne "none"} {
    set_property is_${type} true $m_intf
  }

  ipx::save_bus_definition [ipx::current_busdef]
  ipx::save_abstraction_definition [ipx::current_busabs]
}
"""

proc_set_version = """
proc proc_set_version { {ip_name "ip_tbd"}   \
                        {version_number "1.0"}  \
                        {core_revision_number "0"}  \
                        {display_name "display TBD"}  \
                        {description "description TBD"}  \
                        {vendor_name "Enjoy-Digital"}   \
                        {company_url "http://www.enjoy-digital.fr/"}  \
  } {
  # Management of version/revision
  set_property version $version_number [ipx::current_core]
  set_property core_revision  $core_revision_number [ipx::current_core]
  set_property display_name $display_name [ipx::current_core]
  set_property description $description [ipx::current_core]

  set_property name $ip_name [ipx::current_core]
  set_property vendor_display_name $vendor_name [ipx::current_core]
  set_property company_url $company_url [ipx::current_core]

}
"""

proc_set_device_family = """
proc proc_set_device_family { {setting "all"} } {
  # Management of supported families
  if { $setting eq "all" } {
      set i_families ""
      foreach i_part [get_parts] {
        lappend i_families [get_property FAMILY $i_part]
      }
      set i_families [lsort -unique $i_families]
      set s_families [get_property supported_families [ipx::current_core]]
      foreach i_family $i_families {
        set s_families "$s_families $i_family Production"
        set s_families "$s_families $i_family Beta"
      }
  } else {
    set s_families $setting
  }
  set_property supported_families $s_families [ipx::current_core]
  puts "got $s_families.\n"
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

proc_add_bus = """
# Add a new port map definition to a bus interface.
proc proc_add_port_map {bus phys logic} {
  set map [ipx::add_port_map $phys $bus]
  set_property "PHYSICAL_NAME" $phys $map
  set_property "LOGICAL_NAME" $logic $map
}

proc proc_add_bus {bus_name mode abs_type bus_type port_maps} {
  set bus [ipx::add_bus_interface $bus_name [ipx::current_core]]

  set_property "ABSTRACTION_TYPE_VLNV" $abs_type $bus
  set_property "BUS_TYPE_VLNV" $bus_type $bus
  set_property "INTERFACE_MODE" $mode $bus

  foreach port_map $port_maps {
    proc_add_port_map $bus {*}$port_map
  }
}

"""

proc_add_ip_files = """
proc proc_add_ip_files {ip_name ip_files} {
  set proj_fileset [get_filesets sources_1]
  foreach m_file $ip_files {
    puts "got the following file to add: $m_file.\n"
    if {[file extension $m_file] eq ".xdc"} {
      add_files -copy_to ./src -norecurse -fileset constrs_1 $m_file
    } else {
      add_files -copy_to ./src -norecurse -fileset $proj_fileset $m_file
    }
  }
  set_property "top" "$ip_name" $proj_fileset
}
"""

wishbone_add_bus = """
proc_add_bus "wishbone_in" "slave" \
    "Enjoy-Digital.com:interface:wishbone_rtl:1.0" \
    "Enjoy-Digital.com:interface:wishbone:1.0" \
    { \
        {"wishbone_in_adr" "wishbone_in_adr"} \
        {"wishbone_in_dat_w" "wishbone_in_dat_w"} \
        {"wishbone_in_dat_r" "wishbone_in_dat_r"} \
        {"wishbone_in_sel" "wishbone_in_sel"} \
        {"wishbone_in_cyc" "wishbone_in_cyc"} \
        {"wishbone_in_stb" "wishbone_in_stb"} \
        {"wishbone_in_ack" "wishbone_in_ack"} \
        {"wishbone_in_we" "wishbone_in_we"} \
        {"wishbone_in_cti" "wishbone_in_cti"} \
        {"wishbone_in_bte" "wishbone_in_bte"} \
        {"wishbone_in_err" "wishbone_in_err"} \
    }
"""

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

def build_gui():

    dict_gui = get_gui_interface()
    string = '# Set GUI properties\n'
    #Parse keys to retrieve the group names.
    for group in dict_gui:
        string1 =  'ipgui::add_group -name {'+group+'} -component [ipx::current_core] '
        string1 += '-parent [ipgui::get_pagespec -name "Page 0" '
        string1 += '-component [ipx::current_core] ] -display_name {'+group+'} -layout {vertical}\n'
        string += string1 
    #Parse vars to retrieve the generic names & order.
    for group in dict_gui:
        vari = dict_gui[group]['vars']
        for var in vari:
            string2 =  'ipgui::move_param -component [ipx::current_core] '
            string2 += '-order '+str(vari[var]['order'])+' [ipgui::get_guiparamspec -name "'+var+'" '
            string2 += '-component [ipx::current_core]] -parent [ipgui::get_groupspec '
            string2 += '-name "'+group+'" -component [ipx::current_core]]\n'
            string2 += 'set_property enablement_value false [ipx::get_user_parameters '+var+' -of_objects [ipx::current_core]]\n'

            string += string2
    return(string)

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

    # Verilog Post Processing --------------------------------------------------------------------------
    def _netlist_post_processing(self, infile, outfile):
        Found = False
        with open(infile, 'r') as reader:
            #print ("Name of the file: ", reader.name)
            inline = reader.readlines()

        with open(outfile, 'w') as writer:
            #print ("Name of the file: ", writer.name)
            for line in inline:
                writer.write(line)
                m = re.search("^\);\n", line)
                if m and not Found:
                    writer.write("parameter {} = {};\n".format("address_width",self.address_width))
                    writer.write("parameter {} = {};\n".format("input_width",self.input_width))
                    writer.write("parameter {} = {};\n".format("output_width",self.output_width))
                    writer.write("parameter {} = {};\n".format("user_width",self.user_width))
                    writer.write("parameter {} = {};\n".format("reverse",0))
                    Found = True

    # XDC Post Processing --------------------------------------------------------------------------
    def _constraints_post_processing(self, infile, outfile):
        Found = False
        with open(infile, 'r') as reader:
            #print ("Name of the file: ", reader.name)
            inline = reader.readlines()

        with open(outfile, 'w') as writer:
            #print ("Name of the file: ", writer.name)
            for line in inline:
                m = re.search("Design constraints", line)
                if m:
                    Found = True
                if Found:
                    writer.write(line)

    def generate_package(self, build_name):

        version_number = "1.3"
        # Create package directory
        package = "package_{}".format(build_name)
        shutil.rmtree(package, ignore_errors=True)
        os.makedirs(package)

        # Copy core files to package
        os.system("cp -r ila/ila.xci {}".format(package))
        self._netlist_post_processing("build/{}.v".format(build_name),"{}/{}.v".format(package,build_name))
        self._constraints_post_processing("build/{}.xdc".format(build_name),"{}/{}.xdc".format(package,build_name))
        # SEBO : Issue #11.
        
        # Prepare Vivado's tcl core packager script
        tcl = []
        # Declare Procedures
        tcl.append(proc_add_ip_files)
        tcl.append(proc_add_bus)
        tcl.append(proc_add_bus_clock)
        tcl.append(proc_declare_interrupt)
        tcl.append(proc_set_version)
        tcl.append(proc_set_device_family)
        tcl.append(proc_archive_ip)
        # Create projet and send commands:
        tcl.append("create_project -force -name {}_packager".format(build_name))

        #Add files
        tcl.append("proc_add_ip_files \"{}\"  \"{}\" ".format(build_name, "[list \"./ila.xci\" \"./"+build_name+".xdc\" \"./"+build_name+".v\"]"))
        
        tcl.append("ipx::package_project -root_dir . -vendor Enjoy-Digital.com -library user -taxonomy /Enjoy_Digital")
        tcl.append("set_property name {} [ipx::current_core]".format(build_name))
        # tcl.append("proc_set_device_family \"zynq Production\"")
        tcl.append("proc_set_device_family \"all\"")
        tcl.append("ipx::save_core [ipx::current_core]")

        tcl.append(wishbone_add_bus)
        tcl.append("proc_add_bus_clock \"{}\" \"{}\" \"{}\"".format("axilite_clk", "wishbone_in", "axilite_rst"))
        
        #FIXME: How to retrieve from LiteX the clock, reset and interface names?
        tcl.append("proc_add_bus_clock \"{}\" \"{}\" \"{}\"".format("axis_clk", "axis_in:axis_out", "axis_rst"))
        tcl.append("proc_add_bus_clock \"{}\" \"{}\" \"{}\"".format("axilite_clk", "axilite_in", "axilite_rst"))
        tcl.append("proc_declare_interrupt \"{}\"".format("irq"))
        
        #GUI customization
        tcl.append(build_gui())
        tcl.append("proc_set_version \"{}\"  \"{}\" \"{}\" \"{}\"".format("AXIConverter", version_number, "0", "axi_converter IP (Packaging Proof of Concept)"))
        
        tcl.append("ipx::create_xgui_files [ipx::current_core]")
        tcl.append("ipx::update_checksums [ipx::current_core]")
        tcl.append("ipx::check_integrity -quiet [ipx::current_core]")
        tcl.append("ipx::save_core [ipx::current_core]")
        tcl.append("proc_archive_ip \"{}\" \"{}\" \"{}\"".format("Enjoy-Digital", build_name, version_number))
        tcl.append("close_project")
        tcl.append("exit")
        tools.write_to_file(package + "/packager.tcl", "\n".join(tcl))

        # Run Vivado's tcl core packager script
        os.system("cd {} && vivado -mode batch -source packager.tcl".format(package))

    def generate_project(self, build_name):
        part = "xc7z010iclg225-1L"

        # Create project directory
        project = "project_{}".format(build_name)
        # Create package directory
        package = "package_{}".format(build_name)
        
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

    def generate_interface(self, build_name):
        project = "interfaces"
        shutil.rmtree(project, ignore_errors=True)
        os.makedirs(project)

        # Prepare Vivado's tcl interface build script
        tcl = []
        # Declare Procedures
        tcl.append(proc_define_interface)
        tcl.append(proc_define_interface_port)
        tcl.append("set if_name {}".format("wishbone"))
        # declare the interface name
        tcl.append("proc_define_interface $if_name")
        # declare the interface ports
        tcl.append("proc_define_interface_port {} {} {} ".format("wishbone_adr","30","input"))
        tcl.append("proc_define_interface_port {} {} {} ".format("wishbone_dat_w","16","input"))
        tcl.append("proc_define_interface_port {} {} {} ".format("wishbone_dat_r","16","output"))
        tcl.append("proc_define_interface_port {} {} {} ".format("wishbone_sel","2","input"))
        tcl.append("proc_define_interface_port {} {} {} ".format("wishbone_cyc","1","input"))
        tcl.append("proc_define_interface_port {} {} {} ".format("wishbone_stb","1","input"))
        tcl.append("proc_define_interface_port {} {} {} ".format("wishbone_ack","1","output"))
        tcl.append("proc_define_interface_port {} {} {} ".format("wishbone_we","1","input"))
        tcl.append("proc_define_interface_port {} {} {} ".format("wishbone_cti","3","input"))
        tcl.append("proc_define_interface_port {} {} {} ".format("wishbone_bte","2","input"))
        tcl.append("proc_define_interface_port {} {} {} ".format("wishbone_err","1","output"))
        
        tools.write_to_file(project + "/interfaces.tcl", "\n".join(tcl))

        # Run Vivado's tcl core packager script
        os.system("cd {} && vivado -mode batch -source interfaces.tcl".format(project))


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
    parser.add_argument("--interface",     action="store_true", help="Build Package custom interfaces")
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
    if args.interface:
        module.generate_interface(build_name)
    if args.package:
        module.generate_package(build_name)
    if args.project:
        module.generate_project(build_name)

if __name__ == "__main__":
    main()
