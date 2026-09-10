from asset_quality import audit


def test_text_evidence_includes_heading_button_and_semantic_fields_but_not_image_alt():
    ir = {'tree': [{'type': 'composition', 'children': [
        {'type': 'heading', 'text': 'Заголовок'}, {'type': 'text', 'text': 'Текст'},
        {'type': 'button', 'text': 'Купить'}, {'type': 'image', 'alt': 'Текст внутри картинки'},
        {'type': 'hero', 'props': {'heading': 'Секция', 'subheading': 'Подзаголовок'}},
    ]}]}
    evidence = audit(ir)
    assert evidence['nativeTextCount'] == 5
    assert evidence['status'] == 'fail'  # the missing image remains a separate failure
    assert evidence['checks']['pixelContent'] == 'unknown'
