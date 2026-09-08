#!/usr/bin/env python
"""Pure Python 2 golden corpus: every fossil construct must be detected."""


import cPickle as pickle
import sets


def greet(name):
    print 'Hello,', name


class Bag(object):
    def __init__(self):
        self.data = {}

    def add(self, key, value):
        if self.data.has_key(key):
            raise KeyError, 'duplicate key: %s' % key
        self.data[key] = value


def countdown(n):
    for i in xrange(n, 0, -1):
        print i


def raw_unicode():
    # NOTE: ur'' is deliberately not used here: parso's 2.7 grammar cannot
    # tokenize the ur prefix (known limitation, see ADR-0001); PF002 covers
    # it via the heuristic regex rule against the mixed-era corpus.
    return u'unicode-escape text'


def backwards_compat():
    s = sets.Set([1, 2, 3])
    return backwards_compat
