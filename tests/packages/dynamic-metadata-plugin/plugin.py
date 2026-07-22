# SPDX-FileCopyrightText: 2026 The meson-python developers
#
# SPDX-License-Identifier: MIT


def dynamic_metadata(settings, project):
    return {
        'description': f'a plugin described {project["name"]}',
        'dependencies': list(settings['dependencies']),
    }


def dynamic_wheel(settings):
    return {'dependencies': True}


def get_requires_for_dynamic_metadata(settings):
    return ['test-plugin-requirement']
