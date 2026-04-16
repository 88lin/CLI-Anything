#!/usr/bin/env python3
"""Update registry-dates.json with last modified dates from harness directories."""
import json
import re
import subprocess
import urllib.request
from pathlib import Path
from datetime import datetime


def get_last_modified(harness_path):
    """Get the most recent git commit date for files in a harness directory."""
    try:
        result = subprocess.run(
            ['git', 'log', '-1', '--format=%ct', '--', str(harness_path)],
            capture_output=True,
            text=True,
            check=True
        )
        timestamp = int(result.stdout.strip())
        return datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d')
    except (subprocess.CalledProcessError, ValueError):
        return None


def get_github_repo_date(source_url):
    """Get the last push date from a GitHub repo via the API."""
    # Extract owner/repo from URL like https://github.com/owner/repo
    match = re.match(r'https://github\.com/([^/]+/[^/]+?)(?:\.git)?$', source_url)
    if not match:
        return None
    repo_slug = match.group(1)
    api_url = f'https://api.github.com/repos/{repo_slug}'
    try:
        req = urllib.request.Request(api_url, headers={'Accept': 'application/vnd.github.v3+json'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            pushed_at = data.get('pushed_at')  # e.g. "2026-04-13T08:00:00Z"
            if pushed_at:
                return pushed_at[:10]
    except Exception:
        pass
    return None


def get_pypi_date(install_cmd):
    """Get the last release date from PyPI for a simple pip package."""
    # Only works for plain "pip install <package>" commands (not git+ URLs)
    match = re.match(r'^pip install ([a-zA-Z0-9_-]+)$', install_cmd)
    if not match:
        return None
    package = match.group(1)
    api_url = f'https://pypi.org/pypi/{package}/json'
    try:
        with urllib.request.urlopen(api_url, timeout=10) as resp:
            data = json.loads(resp.read())
            # Get the upload time of the latest version
            latest = data.get('info', {}).get('version')
            releases = data.get('releases', {})
            if latest and releases.get(latest):
                upload_time = releases[latest][0].get('upload_time')  # e.g. "2026-04-10T12:00:00"
                if upload_time:
                    return upload_time[:10]
    except Exception:
        pass
    return None


def get_external_date(cli):
    """Get the last update date for an external CLI, trying GitHub API then PyPI."""
    source_url = cli.get('source_url')
    if source_url:
        date = get_github_repo_date(source_url)
        if date:
            return date
    # Fallback to PyPI
    return get_pypi_date(cli.get('install_cmd', ''))


def main():
    repo_root = Path(__file__).parent.parent.parent
    registry_path = repo_root / 'registry.json'
    dates_path = repo_root / 'docs' / 'hub' / 'registry-dates.json'

    with open(registry_path) as f:
        data = json.load(f)

    dates = {}
    for cli in data['clis']:
        if cli.get('source_url'):
            # External repo: query GitHub API / PyPI for real update date
            dates[cli['name']] = get_external_date(cli)
        else:
            # In-repo: use the last commit in the harness directory
            harness_path = repo_root / cli['name'] / 'agent-harness'
            if harness_path.exists():
                dates[cli['name']] = get_last_modified(harness_path)

    with open(dates_path, 'w') as f:
        json.dump(dates, f, indent=2)

    print(f"Updated dates for {len(dates)} CLI entries")

if __name__ == '__main__':
    main()
