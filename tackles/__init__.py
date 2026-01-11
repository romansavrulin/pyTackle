import importlib
import pathlib
import re
import sys
import pkgutil

__all__ = []

def import_submodules(package_name):
    """ Import all submodules of a module, recursively

    :param package_name: Package name
    :type package_name: str
    :rtype: dict[types.ModuleType]
    """
    package = sys.modules[package_name]
    for loader, name, is_pkg in pkgutil.walk_packages(package.__path__):
        print(package_name + '.' + name)
    return {
        name: importlib.import_module(package_name + '.' + name)
        for loader, name, is_pkg in pkgutil.walk_packages(package.__path__)
    }


# from tackles.TestTackle import TestTackle
# from tackles.TackleFactory import TackleFactory
# from tackles.CopyValidateMD5 import CopyValidateMD5

path = pathlib.Path(__file__).parent.absolute()
names = [x.name[:-3] for x in path.iterdir() if x.is_file() and re.search("^[a-z,A-Z,0-9]*\.py$", x.name)]
for name in names:
    importlib.import_module(f".{name}", __name__)
    exec(f"from {__name__}.{name} import {name}")
    __all__.append(name)

del importlib, pathlib, re, sys, pkgutil

#__all__ = list(import_submodules(__name__).keys())

#print(__all__)