from backend.services.playwright.session_state import normalize_platform_storage_state


def test_kuaishou_session_cookies_are_cloned_to_root_domain():
    state = {
        "cookies": [
            {
                "name": "kuaishou.web.cp.api_st",
                "value": "session-value",
                "domain": "cp.kuaishou.com",
                "path": "/",
                "httpOnly": True,
                "secure": True,
                "sameSite": "None",
            }
        ],
        "origins": [],
    }

    normalized = normalize_platform_storage_state("kuaishou", state)

    domains = {
        cookie["domain"]
        for cookie in normalized["cookies"]
        if cookie["name"] == "kuaishou.web.cp.api_st"
    }
    assert "cp.kuaishou.com" in domains
    assert ".kuaishou.com" in domains
    assert state["cookies"][0]["domain"] == "cp.kuaishou.com"


def test_non_kuaishou_storage_state_is_not_domain_cloned():
    state = {
        "cookies": [
            {
                "name": "kuaishou.web.cp.api_st",
                "value": "session-value",
                "domain": "cp.kuaishou.com",
                "path": "/",
            }
        ],
    }

    normalized = normalize_platform_storage_state("zhihu", state)

    assert normalized["cookies"] == state["cookies"]
