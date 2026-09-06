import base64
import copy
import hashlib
from types import SimpleNamespace

import pytest
import scraper


SVG = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 10"><path fill="#123abc" d="M0 0h20v10H0z"/></svg>'


def test_remote_vector_retains_exact_original_bytes_and_geometry():
    url = 'https://rsale.net/logo.svg'
    node = {'type':'image', 'sourceKey':'logo', 'src':url,
            'style':{'objectFit':'contain', 'objectPosition':'20% 30%'},
            'frame':{'x':2,'y':3,'width':100,'height':60}}
    before = copy.deepcopy(node)
    item = {'nodes':[node], 'assetRequests':[{'url':url,'sourceKey':'logo','width':100,'height':60,
            'objectFit':'contain','objectPosition':'20% 30%'}]}
    page = SimpleNamespace(locator=lambda *_: pytest.fail('vector capture must not resample the DOM'))
    records = scraper._materialize_capture_assets(page, item, '#logo', {url:SVG})
    assert base64.b64decode(node['src'].split(',',1)[1]) == SVG
    assert node['style'] == before['style'] and node['frame'] == before['frame']
    assert node['sourceMeta']['url'] == url
    assert records[0]['sourceSha256'] == hashlib.sha256(SVG).hexdigest()
    assert records[0]['mime'] == 'image/svg+xml'


@pytest.mark.parametrize('raw', [b'<svg', b'<html/>',
    b'<!DOCTYPE svg [<!ENTITY x "oops">]><svg>&x;</svg>',
    b'<svg><image href="https://example.com/a.png"/></svg>',
    b'<svg><style>@import "font.css";</style></svg>',
    b'<svg><path fill="url(https://example.com/fill)"/></svg>',
    b'<svg onload="alert(1)"/>', b'<svg><script/></svg>'])
def test_incomplete_or_active_svg_is_not_claimed_as_self_contained(raw):
    assert scraper._self_contained_svg(raw) is None


def test_local_vector_references_remain_vector():
    raw = b'<svg><defs><linearGradient id="g"/></defs><path fill="url(#g)"/><use href="#g"/></svg>'
    assert scraper._self_contained_svg(raw)
