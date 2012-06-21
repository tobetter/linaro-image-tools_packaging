# Copyright (C) 2010, 2011 Linaro
#
# Author: James Westby <james.westby@linaro.org>
#
# This file is part of Linaro Image Tools.
#
# Linaro Image Tools is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# Linaro Image Tools is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Linaro Image Tools; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301,
# USA.

import logging
import errno
import subprocess
import tempfile
import os
import shutil

from linaro_image_tools import cmd_runner

from linaro_image_tools.hwpack.config import Config
from linaro_image_tools.hwpack.hardwarepack import HardwarePack, Metadata
from linaro_image_tools.hwpack.packages import (
    FetchedPackage,
    LocalArchiveMaker,
    PackageFetcher,
    )


logger = logging.getLogger(__name__)


LOCAL_ARCHIVE_LABEL = 'hwpack-local'


class ConfigFileMissing(Exception):

    def __init__(self, filename):
        self.filename = filename
        super(ConfigFileMissing, self).__init__(
            "No such config file: '%s'" % self.filename)


class PackageUnpacker(object):
    def __enter__(self):
        self.tempdir = tempfile.mkdtemp()
        return self

    def __exit__(self, type, value, traceback):
        if self.tempdir is not None and os.path.exists(self.tempdir):
            shutil.rmtree(self.tempdir)

    def unpack_package(self, package_file_name):
        # We could extract only a single file, but since dpkg will pipe
        # the entire package through tar anyway we might as well extract all.
        p = cmd_runner.run(["tar", "-C", self.tempdir, "-xf", "-"],
                           stdin=subprocess.PIPE)
        cmd_runner.run(["dpkg", "--fsys-tarfile", package_file_name],
                       stdout=p.stdin).communicate()
        p.communicate()

    def get_file(self, package, file):
        self.unpack_package(package)
        logger.debug("Unpacked package %s." % package)
        temp_file = os.path.join(self.tempdir, file)
        assert os.path.exists(temp_file), "The file '%s' was " \
            "not found in the package '%s'." % (file, package)
        return temp_file


class HardwarePackBuilder(object):

    def __init__(self, config_path, version, local_debs):
        try:
            with open(config_path) as fp:
                self.config = Config(fp)
        except IOError, e:
            if e.errno == errno.ENOENT:
                raise ConfigFileMissing(config_path)
            raise
        self.config.validate()
        self.format = self.config.format
        self.version = version
        self.local_debs = local_debs

    def find_fetched_package(self, packages, wanted_package_name):
        wanted_package = None
        for package in packages:
            if package.name == wanted_package_name:
                wanted_package = package
                break
        else:
            raise AssertionError("Package '%s' was not fetched." % \
                                wanted_package_name)
        return wanted_package

    def add_file_to_hwpack(self, package, wanted_file, package_unpacker,
                           hwpack, target_path):
        tempfile_name = package_unpacker.get_file(
            package.filepath, wanted_file)
        return hwpack.add_file(target_path, tempfile_name)

    def build(self):
        for architecture in self.config.architectures:
            logger.info("Building for %s" % architecture)
            metadata = Metadata.from_config(
                self.config, self.version, architecture)
            hwpack = HardwarePack(metadata)
            sources = self.config.sources
            with LocalArchiveMaker() as local_archive_maker:
                hwpack.add_apt_sources(sources)
                sources = sources.values()
                packages = self.config.packages[:]
                if self.config.u_boot_package is not None:
                    packages.append(self.config.u_boot_package)
                if self.config.spl_package is not None:
                    packages.append(self.config.spl_package)
                local_packages = [
                    FetchedPackage.from_deb(deb)
                    for deb in self.local_debs]
                sources.append(
                    local_archive_maker.sources_entry_for_debs(
                        local_packages, LOCAL_ARCHIVE_LABEL))
                packages.extend([lp.name for lp in local_packages])
                logger.info("Fetching packages")
                fetcher = PackageFetcher(
                    sources, architecture=architecture,
                    prefer_label=LOCAL_ARCHIVE_LABEL)
                with fetcher:
                    with PackageUnpacker() as package_unpacker:
                        fetcher.ignore_packages(self.config.assume_installed)
                        packages = fetcher.fetch_packages(
                            packages,
                            download_content=self.config.include_debs)

                        u_boot_package = None
                        if self.config.u_boot_file is not None:
                            assert self.config.u_boot_package is not None
                            u_boot_package = self.find_fetched_package(
                                packages, self.config.u_boot_package)
                            hwpack.metadata.u_boot = self.add_file_to_hwpack(
                                u_boot_package, self.config.u_boot_file,
                                package_unpacker, hwpack, hwpack.U_BOOT_DIR)

                        spl_package = None
                        if self.config.spl_file is not None:
                            assert self.config.spl_package is not None
                            spl_package = self.find_fetched_package(
                                packages, self.config.spl_package)
                            hwpack.metadata.spl = self.add_file_to_hwpack(
                                spl_package, self.config.spl_file,
                                package_unpacker, hwpack, hwpack.SPL_DIR)

                        # u_boot_package and spl_package can be identical
                        if (u_boot_package is not None and
                            u_boot_package in packages):
                            packages.remove(u_boot_package)
                        if (spl_package is not None and
                            spl_package in packages):
                            packages.remove(spl_package)

                        logger.debug("Adding packages to hwpack")
                        hwpack.add_packages(packages)
                        for local_package in local_packages:
                            if local_package not in packages:
                                logger.warning(
                                    "Local package '%s' not included",
                                    local_package.name)
                        hwpack.add_dependency_package(self.config.packages)
                        with open(hwpack.filename(), 'w') as f:
                            hwpack.to_file(f)
                            logger.info("Wrote %s" % hwpack.filename())
                        with open(hwpack.filename('.manifest.txt'), 'w') as f:
                            f.write(hwpack.manifest_text())
