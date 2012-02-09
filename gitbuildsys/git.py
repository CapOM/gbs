#!/usr/bin/python -tt
# vim: ai ts=4 sts=4 et sw=4
#
# Copyright (c) 2011 Intel, Inc.
#
# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation; version 2 of the License
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY
# or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License
# for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc., 59
# Temple Place - Suite 330, Boston, MA 02111-1307, USA.

import os

# internal modules
import runner
import errors
import msger
from utils import Workdir

class Git:
    def __init__(self, path):
        if not os.path.isdir(os.path.join(path, '.git')):
            raise errors.GitInvalid(path)

        self.path = os.path.abspath(path)

        # as cache
        self.cur_branch = None
        self.branches = None

    def _exec_git(self, command, args=[]):
        """Exec a git command and return the output
        """

        cmd = ['git', command] + args

        cmdln = ' '.join(cmd)
        msger.debug('run command: %s' % cmdln)

        with Workdir(self.path):
            ret, out = runner.runtool(cmd)

        if ret:
            raise errors.GitError("command error for: %s" % cmdln)

        return out

    def status(self, *args):
        outs = self._exec_git('status', ['-s'] + list(args))

        sts = {}
        for line in outs.splitlines():
            st = line[:2]
            if st not in sts:
                sts[st] = [line[2:].strip()]
            else:
                sts[st].append(line[2:].strip())

        return sts

    def ls_files(self):
        """Return the files list
        """
        return filter(None, self._exec_git('ls-files').splitlines())

    def _get_branches(self):
        """Return the branches list, current working branch is the first
        element.
        """

        branches = []
        for line in self._exec_git('branch', ['--no-color']).splitlines():
            br = line.strip().split()[-1]

            if line.startswith('*'):
                current_branch = br

            branches.append(br)

        return (current_branch, branches)

    def get_branches(self):
        if not self.cur_branch or not self.branches:
            self.cur_branch, self.branches = \
                self._get_branches()

        return (self.cur_branch, self.branches)

    def is_clean(self):
        """does the repository contain any uncommitted modifications"""

        gitsts = self.status()
        if 'M ' in gitsts or ' M' in gitsts:
            return False
        else:
            return True

    def has_branch(self, br, remote=False):
        """Check if the repository has branch 'br'
          @param remote: only liste remote branches
        """

        if remote:
            options = [ '--no-color', '-r' ]

            for line in self._exec_git('branch', options).splitlines():
                rbr = line.strip().split()[-1]
                if br == rbr:
                    return True

            return False

        else:
            return (br in self.get_branches()[1])

    def archive_tar(self, prefix, tarname, treeish = None):
        """Archive git tree to tar ball
          @prefix: tarball topdir 
          @output: output tarball name
          @treeish: commit ID archive from
        """
        filetypes = ['.tar.gz', '.tar.bz2', '.tgz']
        tarfile = None
        compress = None
        for type in filetypes:
           if tarname.endswith(type):
               tarfile = "%s.tar" % tarname.replace(type, '')
               compress = type
               break
        else:
            raise errors.GitError("Can't support tarball type, "\
                                  "supported types: %s" % ', '.join(filetypes))

        if treeish is None:
            treeish = 'HEAD'

        options = [ treeish, '--output=%s' % tarfile, \
                    '--prefix=%s' % prefix ]
        self._exec_git('archive', options)

        if compress == '.tar.bz2':
            runner.quiet('bzip2 -f %s' % tarfile)

        if compress == 'gz':
            # TODO: implement later.
            pass
