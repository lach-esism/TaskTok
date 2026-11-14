"""Additive /classify fields for the NLP enhancement."""


def test_classify_returns_additive_nlp_fields(client):
    response = client.post(
        "/classify",
        json={
            "text": "招聘一名电池工艺工程师，要求 3 年以上经验，预算 8000 元。",
            "top_k": 2,
        },
    )
    assert response.status_code == 200
    body = response.json()
    # Existing contract stays intact.
    assert body["category"] == "recruitment"
    assert body["suggested_template"] == "recruitment"
    assert len(body["candidates"]) == 2
    assert body["extracted"]["budget_min"] == 8000
    # Additive fields.
    assert "confidence" in body
    assert "calibrated_confidence" in body
    assert "confidence_threshold" in body
    assert "evidence" in body
    assert "extracted_v2" in body
    assert "fields_v2" in body
    assert body["fields_v2"]["budget"]["value"] == [8000, 8000]
    assert isinstance(body["calibrated_confidence"], (int, float))
    assert isinstance(body["evidence"], list)
