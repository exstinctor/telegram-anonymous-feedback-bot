"""Тесты определения типа вложения и фильтра is_supported_content."""
from types import SimpleNamespace

from bot.handlers.messages import _detect_attachment, is_supported_content


def mk(**kwargs):
    base = dict(text=None, caption=None, photo=None, video=None, voice=None,
                audio=None, animation=None, sticker=None, document=None)
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_commands_excluded():
    assert is_supported_content(mk(text="/foo")) is False
    assert is_supported_content(mk(text="/start")) is False
    assert is_supported_content(mk(text="/start payload")) is False


def test_supported_types_pass():
    assert is_supported_content(mk(text="hello")) is True
    assert is_supported_content(mk(photo=[SimpleNamespace(file_id="P1")])) is True
    assert is_supported_content(mk(video=SimpleNamespace(file_id="V1"))) is True
    assert is_supported_content(mk(voice=SimpleNamespace(file_id="VO1"))) is True
    assert is_supported_content(mk(audio=SimpleNamespace(file_id="A1"))) is True
    assert is_supported_content(mk(animation=SimpleNamespace(file_id="AN1"))) is True
    assert is_supported_content(mk(sticker=SimpleNamespace(file_id="S1"))) is True
    assert is_supported_content(mk(document=SimpleNamespace(file_id="D1", file_name="a.pdf"))) is True


def test_empty_message_excluded():
    assert is_supported_content(mk()) is False


def test_detect_attachment_photo_picks_largest():
    msg = mk(photo=[SimpleNamespace(file_id="small"), SimpleNamespace(file_id="BIG")])
    msg_type, fields = _detect_attachment(msg)
    assert msg_type == "PHOTO"
    assert fields["photo_id"] == "BIG"


def test_detect_attachment_document_keeps_filename():
    msg = mk(document=SimpleNamespace(file_id="D1", file_name="virus.exe"))
    msg_type, fields = _detect_attachment(msg)
    assert msg_type == "DOCUMENT"
    assert fields["document_name"] == "virus.exe"


def test_detect_attachment_text():
    msg_type, fields = _detect_attachment(mk(text="hi"))
    assert msg_type == "TEXT"
    assert fields == {}


def test_detect_attachment_unsupported_returns_none():
    msg_type, fields = _detect_attachment(mk())
    assert msg_type is None
    assert fields is None
