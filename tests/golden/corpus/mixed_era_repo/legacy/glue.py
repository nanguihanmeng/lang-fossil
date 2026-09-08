"""Mixed-era module: py2 idioms inside an otherwise modern tree."""

import asyncore


def old_style():
    d = {}
    if d.has_key('x'):
        for i in xrange(3):
            print i
    return ur'mixed era string'
