#!/usr/bin/env python3
"""Scan a CalDAV calendar for duplicate events and report them."""

import argparse
import os
import sys
from collections import defaultdict
from datetime import datetime
from typing import Any, Optional

import caldav


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Scan a CalDAV calendar for duplicate events'
    )
    parser.add_argument('--url', help='CalDAV server URL')
    parser.add_argument('--username', help='CalDAV username')
    parser.add_argument('--password', help='CalDAV password (mutually exclusive with --password-file)')
    parser.add_argument('--password-file', help='Read CalDAV password from file')
    parser.add_argument('--calendar', help='Calendar name (skip interactive pick)')
    parser.add_argument(
        '--backup-dir',
        default='.',
        help='Directory to write backup .ics files (default: .)',
    )
    parser.add_argument(
        '--yes', action='store_true', help='Delete duplicates without prompting'
    )
    return parser.parse_args()


def _read_password(args: argparse.Namespace) -> Optional[str]:
    if args.password_file:
        try:
            with open(args.password_file) as f:
                return f.readline().rstrip('\n\r')
        except OSError as e:
            print(f"Error reading password file: {e}", file=sys.stderr)
            return None
    if args.password:
        return args.password
    return os.environ.get('CALDAV_PASSWORD')


def get_creds(args: argparse.Namespace) -> dict[str, Optional[str]]:
    return {
        'url': args.url or os.environ.get('CALDAV_URL'),
        'username': args.username or os.environ.get('CALDAV_USERNAME'),
        'password': _read_password(args),
    }


def _safe_val(vevent: Any, name: str) -> str:
    """Return the string value of a vobject property or empty string."""
    try:
        return str(getattr(vevent, name).value)
    except (AttributeError, ValueError):
        return ''


def vevent_key_by_content(vevent: Any) -> tuple[str, str, str]:
    s = _safe_val(vevent, 'summary')
    dtstart = _safe_val(vevent, 'dtstart')
    dtend = _safe_val(vevent, 'dtend')
    return (s, dtstart, dtend)


def _candidate_principal_urls(base_url: str, username: str):
    """Return URL candidates to try for the CalDAV principal."""
    base = base_url.rstrip('/')

    yield base  # try user-supplied URL as-is (full principal URL)

    # Nextcloud / ownCloud servers — try various path prefixes
    for prefix in ('/remote.php/dav', '/remote.php', ''):
        yield f"{base}{prefix}/principals/users/{username}/"
        yield f"{base}{prefix}/principals/__uids__/{username}/"


def connect(creds: dict[str, Optional[str]]) -> tuple[caldav.DAVClient, caldav.Principal]:
    """Try candidate principal URLs and return (client, principal)."""
    username = creds['username']
    base = creds['url']
    print(f"Discovering CalDAV principal URL for user '{username}' ...")

    for url in _candidate_principal_urls(base, username):
        try:
            client = caldav.DAVClient(
                url=url,
                username=creds['username'],
                password=creds['password'],
            )
            principal = caldav.Principal(client)
            print(f"✓ Connected via: {url}")
            return client, principal
        except caldav.lib.error.DAVError:
            print(f"  ✗ {url}")

    msg = (
        'Could not connect. Try setting CALDAV_URL to a full principal URL, e.g.\n'
        '  https://nextcloud.example.com/remote.php/dav/principals/users/username/'
    )
    raise ConnectionError(msg)


def validate_creds(creds: dict[str, Optional[str]]) -> bool:
    missing = [k for k, v in creds.items() if not v]
    if missing:
        print(
            f"Missing required config: {', '.join(missing)}. "
            'Provide via --flags or CALDAV_URL / CALDAV_USERNAME / CALDAV_PASSWORD env vars.'
        )
        return False
    return True


def select_calendar(calendars: list[caldav.Calendar], calendar_name: Optional[str]) -> Optional[caldav.Calendar]:
    if calendar_name:
        cal = next((c for c in calendars if c.get_display_name() == calendar_name), None)
        if not cal:
            names = [c.get_display_name() for c in calendars]
            print(f"Calendar '{calendar_name}' not found. Available: {names}")
            return None
        return cal
    if len(calendars) == 1:
        cal = calendars[0]
        print(f"Using calendar: {cal.get_display_name()}")
        return cal
    print('Available calendars:')
    for i, c in enumerate(calendars, 1):
        print(f"  {i}. {c.get_display_name() or c.name}")
    while True:
        try:
            choice = input('Select calendar (number): ').strip()
            idx = int(choice) - 1
            if 0 <= idx < len(calendars):
                return calendars[idx]
            print(f"Enter a number between 1 and {len(calendars)}.")
        except (ValueError, EOFError):
            print('Invalid input.')
        except KeyboardInterrupt:
            print()
            return None


