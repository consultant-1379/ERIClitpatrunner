import __builtin__
import os
import grp
import shutil
import errno
import copy
import fcntl

from litpats import default_files

from ConfigParser import SafeConfigParser

from collections import namedtuple


ALLOWED_FILES = ['/dev/null']


class MockFile(object):
    def __init__(self, contents=None):
        if contents:
            self.lines = contents.split("\n")
        else:
            self.lines = []
        self._closed = True
        self._name = ''
        self._mode = 'r'

    def __repr__(self):
        state = 'closed' if self._closed else 'open'
        return "<{0} {1} {2}, mode '{3}' at {4}".format(
                                                    state,
                                                    self.__class__.__name__,
                                                    self._name,
                                                    self._mode,
                                                    hex(id(self)))

    def __str__(self):
        pass

    def __unicode__(self):
        pass

    @property
    def name(self):
        return self._name

    @name.setter
    def name(self, value):
        raise TypeError('readonly attribute')

    @name.deleter
    def name(self):
        raise TypeError('readonly attribute')

    @property
    def mode(self):
        return self._mode

    @mode.setter
    def mode(self, value):
        raise TypeError('readonly attribute')

    @mode.deleter
    def mode(self):
        raise TypeError('readonly attribute')

    @property
    def closed(self):
        return self._closed

    def close(self):
        self._closed = True

    def dump(self):
        return "\n".join(self.lines)


class MockBuffer(object):
    arbitrary_fd = 333

    def __init__(self, mock_file):
        self.mock_file = mock_file
        self.line_pointer = 0
        self.offset_pointer = 0
        self.fileno = lambda: MockBuffer.arbitrary_fd

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        pass

    def __getattr__(self, attr):
        return getattr(self.mock_file, attr)

    @property
    def name(self):
        return self.mock_file.name

    @name.setter
    def name(self, value):
        raise TypeError('readonly attribute')

    @name.deleter
    def name(self):
        raise TypeError('readonly attribute')

    @property
    def mode(self):
        return self.mock_file.mode

    @mode.setter
    def mode(self, value):
        raise TypeError('readonly attribute')

    @mode.deleter
    def mode(self):
        raise TypeError('readonly attribute')

    def tell(self):
        return self.offset_pointer

    def seek(self, offset, whence=os.SEEK_SET):
        if os.SEEK_SET == whence:
            self.offset_pointer = offset
        elif os.SEEK_CUR == whence:
            self.offset_pointer += offset
        elif os.SEEK_END == whence:
            self.offset_pointer = len(self.mock_file.dump()) - offset

    def read(self, size=None):
        if size:
            fullfile = self.mock_file.dump()
            size = min(size, len(fullfile) - self.offset_pointer)
            segment = fullfile[self.offset_pointer:self.offset_pointer + size]
            self.offset_pointer += size
            return segment
        return "\n".join(self.mock_file.lines)

    def readline(self):
        if self.line_pointer < len(self.mock_file.lines):
            line = self.mock_file.lines[self.line_pointer]
            self.line_pointer += 1
            return "%s\n" % (line,)
        else:
            return ""

    def readlines(self):
        return self.mock_file.lines

    def write(self, data):
        lines = data.split('\n')
        if lines and lines[-1] == '':
            lines.pop()
        self.mock_file.lines.extend(lines)

    def __iter__(self):
        for line in list(self.mock_file.lines):
            yield line

    def flush(self):
        pass

    def truncate(self, size=None):
        self.mock_file.lines = self.mock_file.lines[:self.offset_pointer]


def patched_read(self, filenames):
    if isinstance(filenames, basestring):
        filenames = [filenames]
        read_ok = []
        for filename in filenames:
            if filename.endswith("litp_logging.conf"):
                self.logging_config = _logging_content()
                fp = MockFile(_logging_content())
                mb = MockBuffer(fp)
                self.readfp(mb, filename)
            else:
                try:
                    fp = open(filename)
                except IOError:
                    continue
                self._read(fp, filename)
                fp.close()
                read_ok.append(filename)
    return read_ok


