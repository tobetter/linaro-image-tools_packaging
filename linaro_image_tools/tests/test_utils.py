# Copyright (C) 2010, 2011 Linaro
#
# Author: Guilherme Salgado <guilherme.salgado@linaro.org>
#
# This file is part of Linaro Image Tools.
#
# Linaro Image Tools is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Linaro Image Tools is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import os
import stat
import subprocess
import sys
import logging
import tempfile
import tarfile

from linaro_image_tools import cmd_runner, utils
from linaro_image_tools.testing import TestCaseWithFixtures
from linaro_image_tools.tests.fixtures import (
    CreateTempDirFixture,
    MockCmdRunnerPopenFixture,
    MockSomethingFixture,
    )
from linaro_image_tools.utils import (
    ensure_command,
    find_command,
    install_package_providing,
    preferred_tools_dir,
    UnableToFindPackageProvidingCommand,
    verify_file_integrity,
    check_file_integrity_and_log_errors,
    path_in_tarfile_exists,
    IncompatibleOptions,
    prep_media_path,
    additional_option_checks,
    )

sudo_args = " ".join(cmd_runner.SUDO_ARGS)


class TestPathInTarfile(TestCaseWithFixtures):
    def setUp(self):
        super(TestPathInTarfile, self).setUp()
        tempdir = self.useFixture(CreateTempDirFixture()).get_temp_dir()
        self.tarfile_name = os.path.join(tempdir, 'test_tarfile.tar.gz')
        self.tempfile_added = self.createTempFileAsFixture()
        self.tempfile_unused = self.createTempFileAsFixture()
        with tarfile.open(self.tarfile_name, 'w:gz') as tar:
            tar.add(self.tempfile_added)

    def test_file_exists(self):
        self.assertTrue(path_in_tarfile_exists(self.tempfile_added[1:],
                                               self.tarfile_name))

    def test_file_does_not_exist(self):
        self.assertFalse(path_in_tarfile_exists(self.tempfile_unused[1:],
                                                self.tarfile_name))


class TestVerifyFileIntegrity(TestCaseWithFixtures):

    filenames_in_shafile = ['verified-file1', 'verified-file2']

    class MockCmdRunnerPopen(object):
        def __call__(self, cmd, *args, **kwargs):
            self.returncode = 0
            return self

        def communicate(self, input=None):
            self.wait()
            return ': OK\n'.join(
                TestVerifyFileIntegrity.filenames_in_shafile) + ': OK\n', ''

        def wait(self):
            return self.returncode


    class MockCmdRunnerPopen_sha1sum_fail(object):
        def __call__(self, cmd, *args, **kwargs):
            self.returncode = 0
            return self

        def communicate(self, input=None):
            self.wait()
            return ': ERROR\n'.join(
                TestVerifyFileIntegrity.filenames_in_shafile) + ': ERROR\n', ''

        def wait(self):
            return self.returncode


    class MockCmdRunnerPopen_wait_fails(object):
        def __call__(self, cmd, *args, **kwargs):
            self.returncode = 0
            return self

        def communicate(self, input=None):
            self.wait()
            return ': OK\n'.join(
                TestVerifyFileIntegrity.filenames_in_shafile) + ': OK\n', ''

        def wait(self):
            stdout = ': OK\n'.join(
                TestVerifyFileIntegrity.filenames_in_shafile) + ': OK\n'
            raise cmd_runner.SubcommandNonZeroReturnValue([], 1, stdout, None)

    class FakeTempFile():
        name = "/tmp/1"

        def close(self):
            pass

        def read(self):
            return ""

    def test_verify_files(self):
        fixture = self.useFixture(MockCmdRunnerPopenFixture())
        self.useFixture(MockSomethingFixture(tempfile, 'NamedTemporaryFile',
                                             self.FakeTempFile))
        hash_filename = "dummy-file.txt"
        signature_filename = hash_filename + ".asc"
        verify_file_integrity([signature_filename])
        self.assertEqual(
            ['gpg --status-file=%s --verify %s' % (self.FakeTempFile.name,
                                                   signature_filename),
             'sha1sum -c %s' % hash_filename],
            fixture.mock.commands_executed)
        
    def test_verify_files_returns_files(self):
        self.useFixture(MockSomethingFixture(cmd_runner, 'Popen',
                                             self.MockCmdRunnerPopen()))
        hash_filename = "dummy-file.txt"
        signature_filename = hash_filename + ".asc"
        verified_files, _, _ = verify_file_integrity([signature_filename])
        self.assertEqual(self.filenames_in_shafile, verified_files)

    def test_check_file_integrity_and_print_errors(self):
        self.useFixture(MockSomethingFixture(cmd_runner, 'Popen',
                                             self.MockCmdRunnerPopen()))
        hash_filename = "dummy-file.txt"
        signature_filename = hash_filename + ".asc"
        result, verified_files = check_file_integrity_and_log_errors(
                                                [signature_filename],
                                                self.filenames_in_shafile[0],
                                                [self.filenames_in_shafile[1]])
        self.assertEqual(self.filenames_in_shafile, verified_files)

        # The sha1sums are faked as passing and all commands return 0, so
        # it should look like GPG passed
        self.assertTrue(result)

    def test_check_file_integrity_and_print_errors_fail_sha1sum(self):
        logging.getLogger().setLevel(100)  # Disable logging messages to screen
        self.useFixture(MockSomethingFixture(cmd_runner, 'Popen',
                                    self.MockCmdRunnerPopen_sha1sum_fail()))
        hash_filename = "dummy-file.txt"
        signature_filename = hash_filename + ".asc"
        result, verified_files = check_file_integrity_and_log_errors(
                                                [signature_filename],
                                                self.filenames_in_shafile[0],
                                                [self.filenames_in_shafile[1]])
        self.assertEqual([], verified_files)

        # The sha1sums are faked as failing and all commands return 0, so
        # it should look like GPG passed
        self.assertFalse(result)
        logging.getLogger().setLevel(logging.WARNING)

    def test_check_file_integrity_and_print_errors_fail_gpg(self):
        logging.getLogger().setLevel(100)  # Disable logging messages to screen
        self.useFixture(MockSomethingFixture(cmd_runner, 'Popen',
                                    self.MockCmdRunnerPopen_wait_fails()))
        hash_filename = "dummy-file.txt"
        signature_filename = hash_filename + ".asc"
        result, verified_files = check_file_integrity_and_log_errors(
                                                [signature_filename],
                                                self.filenames_in_shafile[0],
                                                [self.filenames_in_shafile[1]])
        self.assertEqual([], verified_files)

        # The sha1sums are faked as passing and all commands return 1, so
        # it should look like GPG failed
        self.assertFalse(result)
        logging.getLogger().setLevel(logging.WARNING)

