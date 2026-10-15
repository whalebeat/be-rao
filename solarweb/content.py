"""Rich-text sanitizing for product descriptions and posts (staff-entered HTML)."""
import html

import nh3

ALLOWED_TAGS = {
    'p', 'br', 'h2', 'h3', 'h4', 'strong', 'b', 'em', 'i', 'u', 's', 'a', 'ul', 'ol', 'li',
    'img', 'blockquote', 'table', 'thead', 'tbody', 'tr', 'th', 'td', 'span', 'pre', 'code', 'hr',
}
ALLOWED_ATTRIBUTES = {
    '*': {'class'},
    'a': {'href', 'title', 'target'},
    'img': {'src', 'alt', 'width', 'height'},
    'td': {'colspan', 'rowspan'},
    'th': {'colspan', 'rowspan'},
}


def sanitize_html(value):
    value = (value or '').strip()
    if not value or value in ('<p><br></p>', '<p></p>'):
        return ''
    return nh3.clean(value, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRIBUTES,
                     url_schemes={'http', 'https', 'mailto', 'tel'}, link_rel='noopener noreferrer')


def text_to_html(value):
    """Plain text (e.g. from CSV) -> paragraphs. HTML input is sanitized instead."""
    value = (value or '').strip()
    if not value:
        return ''
    if '<' in value and '>' in value:
        return sanitize_html(value)
    return ''.join(f'<p>{html.escape(p.strip())}</p>' for p in value.replace('\\n', '\n').split('\n') if p.strip())


def strip_tags(value):
    return nh3.clean(value or '', tags=set()).strip()
