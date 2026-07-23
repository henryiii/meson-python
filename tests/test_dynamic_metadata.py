# SPDX-FileCopyrightText: 2026 The meson-python developers
#
# SPDX-License-Identifier: MIT

import pathlib
import shutil
import sys
import tarfile

import packaging.requirements
import pyproject_metadata
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
    processed = mesonpy._process_dynamic_metadata(pyproject, source_dir, 'wheel')
    assert processed['project']['dependencies'] == ['a']
    assert processed['project']['dynamic'] == ['keywords']
    with pytest.raises(pyproject_metadata.ConfigurationError, match='Unsupported dynamic fields: "keywords"'):
        mesonpy.Metadata.from_pyproject(processed, source_dir)


def test_no_entries_passthrough():
    pyproject = {'project': {'name': 'example', 'version': '1.0.0'}}
    processed = mesonpy._process_dynamic_metadata(pyproject, pathlib.Path(), 'wheel')
    assert processed is pyproject


def test_malformed_config():
    with pytest.raises(mesonpy.ConfigError, match='"tool.dynamic-metadata" must be an array of tables'):
        mesonpy._dynamic_metadata_entries({'tool': {'dynamic-metadata': 'nope'}})
