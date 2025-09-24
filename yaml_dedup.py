#!/usr/bin/env python3
"""
Simple script to remove duplicate entries from second YAML file that exist in first YAML file.
Usage: python yaml_dedup.py file1.yaml file2.yaml
"""

import yaml
import sys

def deep_diff_remove(base_dict, override_dict):
    """Remove entries from override_dict that have identical values in base_dict."""
    result = {}

    for key, override_value in override_dict.items():
        if key not in base_dict:
            # Key doesn't exist in base, keep it
            result[key] = override_value
        elif isinstance(override_value, dict) and isinstance(base_dict[key], dict):
            # Both are dictionaries, recursively check
            nested_diff = deep_diff_remove(base_dict[key], override_value)
            if nested_diff:  # Only include if there are differences
                result[key] = nested_diff
        elif override_value != base_dict[key]:
            # Values are different, keep the override
            result[key] = override_value
        # If values are identical, don't include in result (remove duplicate)

    return result

def main():
    if len(sys.argv) != 3:
        print('Usage: python yaml_dedup.py <base_file> <override_file>')
        print('Example: python yaml_dedup.py file1.yaml file2.yaml')
        sys.exit(1)

    base_file = sys.argv[1]
    override_file = sys.argv[2]

    # Load YAML files
    try:
        with open(base_file, 'r') as f:
            base_data = yaml.safe_load(f) or {}

        with open(override_file, 'r') as f:
            override_data = yaml.safe_load(f) or {}
    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)
    except yaml.YAMLError as e:
        print(f"Error parsing YAML: {e}")
        sys.exit(1)

    # Remove duplicates
    unique_data = deep_diff_remove(base_data, override_data)

    # Save deduplicated file
    with open(override_file, 'w') as f:
        yaml.dump(unique_data, f, default_flow_style=False, sort_keys=True, indent=2)

    print(f"  Removed {len(override_data) - len(unique_data)} duplicate top-level entries")

if __name__ == '__main__':
    main()