class MockFilesystem(object):
    _instance = None

    def __init__(self):
        self._files = dict()
        self.active = False
        self.old_exists = None
        self.old_open = None
        self.old_listdir = None
        self.old_fsync = None
        self.old_rename = None
        self.old_fcntl_flock = None
        self.real_files_mock_removed = set()
        self.real_dirs_hidden = set()

    def mock_flock(self, fd, op):
        pass

    @classmethod
    def get_instance(cls):
        return cls._instance

    def mock_open(self, filename, mode="r", buffering=None):
        if filename in ALLOWED_FILES:
            return self.old_open(filename, mode, buffering or 0)
        if filename not in self._files and "r" in mode and self.old_open:
            if self.is_real_path_hidden(filename):
                raise IOError('No such file or directory: {0}'.
                              format(filename))
            return self.old_open(filename, mode, buffering or 0)
        elif "w" in mode:
            self._validate_mock_open(filename, mode, buffering)
            self._files[filename] = MockFile()
        if filename in self._files \
                and isinstance(self._files[filename], MockFile):
            self._files[filename]._name = filename
            self._files[filename]._mode = mode
            self._files[filename]._closed = False
        return MockBuffer(self._files[filename])

    def _validate_mock_open(self, filename, mode, buffering):
        if not isinstance(filename, basestring):
            raise TypeError("coercing to Unicode: "
                    "need string or buffer, %s found" %
                    type(filename))
        if len(filename.split('/')[-1]) > 255:
            raise IOError("File name too long: '%s'" %
                    filename.split('/')[-1])

    def _add_slash(self, dirpath):
        if not dirpath.endswith('/'):
            dirpath += '/'
        return dirpath

    def hide_real_directory(self, dirpath):
        self.real_dirs_hidden.add(self._add_slash(dirpath))

    def is_real_path_hidden(self, path):
        return any([path.startswith(d) for d in self.real_dirs_hidden])

    def mock_fsync(self, fileno):
        try:
            self.old_fsync(fileno)
        except OSError as e:
            if e.errno in (errno.EINVAL, errno.EBADF) and \
                    fileno == MockBuffer.arbitrary_fd:
                pass
            else:
                raise

    def mock_fchmod(self, fileno, mode):
        pass

    def mock_fchown(self, fileno, user, group):
        pass

    def mock_getgrnam(self, group):
        group_info = namedtuple("group_info",
                                "gr_name gr_passwd gr_gid gr_mem")

        return group_info(gr_name='bogus',
                            gr_passwd='secret',
                            gr_gid=99,
                            gr_mem=None)

    def mock_exists(self, path):
        if path in self.real_files_mock_removed:
            return False
        return path in self._paths() or (self.old_exists and
            self.old_exists(path) and not self.is_real_path_hidden(path))

    def mock_isdir(self, path):
        while path.endswith(os.path.sep):
            path = path[:-len(os.path.sep)]
        if not path:
            path = os.path.sep
        return path in (self._paths() - set(self._files.keys())) or (
            self.old_exists and
            self.old_exists(path) and not
            self.is_real_path_hidden(path))

    def mock_isfile(self, path):
        if path.endswith(os.path.sep):
            return False
        return path in (self._files.keys()) or (
            self.old_exists and
            self.old_exists(path) and not
            self.is_real_path_hidden(path))

    def mock_islink(self, path):
        return False

    def _paths(self):
        mocked_paths = set()

        def add_upstream_path(dirs, rightmost_dir):
            if not rightmost_dir:
                return ['']

            dirs.extend([rightmost_dir])
            mocked_paths.add(os.path.sep.join(dirs))
            return dirs

        for mocked_file in self._files.keys():
            path_tokens = mocked_file.split(os.path.sep)
            reduce(add_upstream_path, path_tokens, [])

        return mocked_paths

    def mock_remove(self, path):
        if path in self._files:
            if type(self._files[path]) == file:
                self._files[path].close()
            del self._files[path]
        elif path in self.real_files_mock_removed or \
                     self.is_real_path_hidden(path):
            raise OSError("No such file or directory: '{0}'".format(path))
        elif self.old_exists(path):
            self.real_files_mock_removed.add(path)
        else:
            raise OSError("No such file or directory: '{0}'".format(path))

    def mock_makedirs(self, path, mode=0777):
        pass

    def mock_rename(self, from_file, to_file):
        if from_file in self.real_files_mock_removed:
            raise OSError('No such file or directory: {0}'.format(from_file))
        if from_file not in self._files:
            if self.is_real_path_hidden(from_file):
                raise OSError('No such file or directory: {0}'.
                              format(from_file))
            try:
                self._files[to_file] = MockFile(
                        self.old_open(from_file).read())
            except:
                raise OSError
        else:
            newfile = MockFile()
            newfile.lines = list(self._files[from_file].lines)
            self._files[to_file] = newfile
            del self._files[from_file]

    def mock_copy_tree(self, from_dir, to_dir):
        old_files = copy.deepcopy(self._files)
        if not from_dir.endswith('/'):
            from_dir += '/'
        if not to_dir.endswith('/'):
            to_dir += '/'
        for path in old_files:
            if path.startswith(from_dir):
                copy_path = path.replace(from_dir, to_dir)
                self.mock_copy(path, copy_path)

    def mock_remove_tree(self, remove_dir):
        old_files = copy.deepcopy(self._files)
        if not remove_dir.endswith('/'):
            remove_dir += '/'
        for path in old_files:
            if path.startswith(remove_dir):
                self.mock_remove(path)

    def mock_copy(self, from_file, to_file):
        if from_file in self.real_files_mock_removed:
            raise IOError('No such file or directory: {0}'.format(from_file))
        if from_file not in self._files:
            if self.is_real_path_hidden(from_file):
                raise IOError('No such file or directory: {0}'.
                              format(from_file))
            self._files[to_file] = MockFile(self.old_open(from_file).read())
            self._files[to_file]._name = to_file
        else:
            newfile = MockFile()
            newfile._name = to_file
            newfile.lines = list(self._files[from_file].lines)
            self._files[to_file] = newfile

    def mock_listdir(self, dirpath):
        files = []
        for filepath in self._files:
            filename = filepath[len(dirpath):].lstrip('/')
            if filepath.startswith(dirpath) and '/' not in filename:
                files.append(filename)

        if not self.is_real_path_hidden(self._add_slash(dirpath)):
            try:
                listdir_files = self.old_listdir(dirpath)
                for fname in listdir_files:
                    fpath = os.path.join(dirpath, fname)
                    if not fpath in self.real_files_mock_removed:
                        files.append(fname)
            except OSError as e:
                if e.errno != errno.ENOENT:
                    raise

        return files

    def add_directory(self, link_dir, relative_dir, overlay=True):
        if not overlay:
            self.hide_real_directory(link_dir)
        relative_dir = os.path.abspath(relative_dir)
        for root, dirs, files in os.walk(relative_dir):
            root = root[len(relative_dir):].lstrip('/')
            for filename in files:
                contents = self._read_real_file(os.path.join(relative_dir,
                    root, filename))
                self._files[os.path.join(link_dir, root, filename)] = \
                    MockFile(contents)

    def _read_real_file(self, filepath):
        if self.old_open:
            return self.old_open(filepath).read()
        else:
            return open(filepath).read()

    def add_file(self, filepath, contents):
        if type(contents) == file:
            self._files[filepath] = contents
        else:
            self._files[filepath] = MockFile(contents)

    def hookup(self):
        if not self.active:
            self.old_open = __builtin__.open
            __builtin__.open = MockFilesystem._instance.mock_open
            self.old_exists = os.path.exists
            os.path.exists = MockFilesystem._instance.mock_exists
            self.old_isdir = os.path.isdir
            os.path.isdir = MockFilesystem._instance.mock_isdir
            self.old_isfile = os.path.isfile
            os.path.isfile = MockFilesystem._instance.mock_isfile
            self.old_islink = os.path.islink
            os.path.islink = MockFilesystem._instance.mock_islink
            self.old_fsync = os.fsync
            os.fsync = MockFilesystem._instance.mock_fsync
            self.old_fchmod = os.fchmod
            os.fchmod = MockFilesystem._instance.mock_fchmod
            self.old_fchown = os.fchown
            os.fchown = MockFilesystem._instance.mock_fchown
            self.old_getgrnam = grp.getgrnam
            grp.getgrnam = MockFilesystem._instance.mock_getgrnam
            self.old_rename = os.rename
            os.rename = MockFilesystem._instance.mock_rename
            self.old_listdir = os.listdir
            os.listdir = MockFilesystem._instance.mock_listdir
            self.old_remove = os.remove
            os.remove = MockFilesystem._instance.mock_remove
            self.old_makedirs = os.makedirs
            os.makedirs = MockFilesystem._instance.mock_makedirs
            self.old_mkdir = os.mkdir
            os.mkdir = MockFilesystem._instance.mock_makedirs
            self.shutil_copy = shutil.copy
            shutil.copy = MockFilesystem._instance.mock_copy
            self.shutil_copytree = shutil.copytree
            shutil.copytree = MockFilesystem._instance.mock_copy_tree
            self.shutil_rmtree = shutil.rmtree
            shutil.rmtree = MockFilesystem._instance.mock_remove_tree
            self.shutil_copyfile = shutil.copyfile
            shutil.copyfile = MockFilesystem._instance.mock_copy
            self.safeconfigparser_read = patched_read
            SafeConfigParser.read = patched_read
            self.old_fcntl_flock = fcntl.flock
            fcntl.flock = MockFilesystem._instance.mock_flock
        self.active = True

    def release(self):
        if self.active:
            __builtin__.open = self.old_open
            os.path.exists = self.old_exists
            os.path.isdir = self.old_isdir
            os.path.isfile = self.old_isfile
            os.path.islink = self.old_islink
            os.listdir = self.old_listdir
            os.remove = self.old_remove
            os.makedirs = self.old_makedirs
            os.mkdir = self.old_mkdir
            os.fsync = self.old_fsync
            os.fchmod = self.old_fchmod
            os.fchown = self.old_fchown
            grp.getgrnam = self.old_getgrnam
            os.rename = self.old_rename
            shutil.copy = self.shutil_copy
            shutil.copytree = self.shutil_copytree
            shutil.rmtree = self.shutil_rmtree
            shutil.copyfile = self.shutil_copyfile
            SafeConfigParser.read = self.safeconfigparser_read
            fcntl.flock = self.old_fcntl_flock
        self.active = False


