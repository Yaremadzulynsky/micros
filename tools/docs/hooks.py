"""Keep repository links useful when Markdown is rendered outside GitHub."""
from pathlib import Path
from html import escape
from html.parser import HTMLParser
import json
import re
import subprocess
from urllib.parse import quote, unquote, urljoin, urlsplit

ROOT = Path(__file__).resolve().parents[2]
LINK = re.compile(r'(?P<prefix>\]\()(?P<url>[^\s)]+)(?P<suffix>\))')


def check_entry_points(root=ROOT):
    """Check maintained repository guides without rewriting historical evidence."""
    names = subprocess.check_output(
        ['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z', '--', '*.md'],
        cwd=root, text=True).split('\0')
    for name in sorted(set(names)):
        path = root / name
        if (path.name not in ('README.md', 'AGENTS.md', 'CONTRIBUTING.md', 'SKILL.md')
                or any(part in ('archive', 'third_party', 'vendor') for part in Path(name).parts)
                or not path.is_file()):
            continue
        check_local_links(path, root)


def check_local_links(path, root):
    # Example links in fenced code are data, not navigation.
    chunks = re.split(r'(^```[^\n]*\n.*?^```\s*$)', path.read_text(), flags=re.M | re.S)
    for chunk in chunks[::2]:
        for match in LINK.finditer(chunk):
            parsed = urlsplit(match['url'])
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            base = root if parsed.path.startswith('/') else path.parent
            target = (base / unquote(parsed.path).lstrip('/')).resolve()
            # Generated applications create this SDK link at scaffold time.
            template_sdk = (root / 'tools/templates/application/.sdk').resolve()
            if path.is_relative_to(root / 'tools/templates/application') and target.is_relative_to(template_sdk):
                target = (root / target.relative_to(template_sdk)).resolve()
            try:
                target.relative_to(root.resolve())
            except ValueError:
                raise ValueError(f'Link leaves the repository: {path.relative_to(root)}: {match["url"]}')
            if not target.exists():
                raise ValueError(f'Missing repository link: {path.relative_to(root)}: {match["url"]}')


def on_pre_build(config):
    check_entry_points()


def on_page_markdown(markdown, page, config, files):
    published = {Path(f.abs_src_path).resolve() for f in files if f.abs_src_path and f.inclusion.is_included()}
    def rewrite(match):
        url = match['url']
        parsed = urlsplit(url)
        if parsed.scheme or parsed.netloc or not parsed.path or parsed.path.startswith('/'):
            return match[0]
        target = (Path(page.file.abs_src_path).parent / unquote(parsed.path)).resolve()
        if target in published:
            return match[0]
        # Implementation sources are read on GitHub, not copied into the site.
        try:
            relative = target.relative_to(ROOT)
        except ValueError:
            raise ValueError(f'Link leaves the repository: {page.file.src_uri}: {url}')
        if not target.exists():
            raise ValueError(f'Missing repository link: {page.file.src_uri}: {url}')
        ref = config['edit_uri'].split('/')[1]
        kind = 'tree' if target.is_dir() else 'blob'
        destination = f"{config['repo_url']}/{kind}/{ref}/{quote(relative.as_posix())}"
        if parsed.fragment:
            destination += '#' + parsed.fragment
        return match['prefix'] + destination + match['suffix']
    # Leave code examples untouched.
    chunks = re.split(r'(^```[^\n]*\n.*?^```\s*$)', markdown, flags=re.M | re.S)
    return ''.join(chunk if i % 2 else LINK.sub(rewrite, chunk) for i, chunk in enumerate(chunks))


class PublishedLinkCheck(HTMLParser):
    """Reject archive exits, including raw HTML and repository URLs."""

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if name in ('href', 'src') and value:
                parts = unquote(urlsplit(value).path).split('/')
                if 'archive' in parts:
                    raise ValueError(f'Published documentation links to the archive: {value}')


def on_post_page(output, page, config):
    """Check the reading path and preserve the moved introduction's bookmarks."""
    try:
        PublishedLinkCheck().feed(output)
    except ValueError as error:
        raise ValueError(f'{page.file.src_uri}: {error}') from error
    destination = page.meta.get('redirect_to')
    if not destination:
        return output
    canonical = urljoin(page.canonical_url, destination)
    target = escape(destination, quote=True)
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(page.title)}</title>
<link rel="canonical" href="{escape(canonical, quote=True)}">
<script>location.replace({json.dumps(destination)} + location.search + location.hash);</script>
<noscript><meta http-equiv="refresh" content="0; url={target}"></noscript>
</head><body><p>This page has moved.
<a href="{target}">Continue to the documentation</a>.</p></body></html>'''
