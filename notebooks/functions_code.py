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
    name: str = Field(description="Ordered item's name.")
    status: OrderStatus = Field(description="Order status.")
    date: datetime = Field(description="Order date.")
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

    def csv(self):
        return f"{self.id},{self.name},{self.status},{self.date},{self.current_location},{self.delivery_eta}"

    @classmethod
    def csv_header(cls):
        return ",".join(list(cls.model_fields.keys()))

    def stringify(self):
        return self.csv_header() + "\n" + self.csv()


class OrderList(CustomBaseModel):
    """List of orders."""

    orders: List[Order] = Field(description="List of orders.")

    def stringify(self):
        orders_csv = [Order.csv_header()]
        for order in self.orders:
            orders_csv.append(order.csv())
        return "\n".join(orders_csv)


class OrderAPI:
    def __init__(self):
        self.orders = [
            Order(
                id=124,
                name="Nike running shoes",
                status=OrderStatus.OUT_FOR_DELIVERY,
                date=datetime.strptime("9/11/2023", "%m/%d/%Y"),
                current_location="Indiranagar",
                delivery_eta=datetime.strptime("9/13/2023", "%m/%d/%Y"),
            ),
            Order(
                id=123,
                name="Beige blanket",
                status=OrderStatus.DELIVERED,
                date=datetime.strptime("1/1/2023", "%m/%d/%Y"),
            ),
            Order(
                id=122,
                name="IKEA Table lamp",
                status=OrderStatus.CANCELED,
                date=datetime.strptime("2/28/2022", "%m/%d/%Y"),
            ),
            Order(
                id=121,
                name="Bullet proof socks",
                status=OrderStatus.DELIVERED,
                date=datetime.strptime("1/1/2022", "%m/%d/%Y"),
            ),
        ]

    def list_orders(self) -> OrderList:
        """List orders."""
        return OrderList(self.orders)

    def get_order_details(self, order_id: str) -> Order:
        """Get order details like name, status, order datetime of an order id. If status is OUT_FOR_DELIVERY, order's current location and ETA is also returned."""
        order = [o for o in self.orders if o.id == order_id][0]
        return order

    @classmethod
    def get_functions(cls):
        allowlist = ["get_order_details", "list_orders"]
        functions = []
        for name, func in inspect.getmembers(cls, inspect.isfunction):
            if name not in allowlist:
                continue
            parameters = {}
            for arg_name, arg_type in func.__annotations__.items():
                if arg_name == "return":
                    return_type = arg_type
                    if hasattr(return_type, "model_json_schema"):
                        return_type = return_type.model_json_schema()
                else:
                    type_to_name = {
                        str: "string"
                    }
                    parameters[arg_name] = {
                        "type": type_to_name[arg_type],
                    }
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
