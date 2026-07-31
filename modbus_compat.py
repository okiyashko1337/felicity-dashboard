"""Compatibility helpers for supported PyModbus 3.x versions."""

import inspect


def read_holding_registers(
    client: object,
    address: int,
    count: int,
    slave_id: int,
):
    """Use the correct unit-ID keyword for the installed PyModbus version."""
    method = client.read_holding_registers
    parameters = inspect.signature(method).parameters
    unit_keyword = "device_id" if "device_id" in parameters else "slave"
    return method(address, count=count, **{unit_keyword: slave_id})