def backup_events(events: list[caldav.Event], backup_dir: str, cal_name: str) -> str:
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_path = os.path.join(backup_dir, f"{cal_name}_{ts}.ics")
    print(f"Backing up to {backup_path} ...")
    with open(backup_path, 'w') as f:
        for ev in events:
            f.write(ev.data + '\r\n')
    print()
    return backup_path


def find_duplicates(events: list[caldav.Event]) -> tuple[bool, list[tuple[str, list[caldav.Event]]], list[tuple[tuple[str, str, str], list[caldav.Event]]], list[caldav.Event]]:
    uid_map: dict[str, list[caldav.Event]] = defaultdict(list)
    content_map: dict[tuple[str, str, str], list[caldav.Event]] = defaultdict(list)

    for ev in events:
        vevent = ev.vobject_instance.vevent
        uid = _safe_val(vevent, 'uid')
        uid_map[uid].append(ev)

        if uid:
            k = vevent_key_by_content(vevent)
            content_map[k].append(ev)

    to_delete: list[caldav.Event] = []
    to_delete_set: set[caldav.Event] = set()

    # 1. Duplicates by UID
    dupes_by_uid = [(uid, evs) for uid, evs in uid_map.items() if len(evs) > 1]
    if dupes_by_uid:
        print('=== Duplicates by UID ===')
        for uid, evs in dupes_by_uid:
            print(f"\nUID: {uid}  ({len(evs)} occurrences)")
            for ev in evs:
                vevent = ev.vobject_instance.vevent
                print(
                    f"  {_safe_val(vevent, 'summary') or '(no summary)'}  "
                    f"({_safe_val(vevent, 'dtstart') or '?'} -> {_safe_val(vevent, 'dtend') or '?'})"
                )
            for ev in evs[1:]:
                to_delete.append(ev)
                to_delete_set.add(ev)

    # 2. Duplicates by content
    dupes_by_content = [
        (k, evs) for k, evs in content_map.items() if len(evs) > 1
    ]
    if dupes_by_content:
        print('\n=== Duplicates by content (different UID, same summary+start+end) ===')
        for k, evs in dupes_by_content:
            print(f"\n  {k[0] or '(no summary)'}")
            print(f"  {k[1]} -> {k[2]}")
            print(f"  ({len(evs)} occurrences)")
            for ev in evs:
                uid = _safe_val(ev.vobject_instance.vevent, 'uid')
                print(f"    UID: {uid}")
            for ev in evs[1:]:
                if ev not in to_delete_set:
                    to_delete.append(ev)
                    to_delete_set.add(ev)

    found_any = bool(dupes_by_uid or dupes_by_content)
    return found_any, dupes_by_uid, dupes_by_content, to_delete


def confirm_and_delete(to_delete: list[caldav.Event], num_uid_groups: int, num_content_groups: int, args: argparse.Namespace) -> int:
    if not to_delete:
        return 0

    print(f"\nTotal: {num_uid_groups} UID-based + {num_content_groups} content-based duplicate group(s).")
    print(f"Events to delete (keep one per group): {len(to_delete)}")

    if args.yes:
        reply = 'y'
    else:
        reply = input('\nDelete these duplicates? [y/N] ').strip().lower()

    if reply == 'y':
        print('Deleting ...')
        for i, ev in enumerate(to_delete, 1):
            ev.delete()
            print(f"  [{i}/{len(to_delete)}] deleted")
        print('Done.')
    else:
        print('Skipped deletion.')

    return 0


def main() -> int:
    args = parse_args()
    creds = get_creds(args)

    if not validate_creds(creds):
        return 1

    if args.backup_dir and not os.path.isdir(args.backup_dir):
        print(f"Backup directory does not exist: {args.backup_dir}")
        return 1

    client, principal = connect(creds)
    calendars = principal.calendars()

    if not calendars:
        print('No calendars found.')
        return 1

    cal = select_calendar(calendars, args.calendar)
    if not cal:
        return 1

    print('Fetching events ...')
    events = cal.events()
    print(f"Found {len(events)} event(s).\n")

    cal_name = cal.get_display_name() or 'calendar'
    backup_events(events, args.backup_dir, cal_name)

    found_any, dupes_by_uid, dupes_by_content, to_delete = find_duplicates(events)

    if not found_any:
        print('No duplicate events found.')
        return 0

    confirm_and_delete(to_delete, len(dupes_by_uid), len(dupes_by_content), args)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
