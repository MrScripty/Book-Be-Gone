"""Conservative printed-page reference detection, without rewriting Markdown layout."""
import re

NUMBER = r'(?:[0-9]+|[ivxlcdmIVXLCDM]+)'
LOCATOR = NUMBER + r'(?:\s*[–—-]\s*' + NUMBER + r')?'
LOCATORS = LOCATOR + r'(?:\s*(?:,|\band\b|&)\s*' + LOCATOR + r')*'
FILE = re.compile(r'page-[a-z0-9-]+__[a-z0-9-]+__([0-9]{6})-([12])\.md')
LINK = re.compile(r'(?<!!)\[([^\]\n]+)\]\(([^\s()]+)\)')
# Protect authored links/images (including their labels), inline code, autolinks,
# reference links, and escaped characters before looking for printed references.
PROTECTED = re.compile(r'`+[^`\n]*`+|!?\[[^\]\n]*\]\([^\n]*?\)|!?\[[^\]\n]*\]\[[^\]\n]*\]|\[[^\]\n]*\]|<[^>\n]+>|\\.')
EXPLICIT = re.compile(r'\b(?:pages?|pp?\.)\s+(' + LOCATORS + r')(?![\w])', re.I)
INDEX = re.compile(r',\s*(' + LOCATORS + r')(?=\s*(?:[;().]|$|\*(?:see|See)))')
CONTENTS = re.compile(r'(' + LOCATOR + r')\s*\|?\s*$')
SECTION = re.compile(r'^(?:table of contents|contents|index)(?:\s*\(continued\))?$', re.I)


def number(value):
    value = value.strip()
    if value.isascii() and value.isdigit():
        return str(int(value))
    return value.lower()


def file_key(value):
    match = FILE.fullmatch(value.removeprefix('./'))
    return f'{match[1]}:{int(match[2]) - 1}' if match else None


def unique_targets(entries):
    groups = {}
    for key, page in entries:
        if page.get('page_number'):
            groups.setdefault(number(page['page_number']), []).append(page['filename'])
    return {key: names[0] for key, names in groups.items() if len(names) == 1}


def link_text(text, targets, filenames, chapter=None, detect=False):
    """Resolve OCR hints and existing filenames, optionally detecting old plain text.

    Unknown hints stay as page: links so a later capture can resolve them. Ordinary
    detected references stay plain when their target is missing or ambiguous.
    """
    section = chapter.strip().lower() if isinstance(chapter, str) else ''
    in_listing = bool(SECTION.fullmatch(section))
    is_index = section.startswith('index')
    fence = None
    result = []
    for line in text.splitlines(keepends=True):
        stripped = line.lstrip()
        marker = re.match(r'(`{3,}|~{3,})', stripped)
        if fence:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence) and not stripped[len(marker[1]):].strip():
                fence = None
            result.append(line); continue
        if marker:
            fence = marker[1]; result.append(line); continue
        if line.startswith(('    ', '\t')) or re.match(r'^\s*\[[^\]]+\]:', line):
            result.append(line); continue
        heading = re.sub(r'^\s*#{1,6}\s+', '', stripped).strip().strip('*_# ')
        if re.fullmatch(r'(?:page\s+)?' + NUMBER, heading, re.I):
            result.append(line); continue
        if SECTION.fullmatch(heading):
            in_listing = True
            is_index = heading.lower().startswith('index')
            result.append(line); continue

        def resolve(match):
            label, destination = match.groups()
            if destination.startswith('page:'):
                target = targets.get(number(destination[5:]))
            else:
                target = filenames.get(file_key(destination))
            return f'[{label}]({target})' if target else match[0]

        # Never resolve fake links inside code or images.
        code_spans = [(m.start(), m.end()) for m in re.finditer(r'(`+).*?\1|!\[[^\]\n]*\]\([^\n]*?\)', line)]
        line = LINK.sub(lambda m: m[0] if any(a <= m.start() < b for a,b in code_spans) else resolve(m), line)
        if not detect:
            result.append(line); continue
        masked = list(line)
        protected = []
        for match in PROTECTED.finditer(line):
            protected.append(match.span())
            masked[match.start():match.end()] = ' ' * len(match[0])
            existing = LINK.fullmatch(match[0])
            if existing and (file_key(existing[2]) or existing[2].startswith('page:')) and re.fullmatch(NUMBER, existing[1]):
                # Retain numeric link labels as context for partially linked lists
                # and abbreviated ranges, but never wrap the label again.
                start = match.start() + 1
                masked[start:start + len(existing[1])] = existing[1]
        visible = ''.join(masked)
        spans = [m.span(1) for m in EXPLICIT.finditer(visible)]
        if in_listing and not stripped.startswith('#'):
            if is_index:
                spans.extend(m.span(1) for m in INDEX.finditer(visible))
            else:
                match = CONTENTS.search(visible.rstrip('\n'))
                # Require a title before the locator: do not link a printed footer
                # or a bare chapter number masquerading as an entry.
                if match and re.search(r'[A-Za-z]', visible[:match.start(1)]) and not re.fullmatch(r'\s*(?:chapter|part|book|section)\s+' + NUMBER + r'\s*', visible, re.I):
                    spans.append(match.span(1))
        replacements = {}
        for start, end in spans:
            segment = visible[start:end]
            previous = None
            previous_end = 0
            for match in re.finditer(NUMBER, segment):
                raw = match[0]
                target_number = raw
                gap = segment[previous_end:match.start()]
                if previous and re.fullmatch(r'\s*[–—-]\s*', gap) and previous.isdigit() and raw.isdigit() and len(raw) < len(previous):
                    target_number = previous[:-len(raw)] + raw
                    if int(target_number) < int(previous):
                        target_number = str(int(target_number) + 10 ** len(raw))
                target = targets.get(number(target_number))
                if target and not any(a <= start + match.start() < b for a,b in protected):
                    replacements[(start + match.start(), start + match.end())] = f'[{raw}]({target})'
                previous, previous_end = target_number, match.end()
        for (start, end), replacement in sorted(replacements.items(), reverse=True):
            line = line[:start] + replacement + line[end:]
        result.append(line)
    return ''.join(result)
