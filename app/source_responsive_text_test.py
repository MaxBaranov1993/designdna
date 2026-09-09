"""Captured line substrings must survive viewport merge and project reload."""
import copy
import json
from pathlib import Path

import jsonschema
import pytest
import scraper
from ir.migrate import migrate_ir
from ir.responsive import materialize
from ir.schema import load_schema


@pytest.mark.parametrize('mobile_text', ['who to email + how many you can', ''])
def test_measured_line_content_survives_merge_migration_and_materialization(mobile_text):
    def capture(text, width):
        return scraper._captured_ir(
            {'name': 'step', 'kind': 'section', 'label': 'Step', 'selector': '#step'},
            {'root': {'width': width, 'height': 100}, 'nodes': [
                {'type': 'text', 'sourceKey': 'root/p:1::text0l0', 'text': text,
                 'style': {'fontSmoothing': 'antialiased'},
                 'frame': {'x': 0, 'y': 0, 'width': width, 'height': 20}}]})
    variants = {'desktop': capture('who to email + how', 1440),
                'mobile': capture(mobile_text, 390)}
    original = copy.deepcopy(variants)
    merged = scraper._merge_responsive_irs(variants, {
        name: {'width': ir['frame']['width'], 'height': 100} for name, ir in variants.items()})
    jsonschema.Draft7Validator(load_schema(merged['version'])).validate(merged)
    migrated = migrate_ir(merged, recorded_at='2026-09-09T00:00:00+00:00')
    schema = json.loads((Path(__file__).resolve().parents[1] / 'schema/design-ir.schema.json').read_text(encoding='utf-8'))
    jsonschema.Draft7Validator(schema).validate(migrated)
    assert variants == original
    for width, expected in [(1440, 'who to email + how'), (390, mobile_text)]:
        node = materialize(migrated, width)['tree'][0]['children'][0]
        assert node['text'] == expected
        assert node['style']['fontSmoothing'] == 'antialiased'
        assert node['sourceKey'] == 'root/p:1::text0l0'
    assert migrate_ir(migrated) == migrated


def test_legacy_shared_text_is_not_invented_during_migration():
    ir = {'version': '1.1', 'tree': [{'id': 'step', 'type': 'source-block',
          'children': [{'type': 'text', 'text': 'shared', 'sourceKey': 'line',
                        'responsive': {'mobile': {'frame': {'width': 390}}}}]}]}
    migrated = migrate_ir(ir)
    assert 'text' not in migrated['tree'][0]['children'][0]['responsive']['mobile']
    assert materialize(migrated, 390)['tree'][0]['children'][0]['text'] == 'shared'
