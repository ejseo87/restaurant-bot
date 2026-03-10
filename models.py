from pydantic import BaseModel, Field


class OrderItem(BaseModel):
    dish_name: str
    quantity: int
    price: float


class RestaurantContext(BaseModel):
    customer_name: str = "Guest"
    order_items: list[OrderItem] = Field(default_factory=list)
    order_confirmed: bool = False


class InputGuardRailOutput(BaseModel):
    is_off_topic: bool
    reason: str


class HandoffData(BaseModel):
    to_agent_name: str
    issue_type: str
    issue_description: str
    reason: str
