from unittest.mock import patch

from src.module_b import process_data


# WRONG: Patching where the function is defined (module_a) instead of where it's used (module_b).
@patch("src.module_a.external_api_call")
def test_process_data_uses_mocked_data_wrong_target(mock_api):
    mock_api.return_value = "mocked data"
    result = process_data()
    # Expecting uppercase transformation of the mocked data
    assert result == "MOCKED DATA"