def create(root_path):
    if MockFilesystem._instance:
        raise Exception("Cannot create mockfilesystem, already exists, "
            "release the old one first")
    MockFilesystem._instance = MockFilesystem()
    MockFilesystem._instance._files = default_files.create(root_path, MockFile)
    #MockFilesystem._instance.add_directory("/etc", "/etc")
    MockFilesystem._instance.add_directory(
        '/opt/ericsson/nms/litp/etc/plugins', "%s/etc/plugins" % root_path)
    MockFilesystem._instance.add_directory(
        '/opt/ericsson/nms/litp/etc/samples', "%s/etc/samples" % root_path)
    MockFilesystem._instance.add_directory(
        '/opt/ericsson/nms/litp/etc/extensions',
        "%s/etc/extensions" % root_path)
    MockFilesystem._instance.add_directory('/opt/ericsson/nms/litp/share',
        "%s/share" % root_path)
    MockFilesystem._instance.add_directory(
        '/opt/ericsson/nms/litp/bin/samples', "%s/bin/samples" % root_path)
    MockFilesystem._instance.add_file('/etc/litp_logging.conf',
                                      _logging_content())

    MockFilesystem._instance.add_file('/etc/sysconfig/clock',
                                      'Time zone: Europe/mock (MOCK, +001)\n')
    MockFilesystem._instance.add_file('/opt/ericsson/nms/litp/etc/.cobblerrc',
                                      '[cobbler]\ncobbler=mock_password')
    MockFilesystem._instance.add_file(
        '/var/www/html/ms/path/to/yum3/repodata/repomd.xml', 'data')
    MockFilesystem._instance.add_file(
        '/var/www/html/ms/path/to/yum4/repodata/repomd.xml', 'data')
    MockFilesystem._instance.add_file(
        '/var/www/html/ms/path/to/yum5/repodata/repomd.xml', 'data')
    MockFilesystem._instance.add_file(
        '/opt/ericsson/nms/litp/etc/puppet/litp_config_version', '0')
    return MockFilesystem._instance


def destroy():
    mfs = MockFilesystem._instance
    for path in mfs._files:
        if type(mfs._files[path]) == file:
            mfs._files[path].close()
        elif isinstance(mfs._files[path], MockFile):
            mfs._files[path].close()
    MockFilesystem._instance = None


def _logging_content():
    return """
[loggers]
keys=root,litproot

[handlers]
keys=litpSyslogHandler

[formatters]
keys=simpleFormatter,syslogFormatter

[logger_litproot]
level=INFO
handlers=litpSyslogHandler
qualname=litp

[logger_root]
level=CRITICAL
handlers=

[logger_litptrace]
level=INFO
handlers=litpSyslogHandler
qualname=litp.trace

[handler_litpSyslogHandler]
class=litp.service.syslog_handler.LITPSyslogHandler
level=DEBUG
formatter=syslogFormatter
args=(('/dev/log'), handlers.SysLogHandler.LOG_USER)

[formatter_simpleFormatter]
format=%(asctime)s - %(name)s - %(levelname)s - %(message)s
datefmt=

[formatter_syslogFormatter]
#format=litp.nms.ericsson.com: %(name)s: %(process)s: %(message)s
format=%(name)s[%(process)s]: %(levelname)s: %(message)s
datefmt=
"""
