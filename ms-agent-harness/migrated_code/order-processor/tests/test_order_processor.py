import json
import pytest
from src.azure_functions.order_processor.function_app import create_order, get_order


def test_create_order():
    input_data = {
        "id": "123",
        "item": "widget",
        "quantity": 4
    }
    response = create_order(input_data)
    assert response['status'] == 'success'
    assert response['data']['id'] == "123"


def test_get_order():
    order_id = "123"
    response = get_order(order_id)
    assert response['status'] == 'success'
    assert response['data']['id'] == order_id


def test_create_order_invalid_json():
    input_data = {"wrong_key": "value"}
    with pytest.raises(KeyError):
        create_order(input_data)


def test_get_order_not_found():
    order_id = "non-existent-id"
    response = get_order(order_id)
    assert response['status'] == 'error'
    assert response['message'] == 'Order not found'