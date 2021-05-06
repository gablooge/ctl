"""
Plugin that allows you to handle repository versioning
"""

import argparse
import os

import semver

import ctl
from ctl.auth import expose
from ctl.exceptions import OperationNotExposed, UsageError
from ctl.plugins.version_base import VersionBasePlugin, VersionBasePluginConfig
from ctl.util.versioning import validate_prerelease


@ctl.plugin.register("semver2")
class Semver2Plugin(VersionBasePlugin):
    """
    manage repository versioning
    """

    class ConfigSchema(VersionBasePlugin.ConfigSchema):
        config = VersionBasePluginConfig()

    @classmethod
    def add_arguments(cls, parser, plugin_config, confu_cli_args):

        shared_parser = argparse.ArgumentParser(add_help=False)

        release_parser = argparse.ArgumentParser(add_help=False)
        group = release_parser.add_mutually_exclusive_group(required=False)

        group.add_argument(
            "--init",
            action="store_true",
            help="automatically create " "Ctl/VERSION file if it does not exist",
        )

        # subparser that routes operation
        sub = parser.add_subparsers(title="Operation", dest="op")

        # operation `tag`
        op_tag_parser = sub.add_parser(
            "tag",
            help="tag with a specified version",
            parents=[shared_parser, release_parser],
        )
        op_tag_parser.add_argument(
            "version", nargs=1, type=str, help="version string to tag with"
        )

        cls.add_repo_argument(op_tag_parser, plugin_config)

        # operation `bump`
        op_bump_parser = sub.add_parser(
            "bump",
            help="bump semantic version",
            parents=[shared_parser, release_parser],
        )
        op_bump_parser.add_argument(
            "version",
            nargs=1,
            type=str,
            choices=["major", "minor", "patch", "prerelease"],
            help="bumps the specified version segment by 1",
        )

        confu_cli_args.add(op_bump_parser, "changelog_validate")

        cls.add_repo_argument(op_bump_parser, plugin_config)

    def execute(self, **kwargs):

        super().execute(**kwargs)

        if "version" in kwargs and isinstance(kwargs["version"], list):
            kwargs["version"] = kwargs["version"][0]

        kwargs["repo"] = self.get_config("repository")

        op = kwargs.get("op")
        fn = self.get_op(op)

        if not getattr(fn, "exposed", False):
            raise OperationNotExposed(op)

        fn(**kwargs)

    @expose("ctl.{plugin_name}.tag")
    def tag(self, version, repo, **kwargs):
        """
        tag a version according to version specified

        **Arguments**

        - version (`str`): tag version (eg. 1.0.0)
        - repo (`str`): name of existing repository type plugin instance

        **Keyword Arguments**
        - prerelease (`str`): identifier if this is a prerelease version
        - release (`bool`): if `True` also run `merge_release`
        """
        repo_plugin = self.repository(repo)
        repo_plugin.pull()

        if not repo_plugin.is_clean:
            raise UsageError("Currently checked out branch is not clean")

        if kwargs.get("prerelease"):
            prerelease = kwargs.get("prerelease")
            prerelease = validate_prerelease(prerelease)
            version = f"{version}-{prerelease}"

        # Use semver to parse version
        version = semver.VersionInfo.parse(version)
        version_tag = str(version)

        self.log.info(f"Preparing to tag {repo_plugin.checkout_path} as {version_tag}")

        if not os.path.exists(repo_plugin.repo_ctl_dir):
            os.makedirs(repo_plugin.repo_ctl_dir)

        files = []

        self.update_version_files(repo_plugin, version_tag, files)

        repo_plugin.commit(files=files, message=f"Version {version_tag}", push=True)
        repo_plugin.tag(version_tag, message=version_tag, push=True)

    @expose("ctl.{plugin_name}.bump")
    def bump(self, version, repo, **kwargs):
        """
        bump a version according to semantic version

        **Arguments**

        - version (`str`): major, minor, patch or dev
        - repo (`str`): name of existing repository type plugin instance
        """

        repo_plugin = self.repository(repo)
        repo_plugin.pull()

        if version not in ["major", "minor", "patch", "prerelease"]:
            raise ValueError(f"Invalid semantic version: {version}")

        current = semver.VersionInfo.parse(repo_plugin.version)

        if version == "major":
            new_version = current.bump_major()
        elif version == "minor":
            new_version = current.bump_minor()
        elif version == "patch":
            new_version = current.bump_patch()
        elif version == "prerelease":
            if not current.prerelease:
                raise ValueError(
                    "Cannot bump the prerelease if it's not a prereleased version"
                )
            else:
                new_version = current.bump_prerelease()

        self.log.info(
            "Bumping semantic version: {} to {}".format(str(current), str(new_version))
        )

        if self.get_config("changelog_validate"):
            self.validate_changelog(repo, str(new_version))

        self.tag(version=str(new_version), repo=repo, **kwargs)

    @expose("ctl.{plugin_name}.release")
    def release(self, repo, **kwargs):
        """
        release and tag a version

        **Arguments**

        - repo (`str`): name of existing repository type plugin instance
        """
        repo_plugin = self.repository(repo)
        repo_plugin.pull()

        version = repo_plugin.version

        # Use semver to parse version
        version = semver.VersionInfo.parse(version)
        version = version.replace(prerelease=None)
        self.tag(version=str(version), repo=repo, **kwargs)
