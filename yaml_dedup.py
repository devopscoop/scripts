#!/usr/bin/env python3
"""
Remove duplicate entries from second YAML file that exist in first YAML file.
Processes at the line level so comments, quoting, and formatting are preserved.
Usage: python yaml_dedup.py file1.yaml file2.yaml
"""

import re
import sys

from ruamel.yaml import YAML


def _collect_removed_paths(base, override, prefix=''):
    """Return set of dotted key paths to remove from override.
    Mutates *override* (a copy) to detect when parents become empty."""
    paths = set()
    keys_to_remove = []
    for key, val in list(override.items()):
        path = f"{prefix}.{key}" if prefix else str(key)
        if key not in base:
            continue
        if isinstance(val, dict) and isinstance(base[key], dict):
            sub = _collect_removed_paths(base[key], val, path)
            paths.update(sub)
            if not val:
                keys_to_remove.append(key)
        elif val == base[key]:
            keys_to_remove.append(key)
    for key in keys_to_remove:
        path = f"{prefix}.{key}" if prefix else str(key)
        paths.add(path)
        del override[key]
    return paths


def _indent(line):
    return len(line) - len(line.lstrip(' '))


def filter_lines(lines, removed_paths):
    out = []
    stack = []  # (indent, key_name, skip_this_subtree)

    for line in lines:
        stripped = line.rstrip('\n\r')
        indent = _indent(stripped)
        content = stripped.lstrip(' ')

        # Blank/comment lines only affect the stack when inside a
        # skipped subtree so the next key doesn't inherit the skip.
        if not content or content.startswith('#'):
            if stack and stack[-1][2]:
                while stack and indent <= stack[-1][0]:
                    stack.pop()
            current_skip = stack[-1][2] if stack else False
            if not current_skip:
                out.append(stripped)
            continue

        while stack and indent <= stack[-1][0]:
            stack.pop()

        current_skip = stack[-1][2] if stack else False

        m = re.match(r'([\w./-]+):', content)

        if m and not current_skip:
            key = m.group(1)
            path = f"{stack[-1][1]}.{key}" if stack else key
            stack.append((indent, path, path in removed_paths))
            current_skip = stack[-1][2]

        if current_skip:
            continue

        out.append(stripped)

    return out


def main():
    if len(sys.argv) != 3:
        print('Usage: python yaml_dedup.py <base_file> <override_file>')
        sys.exit(1)

    yaml = YAML()
    try:
        with open(sys.argv[1]) as f:
            base = yaml.load(f) or {}
        with open(sys.argv[2]) as f:
            override = yaml.load(f) or {}
    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error parsing YAML: {e}")
        sys.exit(1)

    removed_paths = _collect_removed_paths(base, override)

    if not removed_paths:
        sys.exit(0)

    with open(sys.argv[2]) as f:
        lines = f.readlines()

    result = filter_lines(lines, removed_paths)

    with open(sys.argv[2], 'w') as f:
        f.write('\n'.join(result))
        if result:
            f.write('\n')


if __name__ == '__main__':
    main()
