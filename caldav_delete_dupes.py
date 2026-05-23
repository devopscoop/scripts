#!/usr/bin/env python3
"""Scan a CalDAV calendar for duplicate events and report them."""

import argparse
import os
import re
from collections import defaultdict
from datetime import datetime

import caldav


def parse_args():
    parser = argparse.ArgumentParser(
        description='Scan a CalDAV calendar for duplicate events'
    )
    parser.add_argument('--url', help='CalDAV server URL')
    parser.add_argument('--username', help='CalDAV username')
    parser.add_argument('--password', help='CalDAV password')
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


def get_creds(args):
    return {
        'url': args.url or os.environ.get('CALDAV_URL'),
        'username': args.username or os.environ.get('CALDAV_USERNAME'),
        'password': args.password or os.environ.get('CALDAV_PASSWORD'),
    }


def _safe_val(vevent, name):
    """Return the string value of a vobject property or empty string."""
    try:
        return str(getattr(vevent, name).value)
    except (AttributeError, ValueError):
        return ''


def vevent_key_by_content(vevent):
    s = _safe_val(vevent, 'summary')
    dtstart = _safe_val(vevent, 'dtstart')
    dtend = _safe_val(vevent, 'dtend')
    return (s, dtstart, dtend)


def _candidate_principal_urls(base_url, username):
    """Return URL candidates to try for the CalDAV principal."""
    base = base_url.rstrip('/')
    yield base
    yield f"{base}/principals/users/{username}/"
    yield f"{base}/principals/__uids__/{username}/"

    # Nextcloud / ownCloud
    for prefix in ('', '/remote.php/dav', '/remote.php'):
        yield f"{base}{prefix}/principals/users/{username}/"
        yield f"{base}{prefix}/principals/__uids__/{username}/"


def connect(creds):
    """Try candidate principal URLs and return (client, principal)."""
    username = creds['username']
    base = creds['url']

    for url in _candidate_principal_urls(base, username):
        try:
            client = caldav.DAVClient(
                url=url,
                username=creds['username'],
                password=creds['password'],
            )
            principal = caldav.Principal(client)
            print(f"Connected via: {url}")
            return client, principal
        except caldav.lib.error.DAVError:
            continue

    msg = (
        'Could not connect. Try setting CALDAV_URL to a full principal URL, e.g.\n'
        '  https://nextcloud.example.com/remote.php/dav/principals/users/username/'
    )
    raise ConnectionError(msg)


def main():
    args = parse_args()
    creds = get_creds(args)

    missing = [k for k, v in creds.items() if not v]
    if missing:
        print(
            f"Missing required config: {', '.join(missing)}. "
            'Provide via --flags or CALDAV_URL / CALDAV_USERNAME / CALDAV_PASSWORD env vars.'
        )
        return 1

    client, principal = connect(creds)
    calendars = principal.calendars()

    if not calendars:
        print('No calendars found.')
        return 1

    if args.calendar:
        cal = next((c for c in calendars if c.get_display_name() == args.calendar), None)
        if not cal:
            names = [c.get_display_name() for c in calendars]
            print(f"Calendar '{args.calendar}' not found. Available: {names}")
            return 1
    elif len(calendars) == 1:
        cal = calendars[0]
        print(f"Using calendar: {cal.get_display_name()}")
    else:
        print('Available calendars:')
        for i, c in enumerate(calendars, 1):
            print(f"  {i}. {c.get_display_name() or c.name}")
        while True:
            try:
                choice = input('Select calendar (number): ').strip()
                idx = int(choice) - 1
                if 0 <= idx < len(calendars):
                    cal = calendars[idx]
                    break
                print(f"Enter a number between 1 and {len(calendars)}.")
            except (ValueError, EOFError):
                print('Invalid input.')

    print('Fetching events ...')
    events = cal.events()
    print(f"Found {len(events)} event(s).\n")

    cal_name = cal.get_display_name() or 'calendar'
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_path = os.path.join(args.backup_dir, f"{cal_name}_{ts}.ics")
    print(f"Backing up to {backup_path} ...")
    vevent_re = re.compile(r'BEGIN:VEVENT.+?END:VEVENT', re.DOTALL | re.IGNORECASE)
    with open(backup_path, 'w') as f:
        f.write('BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//caldav_dupes//EN\r\n')
        for ev in events:
            match = vevent_re.search(ev.data)
            if match:
                f.write(match.group() + '\r\n')
        f.write('END:VCALENDAR\r\n')
    print()

    uid_map = defaultdict(list)
    content_map = defaultdict(list)

    for ev in events:
        vevent = ev.vobject_instance.vevent
        uid = _safe_val(vevent, 'uid')
        uid_map[uid].append(ev)

        if uid:
            k = vevent_key_by_content(vevent)
            content_map[k].append(ev)

    found_any = False
    to_delete = []  # events to remove (keep one per group)

    # 1. Duplicates by UID
    dupes_by_uid = [(uid, evs) for uid, evs in uid_map.items() if len(evs) > 1]
    if dupes_by_uid:
        found_any = True
        print('=== Duplicates by UID ===')
        for uid, evs in dupes_by_uid:
            print(f"\nUID: {uid}  ({len(evs)} occurrences)")
            for ev in evs:
                vevent = ev.vobject_instance.vevent
                print(
                    f"  {_safe_val(vevent, 'summary') or '(no summary)'}  "
                    f"({_safe_val(vevent, 'dtstart') or '?'} -> {_safe_val(vevent, 'dtend') or '?'})"
                )
            to_delete.extend(evs[1:])  # keep first

    # 2. Duplicates by content
    dupes_by_content = [
        (k, evs) for k, evs in content_map.items() if len(evs) > 1
    ]
    if dupes_by_content:
        found_any = True
        print('\n=== Duplicates by content (different UID, same summary+start+end) ===')
        for k, evs in dupes_by_content:
            print(f"\n  {k[0] or '(no summary)'}")
            print(f"  {k[1]} -> {k[2]}")
            print(f"  ({len(evs)} occurrences)")
            for ev in evs:
                uid = _safe_val(ev.vobject_instance.vevent, 'uid')
                print(f"    UID: {uid}")
            # Don't re-add content-based dupes if already in to_delete via UID
            keep = evs[0]
            for ev in evs[1:]:
                if ev not in to_delete:
                    to_delete.append(ev)

    if not found_any:
        print('No duplicate events found.')
        return 0

    print(f"\nTotal: {len(dupes_by_uid)} UID-based + {len(dupes_by_content)} content-based duplicate group(s).")
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

    return 1 if to_delete else 0


if __name__ == '__main__':
    raise SystemExit(main())
