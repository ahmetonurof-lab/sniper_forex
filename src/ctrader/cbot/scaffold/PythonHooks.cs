// ---------------------------------------------------------------
// Spotware standard bridge — identical across all Python algo samples.
// Source: spotware/ctrader-python-algo-samples (MIT-licensed).
// DO NOT EDIT — regenerate from Spotware samples if upgrading.
// ---------------------------------------------------------------

using System;
using Python.Runtime;

namespace cAlgo.Robots;

internal static class PythonHooks
{
    internal const string DummyTraceback = @"
class TracebackType:
    def __init__(self, *args, **kwargs):
        pass

def format_exception(exc_type, exc_value, exc_tb):
    return [str(exc_value)]

def format_exception_only(exc_type, exc_value):
    return [str(exc_value)]
";

    internal const string InMemoryModuleLoaderPythonCode = @"
import importlib.abc
import importlib.machinery
import sys

class InMemoryModuleFinder(importlib.abc.MetaPathFinder):
    def __init__(self, module_map):
        self._module_map = module_map

    def find_spec(self, fullname, path=None, target=None):
        if fullname in self._module_map:
            return importlib.machinery.ModuleSpec(
                fullname,
                InMemoryModuleLoader(self._module_map),
                origin=fullname + '.py',
            )
        return None

class InMemoryModuleLoader(importlib.abc.Loader):
    def __init__(self, module_map):
        self._module_map = module_map

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        fullname = module.__name__
        if fullname not in self._module_map:
            raise ImportError(fullname)
        code = self._module_map[fullname]
        module.__file__ = fullname + '.py'
        module.__loader__ = self
        exec(compile(code, fullname + '.py', 'exec'), module.__dict__)

def install_inmemory_importer(module_map, is_clear_cache):
    finder = InMemoryModuleFinder(module_map)
    sys.meta_path.insert(0, finder)
    if is_clear_cache:
        importlib.invalidate_caches()
    return finder
";
}
