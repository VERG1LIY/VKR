from handlers.commands import _escape_html


def test_escape_html_escapes_literal_angle_brackets():
    text = "Команда /search <текст> — пример"
    assert _escape_html(text) == "Команда /search &lt;текст&gt; — пример"


def test_escape_html_escapes_ampersands_and_quotes():
    text = 'Текст & "цитата"'
    assert _escape_html(text) == 'Текст &amp; &quot;цитата&quot;'
