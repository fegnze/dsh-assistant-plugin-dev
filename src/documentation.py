"""Structural bilingual README gates; translation quality requires human review."""
import json
import re
from processes import ProcessAdapter
subprocess = ProcessAdapter()

README_FILES = ('README.md', 'docs/zh.md')
README_LINKS = ('docs/zh.md', '../README.md')
REVIEW = ('Human review required: README.md is the English GitHub/npm default; '
          'docs/zh.md is the full canonical Chinese alternative. Keep features, '
          'installation, configuration, limitations and examples accurate and matching. '
          'Structural checks do not verify language or translation completeness.')


def competing_readmes(names):
    """npm searches case-insensitive root README and README.* candidates."""
    return sorted(name for name in names if '/' not in name and name != 'README.md'
                  and (name.lower() == 'readme' or name.lower().startswith('readme.')))


def issues(path):
    result = [f'Competing root README candidate: {name}'
              for name in competing_readmes(entry.name for entry in path.iterdir())]
    try:
        manifest = json.loads((path / 'package.json').read_text(encoding='utf-8'))
    except (OSError, UnicodeError, ValueError):
        result.append('Missing or unreadable package.json for README metadata audit')
    else:
        if not isinstance(manifest, dict):
            result.append('package.json must be an object for README metadata audit')
        else:
            for field in ('readme', 'readmeFilename'):
                if field in manifest:
                    result.append(f'Remove stale package.json README metadata: {field}')
    for name, other in zip(README_FILES, README_LINKS):
        try:
            text = (path / name).read_text(encoding='utf-8')
        except (OSError, UnicodeError):
            result.append(f'Missing or unreadable bilingual documentation: {name}')
            continue
        if not text.strip():
            result.append(f'Empty bilingual documentation: {name}')
        # The documented convention is an inline relative Markdown link in the
        # first ten physical lines, not a mention or a code/comment example.
        top = '\n'.join(text.splitlines()[:10])
        top = re.sub(r'<!--.*?(?:-->|\Z)', '', top, flags=re.S)
        top = re.sub(r'(?m)^\s*(`{3,}|~{3,}).*?\Z', '', top, flags=re.S)
        link = rf'(?<!!)\[[^\]\n]+\]\(\s*<?(?:\./)?{re.escape(other)}>?(?:\s+["\'][^\n]*["\'])?\s*\)'
        if not re.search(link, top):
            result.append(f'{name} must link to {other} in its first 10 lines')
    return result


def require(path, packed_files=None):
    problems = issues(path)
    if packed_files is not None:
        problems.extend(f'npm payload missing {name}' for name in README_FILES if name not in packed_files)
        problems.extend(f'npm payload has competing root README candidate: {name}'
                        for name in competing_readmes(packed_files))
    if problems:
        raise ValueError('; '.join(problems))
    return {'files': list(README_FILES), 'review': REVIEW}


def audit_pack(path):
    """Check the actual npm inventory, not package.json allowlist guesses."""
    require(path)
    result = subprocess.run(['npm', 'pack', '--dry-run', '--json', '--ignore-scripts'],
                            cwd=path, capture_output=True, timeout=60)
    if result.returncode:
        raise ValueError('Documentation package audit failed')
    files = json.loads(result.stdout)[0]['files']
    require(path, {row['path'] for row in files})
    return files
