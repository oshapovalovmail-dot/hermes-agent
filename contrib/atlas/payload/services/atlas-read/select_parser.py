"""Positive SQL subset: one SELECT over one native table, no extensibility.

QL input/output budgets are imposed by the caller outside this parser. YQL
requires a static row slice on every source. Unsupported SQL is a refusal, not
an unclassified execution. No regex-only effect classification.
"""
import json
import re


class SelectError(ValueError):
    pass


TOKEN = re.compile(r'''\s*(?:(?P<path>\[//[^\]\r\n]+\]|`//[^`\r\n]+`)|(?P<string>"(?:[^"\\\r\n]|\\["\\nrt])*"|'(?:[^'\\\r\n]|\\['\\nrt])*')|(?P<num>[0-9]+(?:\.[0-9]+)?)|(?P<word>[A-Za-z_][A-Za-z0-9_]*)|(?P<op><=|>=|!=|<>|[(),*+\-/=<>;]))''')
RESERVED = set('SELECT FROM WHERE GROUP BY ORDER ASC DESC LIMIT AS AND OR NOT IS NULL TRUE FALSE'.split())
AGGREGATES = {'COUNT', 'SUM', 'AVG', 'MIN', 'MAX'}


def parse_select(query, safe_source, safe_column, dialect='ql'):
    if type(query) is not str or len(query) > 16384:
        raise SelectError('length')
    tokens = []; pos = 0
    while pos < len(query.rstrip()):
        match = TOKEN.match(query, pos)
        if not match: raise SelectError('token')
        tokens.append((match.lastgroup, match.group(match.lastgroup)))
        pos = match.end()
        if len(tokens) > 1000: raise SelectError('tokens')
    i = 0
    def peek(word=None):
        if i >= len(tokens): return False
        return tokens[i][1].upper() == word if word else tokens[i][1]
    def take(word=None):
        nonlocal i
        if i >= len(tokens) or (word and not peek(word)): raise SelectError('expected ' + str(word))
        token = tokens[i]; i += 1; return token
    def identifier():
        kind, value = take()
        if kind != 'word' or value.upper() in RESERVED: raise SelectError('identifier')
        safe_column(value)
        return value
    def expression(depth=0):
        nonlocal i
        if depth > 12: raise SelectError('depth')
        if peek('-') or peek('+'): take()
        if peek('('):
            take(); expression(depth+1); take(')')
        else:
            kind, value = take()
            if kind == 'word':
                if value.upper() in ('NULL', 'TRUE', 'FALSE'): pass
                elif peek('('):
                    if value.upper() not in AGGREGATES: raise SelectError('function')
                    take('(')
                    if peek('*'):
                        if value.upper() != 'COUNT': raise SelectError('star')
                        take('*')
                    else: expression(depth+1)
                    take(')')
                else:
                    if value.upper() in RESERVED: raise SelectError('reserved')
                    safe_column(value)
            elif kind not in ('num', 'string'): raise SelectError('expression')
        while peek() in ('+', '-', '*', '/'):
            take(); expression(depth+1)
    def condition(depth=0):
        if depth > 12: raise SelectError('condition depth')
        if peek('NOT'): take()
        if peek('('): take(); condition(depth+1); take(')')
        else:
            expression()
            if peek('IS'):
                take();
                if peek('NOT'): take()
                take('NULL')
            elif peek() in ('=', '!=', '<>', '<', '<=', '>', '>='):
                take(); expression()
            else: raise SelectError('comparison')
        while peek('AND') or peek('OR'):
            take(); condition(depth+1)
    had_select = bool(peek('SELECT'))
    if had_select: take('SELECT')
    if peek('*'): take('*')
    else:
        while True:
            expression()
            if peek('AS'): take(); identifier()
            if not peek(','): break
            take(',')
    take('FROM')
    kind, source = take()
    if kind != 'path': raise SelectError('source')
    if dialect == 'ql':
        if not source.startswith('[//'): raise SelectError('QL path')
        safe_source(source[1:-1])
    elif dialect == 'yql':
        if not source.startswith('`//'): raise SelectError('YQL path')
        safe_source(source[1:-1], ranged=True)
    else: raise SelectError('dialect')
    if peek('WHERE'): take(); condition()
    if peek('GROUP'):
        take(); take('BY'); identifier()
        while peek(','): take(); identifier()
    if peek('ORDER'):
        take(); take('BY')
        while True:
            identifier()
            if peek('ASC') or peek('DESC'): take()
            if not peek(','): break
            take()
    take('LIMIT')
    kind, value = take()
    if kind != 'num' or not value.isdigit() or not 1 <= int(value) <= 100: raise SelectError('limit')
    limit = int(value)
    if peek(';'): take()
    if i != len(tokens): raise SelectError('tail')
    normalized = query.strip().rstrip(';').strip()
    if dialect == 'ql' and had_select: normalized = re.sub(r'^SELECT\s+', '', normalized, count=1, flags=re.I)
    if dialect == 'yql' and not had_select: raise SelectError('SELECT required')
    return normalized, limit
