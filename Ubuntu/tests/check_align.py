#!/usr/bin/env python3
"""Assert every rendered box is a perfect rectangle.

Reads a captured terminal transcript on stdin, strips ANSI, and checks that
each run of box-drawing lines has one consistent display width -- measured in
COLUMNS (unicodedata east-asian width), not bytes and not code points, since
the layout is padded on printed width.
"""
import re
import sys
import unicodedata

ANSI = re.compile(r'\x1B\[[0-9;?]*[a-zA-Z]|\x1B[78=>]|\x1B[()#][A-Za-z0-9]')
EDGE = ('│', '╭', '╰', '├')


def width(s):
    return sum(2 if unicodedata.east_asian_width(c) in 'WF' else 1 for c in s)


text = sys.stdin.buffer.read().decode('utf-8', 'replace').replace('\r', '')
lines = [ANSI.sub('', ln) for ln in text.split('\n')]

boxes, cur = [], []
for ln in lines:
    if ln.startswith(EDGE):
        cur.append(ln)
    elif cur:
        boxes.append(cur)
        cur = []
if cur:
    boxes.append(cur)

if not boxes:
    print('NO BOXES FOUND -- nothing to check')
    sys.exit(1)

bad = 0
for i, box in enumerate(boxes, 1):
    widths = {width(ln) for ln in box}
    if len(widths) == 1:
        print(f'  ok   box {i}: {len(box)} lines, all {widths.pop()} cols')
    else:
        bad += 1
        print(f'  FAIL box {i}: ragged widths {sorted(widths)}')
        for ln in box:
            print(f'        {width(ln):>4}  {ln[:70]}')

# Every box must also be closed: same count of top and bottom corners.
for i, box in enumerate(boxes, 1):
    if not box[0].startswith('╭') or not box[-1].startswith('╰'):
        bad += 1
        print(f'  FAIL box {i}: not closed ({box[0][:3]!r} .. {box[-1][:3]!r})')

print(f'\n{len(boxes)} boxes checked, {bad} bad')
sys.exit(1 if bad else 0)
