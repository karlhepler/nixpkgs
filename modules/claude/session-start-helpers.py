"""
Helper functions for the claude-session-start-hook.

Each function is invoked as a subcommand:
  python3 session-start-helpers.py <function_name> [args...]
"""
import json
import re
import sys
import xml.etree.ElementTree as ET


def extract_kanban_name():
    """Read kanban session-hook output from stdin and print the session name."""
    text = sys.stdin.read()
    m = re.search(r'Your kanban session is: ([a-z0-9-]+)', text)
    print(m.group(1) if m else '')


def extract_session_uuid():
    """Read JSON from stdin and print the session_id field."""
    data = json.loads(sys.stdin.read())
    print(data.get('session_id', ''))


def find_orphaned_cards():
    """Read kanban XML from stdin and print a warning for orphaned cards."""
    xml_text = sys.stdin.read()
    if not xml_text.strip():
        sys.exit(0)
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        sys.exit(0)

    orphans = []
    board_session = root.get('session', 'unknown')
    for group in root:
        group_session = board_session if group.tag == 'mine' else None
        for card in group.iter('c'):
            status = card.get('s', '')
            if status not in ('doing', 'review'):
                continue
            num = card.get('n', '?')
            session = card.get('ses', group_session) if group_session is None else group_session
            action_el = card.find('a')
            action = (action_el.text or '').strip() if action_el is not None else ''
            truncated = action[:50] + '...' if len(action) > 50 else action
            orphans.append((num, status, session, truncated))

    if orphans:
        print('Warning: Orphaned cards detected:')
        for num, status, session, action in orphans:
            print(f'  - #{num} ({status}, session: {session}) -- {action}')
        print('Use kanban cancel or kanban redo to resolve.')


def to_result_json():
    """Read text from stdin and wrap it in a Claude hook result JSON envelope."""
    content = sys.stdin.read()
    print(json.dumps({'result': content}))


COMMANDS = {
    'extract_kanban_name': extract_kanban_name,
    'extract_session_uuid': extract_session_uuid,
    'find_orphaned_cards': find_orphaned_cards,
    'to_result_json': to_result_json,
}

if __name__ == '__main__':
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(f"Usage: {sys.argv[0]} <command>", file=sys.stderr)
        print(f"Commands: {', '.join(COMMANDS)}", file=sys.stderr)
        sys.exit(1)
    COMMANDS[sys.argv[1]]()
