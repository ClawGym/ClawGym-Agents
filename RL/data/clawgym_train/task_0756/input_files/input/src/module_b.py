from .module_a import external_api_call


def process_data():
    """
    Calls external_api_call and uppercases the result.
    """
    data = external_api_call()
    return data.upper()