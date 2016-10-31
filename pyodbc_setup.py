#!/usr/bin/python

import sys, os, re, platform
from os.path import exists, abspath, dirname, join, isdir

import numpy

try:
    # Allow use of setuptools so eggs can be built.
    from numpy.distutils.core import setup, Command
except ImportError:
    from distutils.core import setup, Command

from distutils.extension import Extension
from distutils.errors import *

OFFICIAL_BUILD = 9999

NPVERSION_STR = "1.2-dev"

def _print(s):
    # Python 2/3 compatibility
    sys.stdout.write(s + '\n')

class VersionCommand(Command):

    description = "prints the pyodbc version, determined from git"

    user_options = []

    def initialize_options(self):
        self.verbose = 0

    def finalize_options(self):
        pass

    def run(self):
        version_str, version = get_version()
        sys.stdout.write(version_str + '\n')


class TagsCommand(Command):

    description = 'runs etags'

    user_options = []

    def initialize_options(self):
        pass

    def finalize_options(self):
        pass

    def run(self):
        # Windows versions of etag do not seem to expand wildcards (which Unix shells normally do for Unix utilities),
        # so find all of the files ourselves.
        files = [ join('src', f) for f in os.listdir('src') if f.endswith(('.h', '.cpp')) ]
        cmd = 'etags %s' % ' '.join(files)
        return os.system(cmd)


def get_module_extension(modname):
    version_str, version = get_version()

    src_path = join(dirname(__file__), 'pyodbc/src')

    settings = get_compiler_settings(version_str)

    files = [ abspath(join(src_path, f)) for f in os.listdir(src_path) if f.endswith('.cpp') ]

    return Extension(modname, files, **settings)

def get_compiler_settings(version_str):

    settings = { 'libraries': [],
                 'include_dirs': [numpy.get_include()],
                 'define_macros' : [ ('PYODBC_VERSION', version_str),
                                     ('NPODBC_VERSION', NPVERSION_STR)] }

    if 'C_INCLUDE_PATH' in os.environ:
        settings['include_dirs'].extend(os.environ['C_INCLUDE_PATH'].split(os.pathsep))

    # This isn't the best or right way to do this, but I don't see how someone is supposed to sanely subclass the build
    # command.
    for option in ['assert', 'trace', 'leak-check']:
        try:
            sys.argv.remove('--%s' % option)
            settings['define_macros'].append(('PYODBC_%s' % option.replace('-', '_').upper(), 1))
        except ValueError:
            pass

    if os.name == 'nt':
        settings['extra_compile_args'] = ['/Wall',
                                          '/wd4668',
                                          '/wd4820',
                                          '/wd4711', # function selected for automatic inline expansion
                                          '/wd4100', # unreferenced formal parameter
                                          '/wd4127', # "conditional expression is constant" testing compilation constants
                                          '/wd4191', # casts to PYCFunction which doesn't have the keywords parameter
                                          ]
        settings['libraries'].append('odbc32')
        settings['libraries'].append('advapi32')

        if '--debug' in sys.argv:
            sys.argv.remove('--debug')
            settings['extra_compile_args'].extend('/Od /Ge /GS /GZ /RTC1 /Wp64 /Yd'.split())

    elif os.environ.get("OS", '').lower().startswith('windows'):
        # Windows Cygwin (posix on windows)
        # OS name not windows, but still on Windows
        settings['libraries'].append('odbc32')

    elif sys.platform == 'darwin':
        # OS/X no longer ships with iODBC.
#        settings['libraries'].append('iodbc')
        settings['extra_compile_args'] = ['-Wno-write-strings',
                                          '-I%s/include' % sys.prefix]

        # What is the proper way to detect iODBC, MyODBC, unixODBC, etc.?
        settings['libraries'].append('odbc')

    else:
        # Other posix-like: Linux, Solaris, etc.

        # Python functions take a lot of 'char *' that really should be const.  gcc complains about this *a lot*
        settings['extra_compile_args'] = ['-Wno-write-strings',
                                          '-I%s/include' % sys.prefix]

        # What is the proper way to detect iODBC, MyODBC, unixODBC, etc.?
        settings['libraries'].append('odbc')

    return settings


