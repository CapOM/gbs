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

"""Implementation of subcmd: build
"""

import os
import glob

from gitbuildsys import msger, errors, utils

from gitbuildsys.conf import configmgr, encode_passwd
from gitbuildsys.oscapi import OSC, OSCError
from gitbuildsys.cmd_export import export_sources

import gbp.rpm
from gbp.rpm.git import GitRepositoryError, RpmGitRepository
from gbp.errors import GbpError

OSCRC_TEMPLATE = """[general]
apiurl = %(apiurl)s
plaintext_passwd=0
use_keyring=0
http_debug = %(http_debug)s
debug = %(debug)s
gnome_keyring=0
[%(apiurl)s]
user=%(user)s
passx=%(passwdx)s
"""


def main(args):
    """gbs remotebuild entry point."""

    obsconf = configmgr.get_current_profile().obs

    if not obsconf or not obsconf.url:
        msger.error('no obs api found, please add it to gbs conf and try again')

    apiurl = obsconf.url

    if not apiurl.user:
        msger.error('empty user is not allowed for remotebuild, '
                    'please add user/passwd to gbs conf, and try again')

    if args.commit and args.include_all:
        raise errors.Usage('--commit can\'t be specified together with '
                           '--include-all')

    obs_repo = args.repository
    obs_arch = args.arch

    if args.buildlog and None in (obs_repo, obs_arch):
        msger.error('please specify arch(-A) and repository(-R)')

    try:
        repo = RpmGitRepository(args.gitdir)
    except GitRepositoryError, err:
        msger.error(str(err))

    workdir = repo.path

    if not (args.buildlog or args.status):
        utils.git_status_checker(repo, args)

    # TODO: check ./packaging dir at first
    specs = glob.glob('%s/packaging/*.spec' % workdir)
    if not specs:
        msger.error('no spec file found under /packaging sub-directory')

    specfile = utils.guess_spec(workdir, args.spec)
    # get 'name' and 'version' from spec file
    try:
        spec = gbp.rpm.parse_spec(specfile)
    except GbpError, err:
        msger.error('%s' % err)

    if not spec.name:
        msger.error('can\'t get correct name.')
    package = spec.name

    base_prj = args.base_obsprj

    if args.target_obsprj is None:
        target_prj = obsconf.target or \
            "home:%s:gbs:%s" % (apiurl.user, base_prj)
    else:
        target_prj = args.target_obsprj

    api_passwd = apiurl.passwd if apiurl.passwd else ''
    # Create temporary oscrc
    oscrc = OSCRC_TEMPLATE % {
                "http_debug": 1 if msger.get_loglevel() == 'debug' else 0,
                "debug": 1 if msger.get_loglevel() == 'verbose' else 0,
                "apiurl": apiurl,
                "user": apiurl.user,
                "passwdx": encode_passwd(api_passwd),
            }

    tmpdir     = configmgr.get('tmpdir', 'general')
    tmpd = utils.Temp(prefix=os.path.join(tmpdir, '.gbs_remotebuild_'),
                      directory=True)
    exportdir = tmpd.path
    tmpf = utils.Temp(dirn=exportdir, prefix='.oscrc', content=oscrc)
    oscrcpath = tmpf.path

    api = OSC(apiurl, oscrc=oscrcpath)

    try:
        if args.buildlog:
            archlist = []
            status = api.get_results(target_prj, package)

            for build_repo in status.keys():
                for arch in status[build_repo]:
                    archlist.append('%-15s%-15s' % (build_repo, arch))
            if not obs_repo or not obs_arch or obs_repo not in status.keys() \
                   or obs_arch not in status[obs_repo].keys():
                msger.error('no valid repo / arch specified for buildlog, '\
                            'valid arguments of repo and arch are:\n%s' % \
                            '\n'.join(archlist))
            if status[obs_repo][obs_arch] not in ['failed', 'succeeded',
                                                  'building', 'finishing']:
                msger.error('build status of %s for %s/%s is %s, no build log.'\
                            % (package, obs_repo, obs_arch,
                               status[obs_repo][obs_arch]))
            msger.info('build log for %s/%s/%s/%s' % (target_prj, package,
                                                      obs_repo, obs_arch))
            print api.get_buildlog(target_prj, package, obs_repo, obs_arch)

            return 0

        if args.status:
            results = []

            status = api.get_results(target_prj, package)

            for build_repo in status.keys():
                for arch in status[build_repo]:
                    stat = status[build_repo][arch]
                    results.append('%-15s%-15s%-15s' % (build_repo, arch, stat))
            msger.info('build results from build server:\n%s' \
                       % '\n'.join(results))
            return 0

        msger.info('checking status of obs project: %s ...' % target_prj)
        if not api.exists(target_prj):
            # FIXME: How do you know that a certain user does not have
            # permissions to create any project, anywhewre?
            if args.target_obsprj and \
                   not target_prj.startswith('home:%s:' % apiurl.user):
                msger.error('no permission to create project %s, only sub '
                            'projects of home:%s are '
                            'allowed ' % (target_prj, apiurl.user))

            msger.info('copying settings of %s to %s' % (base_prj, target_prj))
            api.copy_project(base_prj, target_prj)

        if api.exists(target_prj, package):
            msger.info('cleaning existing package')
            api.remove_files(target_prj, package)
        else:
            msger.info('creating new package %s/%s' % (target_prj, package))
            api.create_package(target_prj, package)
    except OSCError, err:
        msger.error(str(err))

    with utils.Workdir(workdir):
        if args.commit:
            commit = args.commit
        elif args.include_all:
            commit = 'WC.UNTRACKED'
        else:
            commit = 'HEAD'
        relative_spec = specfile.replace('%s/' % workdir, '')
        export_sources(repo, commit, exportdir, relative_spec, args)

    try:
        commit_msg = repo.get_commit_info(args.commit or 'HEAD')['subject']
    except GitRepositoryError, exc:
        msger.error('failed to get commit info: %s' % exc)

    msger.info('commit packaging files to build server ...')
    try:
        api.commit_files(target_prj, package,
                         glob.glob("%s/*" % exportdir), commit_msg)
    except errors.ObsError, exc:
        msger.error('commit packages fail: %s, please check the permission '\
                    'of target project:%s' % (exc, target_prj))


    msger.info('local changes submitted to build server successfully')
    msger.info('follow the link to monitor the build progress:\n'
               '  %s/package/show?package=%s&project=%s' \
               % (apiurl.replace('api', 'build'), package, target_prj))
