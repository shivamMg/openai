import inspect
import json
from datetime import datetime
from enum import Enum
from typing import Dict, Any, List

from pydantic import BaseModel, Field


class CustomBaseModel(BaseModel):
    class Config:
        @staticmethod
        def json_schema_extra(schema: Dict[str, Any]) -> None:
            schema.pop("required", None)
            for name, prop in schema.get("properties", {}).items():
                prop.pop("title", None)
                prop.pop("default", None)



class OrderStatus(str, Enum):
    PLACED = "PLACED"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    DELIVERED = "DELIVERED"
    CANCELED = "CANCELED"


class Order(CustomBaseModel):
    """Order details."""

    id: int = Field(description="Order ID.")
    item_name: str = Field(description="Ordered item's name.")
    status: OrderStatus = Field(description="Order status.")
    order_date: datetime = Field(description="Order date.")
    current_location: str = Field(
        description="OUT_FOR_DELIVERY order's current location.", default=""
    )
    delivery_eta: datetime = Field(
        description="OUT_FOR_DELIVERY order's delivery estimated time of arrival.",
        default="",
    )

    class Config:
        @staticmethod
        def json_schema_extra(schema: Dict[str, Any]) -> None:
            for name, prop in schema.get("properties", {}).items():
                prop.pop("format", None)
                if name == "status":
                    prop.pop("allOf", None)
                    prop["enum"] = [status.value for status in OrderStatus]
            CustomBaseModel.Config.json_schema_extra(schema)

    def __str__(self):
        csv_header = ",".join(list(self.model_fields.keys()))
        csv = f"{self.id},{self.item_name},{self.status},{self.order_date},{self.current_location},{self.delivery_eta}"
        return csv_header + "\n" + csv


class OrderList(CustomBaseModel):
    """List of orders."""

    orders: List[Order] = Field(description="List of orders.")

    def __str__(self):
        csv_header = ",".join(list(Order.model_fields.keys())[:-2])
        orders_csv = [csv_header]
        for order in self.orders:
            csv = f"{order.id},{order.item_name},{order.status},{order.order_date}"
            orders_csv.append(csv)
        return "\n".join(orders_csv)


class OrderAPI:
    def __init__(self):
        self.orders = [
            Order(
                id=124,
                item_name="Nike running shoes",
                status=OrderStatus.OUT_FOR_DELIVERY,
                order_date=datetime.strptime("9/11/2023", "%m/%d/%Y"),
                current_location="Indiranagar",
                delivery_eta=datetime.strptime("9/13/2023", "%m/%d/%Y"),
            ),
            Order(
                id=123,
                item_name="Beige blanket",
                status=OrderStatus.DELIVERED,
                order_date=datetime.strptime("1/1/2023", "%m/%d/%Y"),
            ),
            Order(
                id=122,
                item_name="IKEA Table lamp",
                status=OrderStatus.CANCELED,
                order_date=datetime.strptime("2/28/2022", "%m/%d/%Y"),
            ),
            Order(
                id=121,
                item_name="Shampoo",
                status=OrderStatus.DELIVERED,
                order_date=datetime.strptime("1/1/2022", "%m/%d/%Y"),
            ),
        ]

    def list_orders(self, to_get_order_details: bool) -> OrderList:
        """List orders. If the intent of list orders is to get order ids then to_get_order_details should be true."""
        return OrderList(orders=self.orders)

    def get_order_details(self, order_id: int) -> Order:
        """Get order details like name, status, order datetime of an order id. If status is OUT_FOR_DELIVERY, order's current location and ETA is also returned."""
        order = [o for o in self.orders if o.id == order_id][0]
        return order

    def cancel_order(self, order_id: int, confirmed: bool) -> str:
        """Cancel OUT_FOR_DELIVER order. confirmed represents whether user has confirmed cancellation. Return value tells whether cancellation was successful."""
        return "Cancellation was successful."

    @staticmethod
    def _type_to_parameter(type_cls):
        type_to_name = {
            str: "string",
            int: "integer",
            bool: "boolean",
        }
        return {
            "type": type_to_name[type_cls],
        }

    @classmethod
    def get_functions(cls):
        allowlist = ["get_order_details", "list_orders", "cancel_order"]
        functions = []
        for name, func in inspect.getmembers(cls, inspect.isfunction):
            if name not in allowlist:
                continue
            parameters = {}
            for arg_name, arg_type in func.__annotations__.items():
                if arg_name == "return":
                    if issubclass(arg_type, CustomBaseModel):
                        return_type = arg_type.model_json_schema()
                    else:
                        return_type = cls._type_to_parameter(arg_type)
                else:
                    parameters[arg_name] = cls._type_to_parameter(arg_type)
            functions.append({
                "name": name,
                "description": func.__doc__,
                "parameters": {
                    "type": "object",
                    "properties": parameters,
                },
                "result": return_type,
            })
        return functions


if __name__ == "__main__":
    order_api = OrderAPI()
    print(json.dumps(order_api.get_functions(), indent=2))
    # print(order_api.list_orders())
    # print()
    # print(order_api.get_order_details(order_id=124))

    # print(json.dumps(Order.model_json_schema(), indent=2))
    # print(json.dumps(OrderList.model_json_schema(), indent=2))
