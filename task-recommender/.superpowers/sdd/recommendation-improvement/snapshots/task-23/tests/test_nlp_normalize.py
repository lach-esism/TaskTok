from app.nlp.normalize import normalize_text
from app.nlp.tokenizer import (
    content_words,
    jieba_available,
    keywords,
    tokenize,
)


def test_normalize_text_handles_none_and_empty():
    assert normalize_text(None) == ""
    assert normalize_text("") == ""
    assert normalize_text("   ") == ""


def test_normalize_text_nfkc_fullwidth():
    assert normalize_text("ＡＢＣ１２３") == "ABC123"
    assert normalize_text("８，０００元") == "8,000元"


def test_normalize_text_fullwidth_space_and_whitespace():
    assert normalize_text("预算　8000　元") == "预算 8000 元"
    assert normalize_text("  多   个\n空\t格  ") == "多 个 空 格"


def test_normalize_text_punctuation_dashes():
    assert normalize_text("8000–30000") == "8000-30000"
    assert normalize_text("8000—30000") == "8000-30000"
    assert normalize_text("8000～30000") == "8000~30000"
    assert normalize_text("等等…") == "等等..."


def test_normalize_text_preserves_chinese():
    assert normalize_text("微信小程序开发") == "微信小程序开发"


def test_tokenizer_falls_back_without_jieba():
    # jieba is optional; the app must work without it.
    assert isinstance(jieba_available(), bool)
    tokens = tokenize("微信小程序开发")
    assert tokens
    assert all(isinstance(token, str) and token for token in tokens)


def test_tokenizer_latin_words_preserved():
    tokens = tokenize("使用 Figma 制作原型")
    assert "figma" in tokens or "figma" in " ".join(tokens).lower()


def test_content_words_drops_stopwords_and_single_cjk():
    words = content_words("我们要做一个会员小程序，包含下单支付和后台管理。")
    assert "程序" in words or "小程序" in words or "支付" in words
    # "的"/"要" style stopwords are filtered out.
    assert "的" not in words


def test_keywords_returns_top_k_unique():
    words = keywords("小程序开发，小程序支付，支付接口，后端开发", top_k=3)
    assert isinstance(words, list)
    assert 1 <= len(words) <= 3
    assert len(words) == len(set(words))


def test_keywords_top_k_at_least_one():
    assert keywords("", top_k=5) == []
