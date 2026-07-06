"""Vision plumbing: attachment extraction, message building, provider formats."""
import base64

from app.multimodal.vision import attach_images, extract_image_attachments
from app.providers.cloud_provider import _to_openai_messages

_PNG_B64 = base64.b64encode(b"\x89PNG\r\n\x1a\nfakebytes").decode()


def test_extract_accepts_raw_base64_and_data_urls():
    atts = [
        {"type": "image", "name": "a.png", "data": _PNG_B64},
        {"type": "image", "name": "b.png", "data": f"data:image/png;base64,{_PNG_B64}"},
    ]
    images = extract_image_attachments(atts)
    assert images == [_PNG_B64, _PNG_B64]


def test_extract_drops_non_images_and_garbage():
    atts = [
        {"name": "notes.txt", "id": "f1"},           # uploaded file metadata, not an image
        {"type": "image", "name": "bad", "data": "not-base-64!!!"},
        {"type": "image", "name": "empty", "data": ""},
        "not-a-dict",
    ]
    assert extract_image_attachments(atts) == []
    assert extract_image_attachments(None) == []


def test_extract_caps_image_count():
    atts = [{"type": "image", "data": _PNG_B64} for _ in range(10)]
    assert len(extract_image_attachments(atts)) == 4


def test_attach_images_targets_last_user_message_without_mutating_input():
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "reply"},
        {"role": "user", "content": "what is in this image?"},
    ]
    out = attach_images(messages, [_PNG_B64])
    assert out[-1]["images"] == [_PNG_B64]
    assert "images" not in out[1]
    assert "images" not in messages[-1], "original messages must not be mutated"


def test_cloud_provider_converts_images_to_openai_content_parts():
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "describe", "images": [_PNG_B64]},
    ]
    converted = _to_openai_messages(messages)
    assert converted[0] == {"role": "system", "content": "sys"}
    parts = converted[1]["content"]
    assert parts[0] == {"type": "text", "text": "describe"}
    assert parts[1]["type"] == "image_url"
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")
