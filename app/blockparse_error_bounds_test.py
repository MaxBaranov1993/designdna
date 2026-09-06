import blockparse


def test_schema_diagnostic_keeps_path_without_inline_image_bytes(monkeypatch):
    message = "tree/0/sourceMeta/url: 'data:image/png;base64," + "A" * 100000 + "' is too long"
    monkeypatch.setattr(blockparse.ir, 'validate_ir', lambda doc: [])
    monkeypatch.setattr(blockparse.ir, 'format_errors', lambda errors: [message])
    errors = blockparse._validate({})
    assert errors == ["tree/0/sourceMeta/url: '<inline-asset>' is too long"]


def test_non_asset_schema_messages_are_bounded(monkeypatch):
    monkeypatch.setattr(blockparse.ir, 'validate_ir', lambda doc: [])
    monkeypatch.setattr(blockparse.ir, 'format_errors', lambda errors: ['tree/0: ' + 'x' * 5000])
    assert len(blockparse._validate({})[0]) == 1000