def add_to_path():
    """
    Prepends the build directory to the path so pyodbcconf can be imported without installing it.
    """
    # Now run the utility

    import imp
    library_exts  = [ t[0] for t in imp.get_suffixes() if t[-1] == imp.C_EXTENSION ]
    library_names = [ 'pyodbcconf%s' % ext for ext in library_exts ]

    # Only go into directories that match our version number. 

    dir_suffix = '-%s.%s' % (sys.version_info[0], sys.version_info[1])

    build = join(dirname(abspath(__file__)), 'build')

    for top, dirs, files in os.walk(build):
        dirs = [ d for d in dirs if d.endswith(dir_suffix) ]
        for name in library_names:
            if name in files:
                sys.path.insert(0, top)
                return

    raise SystemExit('Did not find pyodbcconf')


def get_version():
    """
    Returns the version of the product as (description, [major,minor,micro,beta]).

    If the release is official, `beta` will be 9999 (OFFICIAL_BUILD).

      1. If in a git repository, use the latest tag (git describe).
      2. If in an unzipped source directory (from setup.py sdist),
         read the version from the PKG-INFO file.
      3. Use 3.0.0.0 and complain a lot.
    """
    # My goal is to (1) provide accurate tags for official releases but (2) not have to manage tags for every test
    # release.
    #
    # Official versions are tagged using 3 numbers: major, minor, micro.  A build of a tagged version should produce
    # the version using just these pieces, such as 2.1.4.
    #
    # Unofficial versions are "working towards" the next version.  So the next unofficial build after 2.1.4 would be a
    # beta for 2.1.5.  Using 'git describe' we can find out how many changes have been made after 2.1.4 and we'll use
    # this count as the beta id (beta1, beta2, etc.)
    #
    # Since the 4 numbers are put into the Windows DLL, we want to make sure the beta versions sort *before* the
    # official, so we set the official build number to 9999, but we don't show it.

    name    = None              # branch/feature name.  Should be None for official builds.
    numbers = None              # The 4 integers that make up the version.

    # If this is a source release the version will have already been assigned and be in the PKG-INFO file.

    name, numbers = _get_version_pkginfo()

    # If not a source release, we should be in a git repository.  Look for the latest tag.

    if not numbers:
        name, numbers = _get_version_git()

    if not numbers:
        #_print('WARNING: Unable to determine version.  Using 3.0.0.0')
        name, numbers = '3.0.0-unsupported', [3,0,0,0]

    return name, numbers


def _get_version_pkginfo():
    filename = join(dirname(abspath(__file__)), 'PKG-INFO')
    if exists(filename):
        re_ver = re.compile(r'^Version: \s+ (\d+)\.(\d+)\.(\d+) (?: -beta(\d+))?', re.VERBOSE)
        for line in open(filename):
            match = re_ver.search(line)
            if match:
                name    = line.split(':', 1)[1].strip()
                numbers = [int(n or 0) for n in match.groups()[:3]]
                numbers.append(int(match.group(4) or OFFICIAL_BUILD)) # don't use 0 as a default for build
                return name, numbers

    return None, None


def _get_version_git():
    n, result = getoutput('git describe --tag')
    if n:
        #_print('WARNING: git describe failed with: %s %s' % (n, result))
        return None, None

    match = re.match(r'(\d+).(\d+).(\d+) (?: -(\d+)-g([0-9a-z]+))?', result, re.VERBOSE)
    if not match:
        return None, None

    groups = match.groups()
    numbers = [int(x or OFFICIAL_BUILD) for x in groups[:4]]

    if numbers[-1] == OFFICIAL_BUILD:
        name = '%s.%s.%s-[IOPro]' % tuple(groups[:3])
    else:
        # This is a beta of the next micro release, so increment the micro number to reflect this.
        numbers[-2] += 1
        name = '%s.%s.%s-beta%02d-[IOPRO]' % tuple(numbers)
        name+= '-[%s]' % groups[-1]

    n, branch_name = getoutput('git symbolic-ref --short HEAD')
    if n and branch_name != 'master':
        name = branch_name + '-' + name

    return name, numbers



def getoutput(cmd):
    pipe = os.popen(cmd, 'r')
    text   = pipe.read().rstrip('\n')
    status = pipe.close() or 0
    return status, text