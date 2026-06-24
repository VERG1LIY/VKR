from handlers.messages import _looks_like_search_request


def test_detects_search_request_with_find_words():
    assert _looks_like_search_request("найди документ про вал") is True
    assert _looks_like_search_request("дай мне чертёж") is True
    assert _looks_like_search_request("покажи техпроцесс") is True


def test_ignores_regular_chat_message():
    assert _looks_like_search_request("как дела?") is False
    assert _looks_like_search_request("спасибо") is False