class TestEnsureCommand(TestCaseWithFixtures):

    install_pkg_providing_called = False

    def setUp(self):
        super(TestEnsureCommand, self).setUp()
        self.useFixture(MockSomethingFixture(
            sys, 'stdout', open('/dev/null', 'w')))

    def test_command_already_present(self):
        self.mock_install_package_providing()
        ensure_command('apt-get')
        self.assertFalse(self.install_pkg_providing_called)

    def test_command_not_present(self):
        self.mock_install_package_providing()
        ensure_command('apt-get-two-o')
        self.assertTrue(self.install_pkg_providing_called)

    def mock_install_package_providing(self):
        def mock_func(command):
            self.install_pkg_providing_called = True
        self.useFixture(MockSomethingFixture(
            utils, 'install_package_providing', mock_func))


class TestFindCommand(TestCaseWithFixtures):

    def test_preferred_dir(self):
        tempdir = self.useFixture(CreateTempDirFixture()).get_temp_dir()
        lmc = 'linaro-media-create'
        path = os.path.join(tempdir, lmc)
        open(path, 'w').close()
        os.chmod(path, stat.S_IXUSR)
        self.assertEquals(path, find_command(lmc, tempdir))

    def test_existing_command(self):
        lmc = 'linaro-media-create'
        prefer_dir = preferred_tools_dir()
        if prefer_dir is None:
            expected, _ = cmd_runner.run(
                ['which', lmc, ],
                stdout=subprocess.PIPE).communicate()
            expected = expected.strip()
        else:
            expected = os.path.join(prefer_dir, lmc)
        self.assertEquals(expected, find_command(lmc))

    def test_nonexisting_command(self):
        self.assertEquals(find_command('linaro-moo'), None)


class TestInstallPackageProviding(TestCaseWithFixtures):

    def test_found_package(self):
        self.useFixture(MockSomethingFixture(
            sys, 'stdout', open('/dev/null', 'w')))
        fixture = self.useFixture(MockCmdRunnerPopenFixture())
        install_package_providing('mkfs.vfat')
        self.assertEqual(
            ['%s apt-get --yes install dosfstools' % sudo_args],
            fixture.mock.commands_executed)

    def test_not_found_package(self):
        self.assertRaises(
            UnableToFindPackageProvidingCommand,
            install_package_providing, 'mkfs.lean')


class Args():
    def __init__(self, directory, device, board):
        self.directory = directory
        self.device = device
        self.board = board


class TestPrepMediaPath(TestCaseWithFixtures):

    def test_prep_media_path(self):
        self.useFixture(MockSomethingFixture(os.path, 'abspath', lambda x: x))
        self.useFixture(MockSomethingFixture(os, "makedirs", lambda x: x))

        self.assertEqual("testdevice",
                         prep_media_path(Args(directory=None,
                                              device="testdevice",
                                              board="testboard")))

        self.assertEqual("/foo/bar/testdevice",
                         prep_media_path(Args(directory="/foo/bar",
                                              device="testdevice",
                                              board="testboard")))

class TestPrepMediaPath(TestCaseWithFixtures):

    def test_additional_option_checks(self):
        self.useFixture(MockSomethingFixture(os.path, 'abspath', lambda x: x))
        self.useFixture(MockSomethingFixture(os, "makedirs", lambda x: x))

        self.assertRaises(IncompatibleOptions, additional_option_checks,
                          Args(directory="/foo/bar",
                               device="/testdevice",
                               board="testboard"))

        sys.argv.append("--mmc")
        self.assertRaises(IncompatibleOptions, additional_option_checks,
                          Args(directory="/foo/bar",
                               device="testdevice",
                               board="testboard"))
        sys.argv.remove("--mmc")
