from src.datasource.gs_client import is_gs_error
from src.datasource.ratelimit import GS_QUOTA_CODE


def test_is_gs_error_quota():
    assert is_gs_error({"result": [{"code": GS_QUOTA_CODE, "msg": "限额"}], "data": None})
    assert is_gs_error({"result": [{"code": -1, "msg": "fail"}]})
    assert not is_gs_error({"result": [{"code": 0}], "data": {}})
    assert not is_gs_error({"data": []})
    assert not is_gs_error(None)
