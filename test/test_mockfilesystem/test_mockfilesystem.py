import unittest
import os
import shutil
import __builtin__
import tempfile

from contextlib import contextmanager
from ConfigParser import SafeConfigParser

from litpats import mockfilesystem
from litpats import default_files
from litpats.mockfilesystem import MockFile
from litpats.mockfilesystem import MockBuffer
from litpats.mockfilesystem import MockFilesystem


class TestMockFilesystemCreateDestroy(unittest.TestCase):
    def setUp(self):
        self.root_path = '/opt/ericsson/nms/litp'

    def tearDown(self):
        # Try to release and destroy even if mockfilesystem has never been
        # instantiated. Just in case, to not to interfere with other tests.
        try:
            MockFilesystem._instance.release()
        except AttributeError:
            pass

        try:
            mockfilesystem.destroy()
        except AttributeError:
            pass

    def test_cannot_create_mockfilesystem_twice(self):
        mockfilesystem.create(self.root_path)
        self.assertRaises(Exception, mockfilesystem.create, self.root_path)

    def test_create(self):
        fs = mockfilesystem.create(self.root_path)
        self.assertTrue(isinstance(fs, MockFilesystem))
        self.assertTrue(fs is MockFilesystem._instance )

        # Test if mock files are there
        mock_files = ['/etc/sysconfig/clock', '/etc/litp_logging.conf']
        for f in mock_files:
            self._assert_mock_file_in_mockfilesystem(fs, f)

        for f in default_files.default_file_list:
            self._assert_mock_file_in_mockfilesystem(fs,
                    self.root_path + os.path.sep + f)

        # Test some created file contents
        with fs.mock_open('/etc/sysconfig/clock') as f:
            self.assertEquals(f.readlines(), ['Time zone: Europe/mock (MOCK, +001)', ''])

    def test_destroy(self):
        self.assertTrue(MockFilesystem._instance is None)
        mockfilesystem.create(self.root_path)
        self.assertTrue(isinstance(MockFilesystem._instance, MockFilesystem))
        files = MockFilesystem._instance._files.copy()
        mockfilesystem.destroy()
        self.assertTrue(MockFilesystem._instance is None)
        for path in files:
            self.assertTrue(files[path].closed)

    def test_hookup_release(self, test_idempotency=False):
        fs = mockfilesystem.create(self.root_path)
        self.assertTrue(isinstance(fs._instance, MockFilesystem))
        self.assertTrue(isinstance(MockFilesystem._instance, MockFilesystem))

        builtin_open = __builtin__.open
        os_path_exists = os.path.exists
        os_path_isdir = os.path.isdir
        os_fsync = os.fsync
        os_rename = os.rename
        os_listdir = os.listdir
        os_remove = os.remove
        os_makedirs = os.makedirs
        os_mkdir = os.mkdir
        shutil_copy = shutil.copy
        shutil_copyfile = shutil.copyfile

        self.assertTrue(builtin_open == __builtin__.open)
        self.assertTrue(os_path_exists == os.path.exists)
        self.assertTrue(os_path_isdir == os.path.isdir)
        self.assertTrue(os_fsync == os.fsync)
        self.assertTrue(os_rename == os.rename)
        self.assertTrue(os_listdir == os.listdir)
        self.assertTrue(os_remove == os.remove)
        self.assertTrue(os_makedirs == os.makedirs)
        self.assertTrue(os_mkdir == os.mkdir)
        self.assertTrue(shutil_copy == shutil.copy)
        self.assertTrue(shutil_copyfile == shutil.copyfile)

        fs.hookup()
        if test_idempotency:
            fs.hookup()

        self._assertFunctionMock(__builtin__.open, fs.mock_open, builtin_open)
        self._assertFunctionMock(os.path.isdir, fs.mock_isdir, os_path_isdir)
        self._assertFunctionMock(os.fsync, fs.mock_fsync, os_fsync)
        self._assertFunctionMock(os.rename, fs.mock_rename, os_rename)
        self._assertFunctionMock(os.listdir, fs.mock_listdir, os_listdir)
        self._assertFunctionMock(os.remove, fs.mock_remove, os_remove)
        self._assertFunctionMock(os.makedirs, fs.mock_makedirs, os_makedirs)
        self._assertFunctionMock(os.mkdir, fs.mock_makedirs, os_mkdir)
        self._assertFunctionMock(shutil.copy, fs.mock_copy, shutil_copy)
        self._assertFunctionMock(shutil.copyfile, fs.mock_copy, shutil_copyfile)

        self.assertTrue(fs.active)

        fs.release()
        if test_idempotency:
            fs.release()

        self.assertTrue(builtin_open == __builtin__.open)
        self.assertTrue(os_path_exists == os.path.exists)
        self.assertTrue(os_path_isdir == os.path.isdir)
        self.assertTrue(os_fsync == os.fsync)
        self.assertTrue(os_rename == os.rename)
        self.assertTrue(os_listdir == os.listdir)
        self.assertTrue(os_remove == os.remove)
        self.assertTrue(os_makedirs == os.makedirs)
        self.assertTrue(os_mkdir == os.mkdir)
        self.assertTrue(shutil_copy == shutil.copy)
        self.assertTrue(shutil_copyfile == shutil.copyfile)

        self.assertFalse(fs.active)

    def test_hookup_release_idempotent(self):
        self.test_hookup_release(test_idempotency=True)

    def _assert_real_file_in_mockfilesystem(self, fs, path):
        self.assertTrue(path in fs._files)
        with open(path) as f:
            self.assertTrue(
                    os.path.sameopenfile(f.fileno(), fs._files[path].fileno()))

    def _assert_mock_file_in_mockfilesystem(self, fs, path):
        self.assertTrue(path in fs._files)

    def _assertFunctionMock(self, original, mocked, saved):
        self.assertTrue(original == mocked and original != saved)


