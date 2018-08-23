"""
Licensed to the Apache Software Foundation (ASF) under one
or more contributor license agreements.  See the NOTICE file
distributed with this work for additional information
regarding copyright ownership.  The ASF licenses this file
to you under the Apache License, Version 2.0 (the
"License"); you may not use this file except in compliance
with the License.  You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

"""

from ambari_commons.os_check import OSCheck
from resource_management.core.exceptions import Fail
from resource_management.core.logger import Logger
from resource_management.libraries.resources.repository import Repository
from resource_management.libraries.functions.cluster_settings import get_cluster_setting_value
from resource_management.libraries.functions.is_empty import is_empty
import ambari_simplejson as json


__all__ = ["RepositoryUtil", "CommandRepository"]

# components_lits = repoName + postfix
UBUNTU_REPO_COMPONENTS_POSTFIX = "main"

class RepositoryUtil:
  def __init__(self, config, tags_to_skip):
    from resource_management.libraries.script import Script
    self.tags_to_skip = tags_to_skip

    # repo templates
    repo_file = config['repositoryFile']
    repo_rhel_suse = Script.get_cluster_settings().get_repo_suse_rhel_template()
    repo_ubuntu = Script.get_cluster_settings().get_repo_ubuntu_template()

    if is_empty(repo_file):
      return

    self.template = repo_rhel_suse if OSCheck.is_redhat_family() or OSCheck.is_suse_family() else repo_ubuntu
    self.command_repository = CommandRepository(repo_file)

  def create_repo_files(self):
    """
    Creates repositories in a consistent manner for all types
    :return: a dictionary with repo ID => repo file name mapping
    """
    if self.command_repository.mpack_id is None:
      raise Fail("The command repository was not parsed correctly")

    if 0 == len(self.command_repository.items):
      Logger.warning(
        "Repository for {0}/{1} has no repositories.  Ambari may not be managing this version.".format(
          self.command_repository.mpack_name, self.command_repository.version_string))
      return {}

    append_to_file = False  # initialize to False to create the file anew.
    repo_files = {}
    for repository in self.command_repository.items:
      if repository.repo_id is None:
        raise Fail("Repository with url {0} has no id".format(repository.base_url))

      if self.tags_to_skip & repository.tags:
        Logger.info("Repository with url {0} is not created due to its tags: {1}".format(repository.base_url, repository.tags))
        continue

      if not repository.ambari_managed:
        Logger.warning(
          "Repository for {0}/{1}/{2} is not managed by Ambari".format(
            self.command_repository.mpack_name, self.command_repository.version_string, repository.repo_id))
      else:
        Repository(repository.repo_id,
                   action="create",
                   base_url=repository.base_url,
                   mirror_list=repository.mirrors_list,
                   repo_file_name=self.command_repository.repo_filename,
                   repo_template=self.template,
                   components=repository.ubuntu_components,
                   append_to_file=append_to_file)
        append_to_file = True
        repo_files[repository.repo_id] = self.command_repository.repo_filename

    return repo_files

def create_repo_files(template, command_repository):
  """
  DEPRECATED. Is present for usage by old mpacks.
  Please use Script.repository_util.create_repo_files() instead.
  """
  from resource_management.libraries.script import Script
  return RepositoryUtil(Script.get_config(), set()).create_repo_files()

def _find_value(dictionary, key, default=None):
  """
  Helper to find a value in a dictionary
  """
  if key not in dictionary:
    return default

  return dictionary[key]


class CommandRepositoryFeature(object):
  def __init__(self, feat_dict):
    """
    :type feat_dict dict
    """
    self.pre_installed = _find_value(feat_dict, "preInstalled", default=False)
    self.scoped = _find_value(feat_dict, "scoped", default=True)


class CommandRepository(object):
  """
  Class that encapsulates the representation of repositories passed in a command.  This class
  should match the CommandRepository class.
  """

  def __init__(self, repo_object):
    """
    :type repo_object dict|basestring
    """

    if isinstance(repo_object, dict):
      json_dict = dict(repo_object)   # strict dict(from ConfigDict) to avoid hidden type conversions
    elif isinstance(repo_object, basestring):
      json_dict = json.loads(repo_object)
    else:
      raise Fail("Cannot deserialize command repository {0}".format(str(repo_object)))

    self.mpack_id = _find_value(json_dict, 'mpackId')
    self.mpack_name = _find_value(json_dict, 'mpackName')
    self.version_string = _find_value(json_dict, 'mpackVersion')
    self.repo_filename = _find_value(json_dict, 'repoFileName')
    self.feat = CommandRepositoryFeature(_find_value(json_dict, "feature", default={}))
    self.items = []

    repos_def = _find_value(json_dict, 'repositories')
    if repos_def is not None:
       if not isinstance(repos_def, list):
         repos_def = [repos_def]

       for repo_def in repos_def:
         self.items.append(CommandRepositoryItem(self, repo_def))

  def __str__(self):
    inner = []
    if self.mpack_id:
      inner.append("mpack_id: %s" % str(self.mpack_id))
    elif self.mpack_name:
      inner.append("mpack_name: %s" % str(self.mpack_name))
    elif self.version_string:
      inner.append("mpack_version: %s" % str(self.version_string))
    return "CommandRepository{%s}" % ", ".join(inner)


class CommandRepositoryItem(object):
  """
  Class that represents the entries of a CommandRepository.  This isn't meant to be instantiated
  outside a CommandRepository
  """

  def __init__(self, repo, json_dict):
    """
    :type repo CommandRepository
    :type json_dict dict
    """
    self._repo = repo

    self.repo_id = _find_value(json_dict, 'repoId')  # this is the id within the repo file, not an Ambari artifact
    self.repo_name = _find_value(json_dict, 'repoName')
    self.distribution = _find_value(json_dict, 'distribution')
    self.components = _find_value(json_dict, 'components')
    self.base_url = _find_value(json_dict, 'baseUrl')
    self.mirrors_list = _find_value(json_dict, 'mirrorsList')
    self.tags = set(_find_value(json_dict, 'tags', default=[]))
    self.ambari_managed = _find_value(json_dict, 'ambariManaged', default=True)

    self.ubuntu_components = [self.distribution if self.distribution else self.repo_name] + \
                             [self.components.replace(",", " ") if self.components else UBUNTU_REPO_COMPONENTS_POSTFIX]
    self.applicable_services = _find_value(json_dict, 'applicableServices')





