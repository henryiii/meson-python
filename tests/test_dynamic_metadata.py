# SPDX-FileCopyrightText: 2026 The meson-python developers
#
# SPDX-License-Identifier: MIT

import importlib
import importlib.metadata
import pathlib
import shutil
import sys
import tarfile
import textwrap

import packaging.requirements
import pytest
import wheel.wheelfile

import mesonpy

from .conftest import in_git_repo_context, metadata, package_dir


pytest.importorskip('dynamic_metadata')


def test_wheel_metadata(wheel_dynamic_metadata_plugin):
    artifact = wheel.wheelfile.WheelFile(wheel_dynamic_metadata_plugin)
    meta = metadata(artifact.read('dynamic_metadata_plugin-1.0.0.dist-info/METADATA'))

    assert meta['summary'] == 'a plugin described dynamic-metadata-plugin'
    # entries are processed in order and list fields are extended
    assert meta['requires_dist'] == ['dyn-dep>=1', 'second-dep']
    # the wheel metadata is fully resolved
    assert 'dynamic' not in meta


def test_sdist_metadata(sdist_dynamic_metadata_plugin):
    with tarfile.open(sdist_dynamic_metadata_plugin, 'r:gz') as sdist:
        pkg_info = sdist.extractfile('dynamic_metadata_plugin-1.0.0/PKG-INFO').read()
    meta = metadata(pkg_info)

    assert meta['metadata_version'] == '2.2'
    # fields reported by the dynamic_wheel() plugin hook are marked dynamic
    assert [x.lower() for x in meta['dynamic']] == ['requires-dist']
    assert meta['summary'] == 'a plugin described dynamic-metadata-plugin'
    assert meta['requires_dist'] == ['dyn-dep>=1', 'second-dep']


def test_sdist_from_other_cwd(tmp_path, monkeypatch):
    # a provider path relative to the source dir must resolve even when the
    # Project is driven from a different working directory
    source_dir = tmp_path / 'pkg'
    shutil.copytree(package_dir / 'dynamic-metadata-plugin', source_dir)
    source_dir.joinpath('scripts').mkdir()
    source_dir.joinpath('plugin.py').rename(source_dir / 'scripts' / 'plugin.py')
    pyproject = source_dir / 'pyproject.toml'
    pyproject.write_text(pyproject.read_text().replace("path = '.'", "path = 'scripts'"))

    monkeypatch.delitem(sys.modules, 'plugin', raising=False)
    monkeypatch.chdir(tmp_path)
    with in_git_repo_context(source_dir):
        project = mesonpy.Project(source_dir, tmp_path / 'build', build_state='sdist')
        sdist_path = project.sdist(tmp_path)

    with tarfile.open(sdist_path, 'r:gz') as sdist:
        pkg_info = sdist.extractfile('dynamic_metadata_plugin-1.0.0/PKG-INFO').read()
    meta = metadata(pkg_info)
    assert [x.lower() for x in meta['dynamic']] == ['requires-dist']


def test_get_requires(package_dynamic_metadata_plugin):
    for hook in mesonpy.get_requires_for_build_wheel, mesonpy.get_requires_for_build_sdist:
        names = {packaging.requirements.Requirement(x).name for x in hook()}
        assert 'dynamic-metadata' in names
        assert 'test-plugin-requirement' in names


def test_missing_dynamic_metadata_package(monkeypatch, package_dynamic_metadata_plugin):
    monkeypatch.setitem(sys.modules, 'dynamic_metadata', None)
    monkeypatch.setitem(sys.modules, 'dynamic_metadata.loader', None)

    pyproject = {
        'project': {'name': 'example', 'version': '1.0.0', 'dynamic': ['dependencies']},
        'tool': {'dynamic-metadata': [{'provider': 'does.not.matter'}]},
    }
    with pytest.raises(mesonpy.ConfigError, match='add "dynamic-metadata >= [0-9.]+" to "build-system.requires"'):
        mesonpy._process_dynamic_metadata(pyproject, pathlib.Path(), 'wheel')

    # the requirement is returned so that the build step can import the package
    requirements = mesonpy._get_requires_for_dynamic_metadata()
    assert requirements == [f'dynamic-metadata >= {mesonpy._DYNAMIC_METADATA_REQUIRED_VERSION}']


def test_unresolved_dynamic_field(package_dynamic_metadata_plugin):
    source_dir = package_dynamic_metadata_plugin
    pyproject = {
        'project': {
            'name': 'example',
            'version': '1.0.0',
            'dynamic': ['description', 'dependencies', 'keywords'],
        },
        'tool': {'dynamic-metadata': [
            {'provider': {'path': '.', 'module': 'plugin'}, 'dependencies': ['a']},
        ]},
    }
    with pytest.raises(mesonpy.ConfigError, match='not set by any dynamic-metadata plugin: "keywords"'):
        mesonpy._process_dynamic_metadata(pyproject, source_dir, 'wheel')


def test_no_entries_passthrough():
    pyproject = {'project': {'name': 'example', 'version': '1.0.0'}}
    processed, dynamic_headers = mesonpy._process_dynamic_metadata(pyproject, pathlib.Path(), 'wheel')
    assert processed is pyproject
    assert dynamic_headers == []


def test_malformed_config():
    with pytest.raises(mesonpy.ConfigError, match='"tool.dynamic-metadata" must be an array of tables'):
        mesonpy._dynamic_metadata_entries({'tool': {'dynamic-metadata': 'nope'}})