class TestMockFilesystem(unittest.TestCase):
    def setUp(self):
        root_path = '/opt/ericsson/nms/litp'
        # root_path = os.path.dirname(__file__)
        self.fs = mockfilesystem.create(root_path)
        self.fs.hookup()
        # mock_file = MockFile()
        # mock_file.lines = ['line1', 'line2']
        # self.fs._files['/file1.txt'] = mock_file

    def tearDown(self):
        MockFilesystem._instance.release()
        mockfilesystem.destroy()
        del self.fs

    @contextmanager
    def real_dirs_created(self, *dirpaths):
        if not dirpaths:
            raise Exception('"dirpaths" argument not specified')
        try:
            for dirpath in dirpaths:
                try:
                    self.fs.old_mkdir(dirpath)
                except OSError as e:
                    raise
            yield
        finally:
            for dirpath in dirpaths:
                try:
                    self.fs.shutil_rmtree(dirpath)
                except:
                    pass

    @contextmanager
    def real_temp_file_created(self, dirpath):
        if not dirpath:
            raise Exception('"dirpath" argument not specified')
        try:
            fd, fname = tempfile.mkstemp(dir=dirpath)
            yield fname
        finally:
            os.close(fd)
            os.unlink(fname)

    def test_mock_open(self):
        try:
            tmpfd, fname = tempfile.mkstemp()

            # Open real file in 'r' mode
            fd = open(fname, 'r')
            self.assertEquals(fd.name, fname)
            self.assertEquals(fd.mode, 'r')
            self.assertEquals(fd.closed, False)
            self.assertTrue(fname not in self.fs._files)
            self.assertTrue(isinstance(fd, file))
            self.assertRaises(TypeError,
                    lambda fd: setattr(fd, 'name', 'new_name'), fd)
            fd.close()

            # Open real file in 'w' mode
            fd = open(fname, 'w')
            self.assertEquals(fd.name, fname)
            self.assertEquals(fd.mode, 'w')
            self.assertEquals(fd.closed, False)
            self.assertTrue(fname in self.fs._files)
            self.assertTrue(isinstance(fd, MockBuffer))
            self.assertRaises(TypeError,
                    lambda fd: setattr(fd, 'name', 'new_name'), fd)
            fd.close()

            # Open MockFile in 'r' mode
            mock_fname = '/etc/litp_logging.conf'
            fd = open(mock_fname, 'r')
            self.assertEquals(fd.name, mock_fname)
            self.assertEquals(fd.mode, 'r')
            self.assertEquals(fd.closed, False)
            self.assertTrue(mock_fname in self.fs._files)
            self.assertTrue(isinstance(fd, MockBuffer))
            self.assertRaises(TypeError,
                    lambda fd: setattr(fd, 'name', 'new_name'), fd)
            fd.close()

        finally:
            os.close(tmpfd)
            os.unlink(fname)

        self.assertRaises(IOError, open, 'x' * 256, 'r')
        self.assertRaises(IOError, open, 'x' * 256, 'w')
        self.assertRaises(TypeError, open, 1, 'r')
        self.assertRaises(TypeError, open, -1, 'r')
        self.assertRaises(TypeError, open, 1, 'w')
        self.assertRaises(TypeError, open, -1, 'w')

    def test_mock_open_hidden_real_files(self):
        dirpath = '/tmp/_my_test_of_mock_listdir_functinality'
        empty_dirpath = '/tmp/_my_test_of_mock_listdir_functinality_empty'
        with self.real_dirs_created(dirpath, empty_dirpath):
            with self.real_temp_file_created(dirpath) as real_tmp_filename:
                # This should hide real files (overlay=False).
                self.fs.add_directory(dirpath, empty_dirpath, overlay=False)

                try:
                    fd = open(real_tmp_filename, 'r')
                except IOError as e:
                    pass
                else:
                    self.fail("Should have raised an IOError")
                finally:
                    try:
                        fd.close()
                    except:
                        pass

    # def test_file_load(self):
        # self.assertEquals("line1\nline2",
            # self.fs.mock_open('/file1.txt').read())

    # def test_file_save(self):
        # new_file = self.fs.mock_open("/file2.txt", "w")
        # self.assertEquals([], self.fs._files['/file2.txt'].lines)
        # new_file.write("hello")
        # self.assertEquals(['hello'],
            # self.fs._files['/file2.txt'].lines)
        # new_file.write("there\nmoi\nlovely")
        # self.assertEquals(['hello', 'there', 'moi', 'lovely'],
            # self.fs._files['/file2.txt'].lines)

    # def test_add_directory(self):
        # rel_path = os.path.join(os.path.dirname(__file__), "test_dir")
        # self.fs.add_directory("/newdir", rel_path)
        # self.assertEquals("test file 1\n",
            # self.fs.mock_open("/newdir/test_file1.txt").read())
        # self.assertEquals("test file 2\n",
            # self.fs.mock_open("/newdir/test_file2.txt").read())
        # self.assertEquals("test file 3\n",
            # self.fs.mock_open("/newdir/test_subdir/test_file3.txt"
            # ).read())

    def test_mock_fsync(self):
        pass

    def test_mock_exists(self):
        # Test real file
        self.assertTrue(os.path.exists('/dev/zero'))

        # Test mock file
        self.assertTrue(os.path.exists('/etc/sysconfig/clock'))

        # Test directory
        self.assertTrue(os.path.exists('/etc'))

        # Test nonexising file/dir
        self.assertFalse(os.path.exists('/nonexistent'))

        # Test '' file name
        self.assertFalse(os.path.exists(''))

        # Test mock directory
        self.assertTrue(os.path.exists(
            '/opt/ericsson/nms/litp/etc/puppet/modules/cmw'))

    def test_mock_isdir(self):
        pass

    def test_mock_remove(self):
        # TODO: Recreate a mock file with same name as previously removed real file
        self.assertRaises(OSError, os.remove,
                '/paththatdoesntexist/imeanreally/itdoesntexist')
        # Test remove Mock file
        f = open('remove_this', 'w')
        f.close()
        self.assertTrue(f.name in self.fs._files)
        self.assertTrue(os.path.exists(f.name))
        self.assertTrue(os.path.basename(f.name) in os.listdir(os.path.dirname(f.name)))
        os.remove(f.name)
        # Check is it there with other mocked cmds
        self.assertFalse(f.name in self.fs._files)
        self.assertFalse(os.path.exists(f.name))
        self.assertRaises(OSError, os.remove, f.name)
        self.assertRaises(IOError, shutil.copy, f.name, 'do_not_copy')
        self.assertRaises(OSError, os.rename, f.name, 'do_not_rename')
        self.assertFalse(os.path.basename(f.name) in os.listdir(os.path.dirname(f.name)))
        # Test remove real file (e.g. an existing file (don't use old_open!))
        try:
            tmpfd, fname = tempfile.mkstemp()
            self.assertFalse(f.name in self.fs._files)
            self.assertTrue(os.path.exists(fname))
            self.assertTrue(os.path.basename(fname) in os.listdir(os.path.dirname(fname)))
            os.remove(fname)
            # Check is it there with other mocked cmds
            self.assertFalse(os.path.basename(fname) in os.listdir(os.path.dirname(fname)))
            self.assertFalse(os.path.exists(fname))
            self.assertRaises(OSError, os.remove, fname)
            self.assertRaises(IOError, shutil.copy, fname, 'do_not_copy')
            self.assertRaises(OSError, os.rename, fname, 'do_not_rename')
        finally:
            os.close(tmpfd)
            os.unlink(fname)

    def test_mock_makedirs(self):
        pass

    def test_mock_write(self):
        f = open('some_file', 'w')
        f.write('a\nb\nc\n')
        self.assertEquals(['a', 'b', 'c'], f.lines)
        f.close()

        f = open('some_file', 'w')
        f.write('one liner\n')
        self.assertEquals(['one liner'], f.lines)
        f.close()

        f = open('some_file', 'w')
        f.write('one liner no newline')
        self.assertEquals(['one liner no newline'], f.lines)
        f.close()

        f = open('some_file', 'w')
        f.write('')
        self.assertEquals([], f.lines)
        f.close()

    def test_mock_rename(self):
        self.assertRaises(OSError, os.rename,
                '/paththatdoesntexist/imeanreally/itdoesntexist', 'nowhere')
        # Test rename mock file
        f = open('rename_this', 'w')
        f.write('Hello World!')
        f.close()
        old_contents = open(f.name, 'r').read()
        f.close()
        old_name = f.name

        os.rename(f.name, 'renamed')
        self.assertTrue('renamed' in self.fs._files)
        self.assertTrue(old_name not in self.fs._files)

        renamed_f = open('renamed', 'r')
        renamed_contents = renamed_f.read()
        renamed_f.close()

        self.assertEquals(renamed_f.name, 'renamed')
        self.assertEquals(old_contents, renamed_contents)

        # Test renaming file to an existing path
        f2 = open('rename_again', 'w')
        f2.write('abc')
        f2.close()
        f2_contents = open(f2.name, 'r').read()
        f2.close()
        f2_old_name = f2.name

        os.rename(f2.name, 'renamed')

        renamed_again_f = open('renamed', 'r')
        renamed_again_contents = renamed_again_f.read()
        renamed_again_f.close()

        self.assertTrue('renamed' in self.fs._files)
        self.assertTrue(f2_old_name not in self.fs._files)
        self.assertEquals(renamed_again_f.name, 'renamed')
        self.assertEquals(f2_contents, renamed_again_contents)

        # Test rename with real file
        try:
            tmpfd, fname = tempfile.mkstemp()
            real_f = self.fs.old_open(fname, 'w')
            real_f.write(" ' 2-1- kdja     \n")
            real_f.write(" \n  j ... *&  #i'")
            real_f.close()
            real_contents = open(real_f.name, 'r').read()
            real_f.close()

            os.rename(real_f.name, 'renamed_real_f')

            renamed_real_f = open('renamed_real_f', 'r')
            renamed_real_contents = renamed_real_f.read()
            renamed_real_f.close()
            self.assertEquals('renamed_real_f', renamed_real_f.name)
            self.assertEquals(real_contents, renamed_real_contents)
            self.assertTrue('renamed_real_f' in self.fs._files)
            self.assertTrue(real_f.name not in self.fs._files)
        finally:
            os.close(tmpfd)
            os.unlink(fname)

    def test_mock_copy(self):
        self.assertRaises(IOError, shutil.copy,
                '/paththatdoesntexist/imeanreally/itdoesntexist', 'nowhere')
        # Test copy mock file
        f = open('copy_this', 'w')
        f.write('Hello world!')
        f.write('\n ****** #### 1234., ^"')
        f_contents = f.read()
        f.close
        shutil.copy('copy_this', 'test_copied')

        self.assertTrue('copy_this' in self.fs._files)
        self.assertTrue('test_copied' in self.fs._files)

        copied_f = open('test_copied', 'r')
        copied_contents = copied_f.read()
        copied_f.close()
        self.assertEquals(f_contents, copied_contents)
        self.assertEquals(copied_f.name, 'test_copied')
        self.assertTrue(isinstance(copied_f, MockBuffer))

        # Test copy real file (opened and written outside MockFilesystem)
        try:
            tmpfd, fname = tempfile.mkstemp()
            real_f = self.fs.old_open(fname, 'w')
            real_f.write('abc')
            real_f.close()
            real_contents = open(fname, 'r').read()
            real_f.close()

            shutil.copy(fname, 'test_copied2')
            temp_f = open('test_copied2', 'r')
            temp_contents = temp_f.read()
            temp_f.close()

            self.assertEquals(temp_contents, real_contents)
            self.assertEquals(temp_f.name, 'test_copied2')
            self.assertFalse(fname in self.fs._files)
            self.assertTrue('test_copied2' in self.fs._files)
        finally:
            os.close(tmpfd)
            os.unlink(fname)

    def test_listdir(self):
        self.fs.add_file("/dir1/file1.txt", "txt")
        self.fs.add_file("/dir1/file2.txt", "txt")
        self.fs.add_file("/dir1/subdir1/file3.txt", "txt")
        self.fs.add_file("/dir2/file4.txt", "txt")
        self.fs.add_file("/dir2/file5.txt", "txt")
        self.assertEquals(set(['file1.txt', 'file2.txt']),
            set(self.fs.mock_listdir('/dir1')))
        self.assertEquals(set(['file1.txt', 'file2.txt']),
            set(self.fs.mock_listdir('/dir1/')))

        # Test if mock files are listed along with real files
        try:
            dirpath = '/tmp/_my_test_of_mock_listdir_functinality'
            try:
                self.fs.old_mkdir(dirpath)
            except:
                pass
            rfd, rfn = tempfile.mkstemp(dir=dirpath)
            self.assertTrue(rfn not in self.fs._files)

            mf = self.fs.mock_open(
                    dirpath + os.path.sep + 'mock_file.txt', 'w')
            self.assertTrue(mf.name in self.fs._files)

            self.assertEquals(
                set(self.fs.mock_listdir(dirpath)),
                set([os.path.basename(rfn), 'mock_file.txt']))
        finally:
            os.close(rfd)
            os.unlink(rfn)
            self.fs.shutil_rmtree(dirpath)

    def test_listdir_with_real_path_hidden(self):
        # Test if real files are filtered out from the listing.
        dirpath = '/tmp/_my_test_of_mock_listdir_functinality'
        empty_dirpath = '/tmp/_my_test_of_mock_listdir_functinality_empty'
        with self.real_dirs_created(dirpath, empty_dirpath):
            with self.real_temp_file_created(dirpath) as real_tmp_file:
                # This should hide real files (overlay=False).
                self.fs.add_directory(dirpath, empty_dirpath, overlay=False)
                self.assertTrue(real_tmp_file not in self.fs._files)
                mf = self.fs.mock_open(
                        dirpath + os.path.sep + 'mock_file.txt', 'w')
                self.assertTrue(mf.name in self.fs._files)

                # Real file mustn't be listed.
                self.assertEquals(
                    set(self.fs.mock_listdir(dirpath)),
                    set(['mock_file.txt']))

    def test_add_directory(self):
        pass

    def test_add_file(self):
        pass

    def test_mock_copy_and_remove_tree(self):
        # Test mock_copy_tree copies the correct paths
        os.mkdir('/copytree_dir')
        f = open('/copytree_dir/yes_file1.txt', 'w')
        f.write('Hi')
        f.close()
        shutil.copy(f.name, '/copytree_dir/yes_file2.txt')
        os.mkdir('/copytree_dir_not_included/')
        f3 = open('/copytree_dir_not_included/no_file3.txt', 'w')
        f3.write('Hi there!')
        f3.close()
        os.mkdir('copytree_dir/')
        shutil.copy(f3.name, 'copytree_dir/no_file4.txt')
        os.mkdir('/copytree_dir_not_included/copytree_dir/no_file5.txt')
        shutil.copy(f3.name, '/copytree_dir_not_included/copytree_dir/no_file5.txt')
        os.mkdir('/copytree_dir/nested_dir/double_nest/')
        f6 = open('/copytree_dir/nested_dir/double_nest/yes_file6.txt', 'w')
        f6.write('File 6 Content.')
        f6.close()
        shutil.copy(f.name, '/copytree_dir/nested_dir/yes_file7.txt')
        os.mkdir('/new_dir_not_copied')
        f8 = open('/new_dir_not_copied/some_file8.txt', 'w')
        f8.close()

        # Copy target tree
        shutil.copytree('/copytree_dir', '/new_dir')
        self.assertTrue('/new_dir/yes_file1.txt' in self.fs._files)
        self.assertTrue('/new_dir/yes_file2.txt' in self.fs._files)
        self.assertFalse('/new_dir/no_file3.txt' in self.fs._files)
        self.assertFalse('/new_dir/no_file4.txt' in self.fs._files)
        self.assertFalse('/new_dir/no_file5.txt' in self.fs._files)
        self.assertTrue('/new_dir/nested_dir/double_nest/yes_file6.txt' in self.fs._files)
        self.assertTrue('/new_dir/nested_dir/yes_file7.txt' in self.fs._files)

        # Test mock_remove_tree removes the correct paths
        shutil.rmtree('/new_dir')
        self.assertFalse('/new_dir/yes_file1.txt' in self.fs._files)
        self.assertFalse('/new_dir/yes_file2.txt' in self.fs._files)
        self.assertFalse('/new_dir/nested_dir/double_nest/yes_file6.txt' in self.fs._files)
        self.assertFalse('/new_dir/nested_dir/yes_file7.txt' in self.fs._files)
        self.assertTrue(f8.name in self.fs._files)
        for path in self.fs._files:
            self.assertFalse(path.startswith('/new_dir/'))
        # TODO: Test and implement with real files


class TestMockFile(unittest.TestCase):
    def test_close(self):
        pass

    def test_closed(self):
        pass

    def test_dump(self):
        pass


class TestMockBuffer(unittest.TestCase):
    def test_with(self):
        pass

    def test_tell(self):
        pass

    def test_seek(self):
        pass

    def test_read(self):
        pass

    def test_readline(self):
        pass

    def test_readlines(self):
        pass

    def test_write(self):
        pass

    def test_close(self):
        pass

    def test_flush(self):
        pass
