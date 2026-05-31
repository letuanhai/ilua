#!/bin/env python
"""
Downloads Lua manual source files from GitHub (lua/lua) and converts
the @LibEntry blocks in manual.of to a JSON docs dictionary.

Usage:
    python manualparser.py > docs.json

The JSON output maps function names (e.g. "io.read", "assert") to
{signature, documentation} dicts.  Pipe through the Lua one-liner in
builtins.lua to regenerate the builtins table:

    python manualparser.py | \\
      lua -e 'local j=require"ext.json" local d=j.decode(io.read"*a")
              for k,v in pairs(d) do
                io.write(("  [%q]={signature=%q,documentation=%q},\\n")
                  :format(k,v.signature,v.documentation)) end'
"""
from __future__ import print_function
import re
import sys
import json
import subprocess
import tempfile
import os
import shutil

# Lua versions to pull docs from (latest patch tag for each minor version)
LUA_VERSIONS = [
    # 5.1 and 5.2 pre-date the manual.of format; their docs are covered by 5.3+
    ("5.3", "v5.3.6"),
    ("5.4", "v5.4.8"),
    ("5.5", "v5.5.0"),
]

LUA_REPO = "https://github.com/lua/lua.git"

# Markup substitutions: convert @tag{...} to plain text
_MARKUP = [
    # inline literals / identifiers
    (re.compile(r'@(?:id|St|Cdots|nil|false|true|N|T|idx|Lid|def|see)\{([^}]*)\}'), r'\1'),
    # cross-refs and other wrappers we just want the inner text of
    (re.compile(r'@\w+\{([^}]*)\}'), r'\1'),
    # bare macros with no braces
    (re.compile(r'@Cdots\b'), '...'),
    (re.compile(r'@nil\b'), 'nil'),
    (re.compile(r'@false\b'), 'false'),
    (re.compile(r'@true\b'), 'true'),
]

def clean_markup(text):
    """Strip manual.of markup tags, leaving plain text."""
    for pattern, replacement in _MARKUP:
        text = pattern.sub(replacement, text)
    # collapse multiple blank lines
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

def extract_libentries(source):
    """
    Yield (signature, doc_body) tuples by tracking brace depth.
    @LibEntry{sig| body } — the closing } is at depth 0 after the opening {.
    """
    i = 0
    marker = '@LibEntry{'
    while True:
        pos = source.find(marker, i)
        if pos == -1:
            break
        # Find the | that separates signature from body
        pipe = source.find('|', pos + len(marker))
        if pipe == -1:
            break
        sig = source[pos + len(marker):pipe]
        # Walk from pipe+1 counting brace depth (already depth 1 from @LibEntry{)
        depth = 1
        j = pipe + 1
        while j < len(source) and depth > 0:
            if source[j] == '{':
                depth += 1
            elif source[j] == '}':
                depth -= 1
            j += 1
        body = source[pipe + 1:j - 1]  # content before the matching }
        yield sig, body
        i = j

def parse_manual_of(source):
    """
    Parse a manual.of file and return {func_name: {signature, documentation}}.
    Handles @LibEntry{signature| ... } blocks.
    """
    result = {}
    for raw_sig, raw_doc in extract_libentries(source):
        raw_sig = raw_sig.strip()
        raw_doc = raw_doc.strip()

        name_match = re.match(r'^([\w.:]+)', raw_sig)
        if not name_match:
            continue
        func_name = name_match.group(1)

        proto = raw_sig[len(func_name):]
        signature = func_name + clean_markup(proto)
        documentation = clean_markup(raw_doc)

        result[func_name] = {
            'signature': signature,
            'documentation': documentation,
        }
    return result

def fetch_manual_of(tag):
    """Clone the lua/lua repo at the given tag and return the manual.of text."""
    tmpdir = tempfile.mkdtemp(prefix='ilua_lua_')
    try:
        subprocess.check_call(
            ['git', 'clone', '--depth', '1', '--branch', tag,
             '--no-checkout', LUA_REPO, tmpdir],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        subprocess.check_call(
            ['git', 'checkout', 'HEAD', '--', 'manual/'],
            cwd=tmpdir,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        manual_path = os.path.join(tmpdir, 'manual', 'manual.of')
        with open(manual_path, 'r', encoding='utf-8') as f:
            return f.read()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

def main():
    docs_dict = {}
    for version, tag in LUA_VERSIONS:
        print(f"Fetching Lua {version} ({tag})...", file=sys.stderr)
        try:
            source = fetch_manual_of(tag)
            entries = parse_manual_of(source)
            print(f"  -> {len(entries)} entries", file=sys.stderr)
            docs_dict.update(entries)
        except Exception as e:
            print(f"  ERROR: {e}", file=sys.stderr)

    json.dump(docs_dict, sys.stdout, indent=4)
    print(file=sys.stdout)

if __name__ == '__main__':
    main()