PLUGIN_PYPROJECT = '''
[build-system]
build-backend = 'mesonpy'
requires = ['meson-python', 'dynamic-metadata']

[project]
name = 'example'
dynamic = ['version', 'description', 'dependencies']

[[tool.dynamic-metadata]]
provider = {path = '.', module = 'plugin'}
'''


@pytest.fixture
def plugin_project(tmp_path, monkeypatch):
    """Create a project in tmp_path using the given plugin source."""
    def make(plugin: str, pyproject: str = PLUGIN_PYPROJECT) -> pathlib.Path:
        tmp_path.joinpath('pyproject.toml').write_text(pyproject)
        tmp_path.joinpath('meson.build').write_text("project('example', version: '1.2.3')\n")
        tmp_path.joinpath('plugin.py').write_text(textwrap.dedent(plugin))
        monkeypatch.delitem(sys.modules, 'plugin', raising=False)
        monkeypatch.chdir(tmp_path)
        # drop the cached directory listing for the relative provider path
        importlib.invalidate_caches()
        return tmp_path
    return make


def test_plugin_sees_meson_version(plugin_project):
    # the version resolved from meson.build is visible to the plugins
    source_dir = plugin_project('''
        def dynamic_metadata(settings, project):
            return {'description': 'x', 'dependencies': [f'example-core == {project["version"]}']}
    ''')
    project = mesonpy.Project(source_dir, source_dir / 'build')
    assert str(project._metadata.version) == '1.2.3'
    assert [str(x) for x in project._metadata.dependencies] == ['example-core==1.2.3']


def test_field_deferred_to_wheel(plugin_project):
    # a field not computed in the sdist state but reported by dynamic_wheel()
    # stays dynamic in the sdist and is computed when building the wheel
    source_dir = plugin_project('''
        state = None

        def build_state(value):
            global state
            state = value

        def dynamic_metadata(settings, project):
            fragment = {'description': 'x'}
            if state != 'sdist':
                fragment['dependencies'] = ['wheel-only']
            return fragment

        def dynamic_wheel(settings):
            return {'dependencies': True}
    ''')
    with in_git_repo_context(source_dir):
        sdist_path = mesonpy.Project(source_dir, source_dir / 'build', build_state='sdist').sdist(source_dir)
    with tarfile.open(sdist_path, 'r:gz') as sdist:
        meta = metadata(sdist.extractfile('example-1.2.3/PKG-INFO').read())
    assert [x.lower() for x in meta['dynamic']] == ['requires-dist']
    assert 'requires_dist' not in meta

    project = mesonpy.Project(source_dir, source_dir / 'build')
    assert [str(x) for x in project._metadata.dependencies] == ['wheel-only']


def test_sdist_from_default_build_state(plugin_project):
    # Project.sdist() must produce sdist metadata regardless of the build
    # state the project was constructed with
    source_dir = plugin_project('''
        def dynamic_metadata(settings, project):
            return {'description': 'x', 'dependencies': ['a']}

        def dynamic_wheel(settings):
            return {'dependencies': True}
    ''')
    with in_git_repo_context(source_dir):
        sdist_path = mesonpy.Project(source_dir, source_dir / 'build').sdist(source_dir)
    with tarfile.open(sdist_path, 'r:gz') as sdist:
        meta = metadata(sdist.extractfile('example-1.2.3/PKG-INFO').read())
    assert [x.lower() for x in meta['dynamic']] == ['requires-dist']


def test_plugin_error(plugin_project):
    # any exception raised by a plugin is reported as a configuration error
    source_dir = plugin_project('''
        def dynamic_metadta(settings, project):
            return {}
    ''')
    with pytest.raises(mesonpy.ConfigError, match="AttributeError: module 'plugin' has no attribute 'dynamic_metadata'"):
        mesonpy.Project(source_dir, source_dir / 'build')


def test_unset_dynamic_field(plugin_project):
    source_dir = plugin_project('''
        def dynamic_metadata(settings, project):
            return {'description': 'x'}
    ''')
    with pytest.raises(mesonpy.ConfigError, match='not set by any dynamic-metadata plugin: "dependencies"'):
        mesonpy.Project(source_dir, source_dir / 'build')


def test_get_requires_plugin_import_error(plugin_project):
    # a plugin importing a package it declares as its own requirement can
    # not be loaded before that requirement is installed
    plugin_project('''
        import not_installed_package

        def dynamic_metadata(settings, project):
            return {}
    ''')
    assert mesonpy._get_requires_for_dynamic_metadata() == [
        f'dynamic-metadata >= {mesonpy._DYNAMIC_METADATA_REQUIRED_VERSION}']


def test_old_dynamic_metadata_package(monkeypatch, package_dynamic_metadata_plugin):
    monkeypatch.setattr(importlib.metadata, 'version', lambda name: '0.4.0')
    with pytest.raises(mesonpy.ConfigError, match='dynamic-metadata 0.4.0 is too old'):
        mesonpy.Project(package_dynamic_metadata_plugin, package_dynamic_metadata_plugin / 'build')
    # the requirements hook returns the requirement so that a suitable version can be installed
    assert mesonpy._get_requires_for_dynamic_metadata() == [
        f'dynamic-metadata >= {mesonpy._DYNAMIC_METADATA_REQUIRED_VERSION}']
