from src.service.codes import guess_market, to_api_code, build_code_map, remap_code


def test_guess_market_segments():
    assert guess_market("110059") == "SH"
    assert guess_market("113050") == "SH"
    assert guess_market("120002") == "SH"
    assert guess_market("123185") == "SZ"
    assert guess_market("128096") == "SZ"
    assert guess_market("600519") == "SH"
    assert guess_market("000001") == "SZ"
    assert guess_market("H02380") == "HK"
    assert guess_market("430047") == "BJ"


def test_to_api_code():
    assert to_api_code("600519") == "sh600519"
    assert to_api_code("000037") == "sz000037"
    assert to_api_code("H02380") == "hk02380"
    assert to_api_code("sh600519") == "sh600519"


def test_remap_roundtrip():
    codes = ["600519", "000037", "H02380"]
    m = build_code_map(codes)
    assert remap_code("sh600519", m) == "600519"
    assert remap_code("sz000037", m) == "000037"
    assert remap_code("hk02380", m) == "H02380"
    assert remap_code("600519", m) == "600519"
