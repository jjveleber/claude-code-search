import sys
import os

# The project root eval/ package must take priority over tests/eval/
# because pytest imports test_report.py as eval.test_report (due to __init__.py),
# which causes 'eval' to resolve to tests/eval/ instead of the root eval/ package.
# We fix this by explicitly injecting the real eval package into sys.modules.

project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Force-reload eval to point to the project root eval/ package
import importlib
import importlib.util

eval_init = os.path.join(project_root, "eval", "__init__.py")
spec = importlib.util.spec_from_file_location("eval", eval_init,
    submodule_search_locations=[os.path.join(project_root, "eval")])
real_eval = importlib.util.module_from_spec(spec)
sys.modules["eval"] = real_eval
spec.loader.exec_module(real_eval)
