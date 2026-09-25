"""Expose existing per-product fill counters; no engine dynamics are changed."""
from pathlib import Path
import argparse,sysconfig,subprocess
ap=argparse.ArgumentParser();ap.add_argument('--engine-dir',required=True);ap.add_argument('--headers',required=True);a=ap.parse_args();e=Path(a.engine_dir);s=(e/'python/kagsim.cpp').read_text();anchor='        t["sold_units"] = sold;';assert s.count(anchor)==1
s=s.replace(anchor,anchor+'\n        py::dict product_sold;\n        for (const auto& entry : ITI) product_sold[py::str(entry.first)] = f.sold_units[entry.second];\n        t["sold_by_product"] = product_sold;').replace('PYBIND11_MODULE(kagsim, m)','PYBIND11_MODULE(kagsim_ledger, m)')
p=e/'python/kagsim_ledger.cpp';p.write_text(s)
subprocess.run(['g++','-O2','-shared','-std=c++17','-fPIC','-I'+sysconfig.get_path('include'),'-I'+a.headers,str(p),'-o',str(e/('kagsim_ledger'+sysconfig.get_config_var('EXT_SUFFIX')))],check=True)
