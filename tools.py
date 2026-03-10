import random
import streamlit as st
from typing import Any

from agents import function_tool, AgentHooks, Agent, Tool, RunContextWrapper
from models import RestaurantContext, OrderItem


# =============================================================================
# MENU DATA
# =============================================================================

MENU = {
    "김치찌개": {
        "price": 12000,
        "ingredients": ["김치", "돼지고기", "두부", "대파", "고춧가루"],
        "allergens": ["돼지고기"],
        "vegetarian": False,
        "description": "얼큰하고 깊은 맛의 김치찌개",
    },
    "된장찌개": {
        "price": 11000,
        "ingredients": ["된장", "두부", "애호박", "버섯", "대파"],
        "allergens": ["대두"],
        "vegetarian": True,
        "description": "구수하고 담백한 된장찌개",
    },
    "비빔밥": {
        "price": 13000,
        "ingredients": ["밥", "나물", "달걀", "고추장", "참기름"],
        "allergens": ["달걀", "참깨"],
        "vegetarian": True,
        "description": "색깔 나물과 고추장이 어우러진 비빔밥",
    },
    "불고기": {
        "price": 16000,
        "ingredients": ["소고기", "양파", "버섯", "간장", "배"],
        "allergens": ["소고기", "대두"],
        "vegetarian": False,
        "description": "달콤하게 재운 소고기 불고기",
    },
    "파전": {
        "price": 10000,
        "ingredients": ["밀가루", "파", "달걀", "해산물"],
        "allergens": ["글루텐", "달걀", "해산물"],
        "vegetarian": False,
        "description": "바삭한 해물파전",
    },
    "냉면": {
        "price": 11000,
        "ingredients": ["메밀면", "육수", "오이", "달걀", "겨자"],
        "allergens": ["글루텐", "달걀"],
        "vegetarian": False,
        "description": "시원한 평양식 냉면",
    },
    "순두부찌개": {
        "price": 11000,
        "ingredients": ["순두부", "해산물", "달걀", "고춧가루"],
        "allergens": ["달걀", "해산물"],
        "vegetarian": False,
        "description": "부드러운 순두부찌개",
    },
    "갈비탕": {
        "price": 18000,
        "ingredients": ["소갈비", "무", "당면", "대파"],
        "allergens": ["소고기"],
        "vegetarian": False,
        "description": "깊은 국물의 소갈비탕",
    },
}

# In-memory reservation storage (persists within a process)
RESERVATIONS: dict[str, dict] = {}


# =============================================================================
# MENU TOOLS
# =============================================================================


@function_tool
def get_menu_list(wrapper: RunContextWrapper[RestaurantContext]) -> str:
    """Get the full menu list with prices and descriptions."""
    lines = ["📋 오늘의 메뉴\n"]
    for name, info in MENU.items():
        veg = " 🌱" if info["vegetarian"] else ""
        lines.append(f"• {name}{veg} - {info['price']:,}원\n  {info['description']}")
    return "\n".join(lines)


@function_tool
def get_dish_details(wrapper: RunContextWrapper[RestaurantContext], dish_name: str) -> str:
    """
    Get detailed information about a specific dish including ingredients and allergens.

    Args:
        dish_name: Name of the dish to look up
    """
    dish = MENU.get(dish_name)
    if not dish:
        available = ", ".join(MENU.keys())
        return f"'{dish_name}'을(를) 찾을 수 없습니다.\n전체 메뉴: {available}"

    veg = "✅ 채식 가능" if dish["vegetarian"] else "❌ 비채식"
    allergens = ", ".join(dish["allergens"]) if dish["allergens"] else "없음"
    ingredients = ", ".join(dish["ingredients"])

    return f"""🍽️ {dish_name}
설명: {dish["description"]}
가격: {dish["price"]:,}원
재료: {ingredients}
알레르기 유발 성분: {allergens}
채식 여부: {veg}"""


@function_tool
def get_allergen_info(wrapper: RunContextWrapper[RestaurantContext], allergen: str) -> str:
    """
    Find all dishes that contain or are free from a specific allergen.

    Args:
        allergen: Allergen to search for (e.g. '달걀', '글루텐', '해산물', '돼지고기')
    """
    containing = [name for name, info in MENU.items() if allergen in info["allergens"]]
    safe = [name for name, info in MENU.items() if allergen not in info["allergens"]]

    if not containing:
        return f"'{allergen}' 성분이 포함된 메뉴가 없습니다. 모든 메뉴를 안심하고 드실 수 있습니다."

    return f"""⚠️ {allergen} 알레르기 정보

주의 메뉴 (포함): {", ".join(containing)}
안전 메뉴 (미포함): {", ".join(safe)}"""


# =============================================================================
# ORDER TOOLS
# =============================================================================


@function_tool
def add_to_order(
    wrapper: RunContextWrapper[RestaurantContext], dish_name: str, quantity: int
) -> str:
    """
    Add a dish to the current order.

    Args:
        dish_name: Name of the dish to add
        quantity: Number of servings
    """
    context = wrapper.context

    if context.order_confirmed:
        return "이미 주문이 확정되었습니다. 새 주문을 원하시면 직원에게 문의해 주세요."

    dish = MENU.get(dish_name)
    if not dish:
        available = ", ".join(MENU.keys())
        return f"'{dish_name}'을(를) 찾을 수 없습니다.\n전체 메뉴: {available}"

    for item in context.order_items:
        if item.dish_name == dish_name:
            item.quantity += quantity
            subtotal = item.quantity * dish["price"]
            return f"✅ {dish_name} {quantity}개 추가 (총 {item.quantity}개, {subtotal:,}원)"

    context.order_items.append(
        OrderItem(dish_name=dish_name, quantity=quantity, price=dish["price"])
    )
    return f"✅ {dish_name} {quantity}개를 주문에 추가했습니다. ({dish['price']:,}원)"


@function_tool
def get_current_order(wrapper: RunContextWrapper[RestaurantContext]) -> str:
    """Get the current order items and total price."""
    context = wrapper.context

    if not context.order_items:
        return "현재 주문 내역이 없습니다."

    lines = ["🛒 현재 주문 내역\n"]
    total = 0
    for item in context.order_items:
        subtotal = item.price * item.quantity
        total += subtotal
        lines.append(f"• {item.dish_name} x{item.quantity} = {subtotal:,}원")

    lines.append(f"\n💰 총합계: {total:,}원")
    status = "✅ 확정됨" if context.order_confirmed else "⏳ 미확정 (확인 필요)"
    lines.append(f"주문 상태: {status}")

    return "\n".join(lines)


@function_tool
def confirm_order(wrapper: RunContextWrapper[RestaurantContext]) -> str:
    """Confirm and finalize the current order after reviewing with the customer."""
    context = wrapper.context

    if not context.order_items:
        return "주문 내역이 없습니다. 먼저 메뉴를 선택해 주세요."

    if context.order_confirmed:
        return "이미 주문이 확정되었습니다."

    context.order_confirmed = True
    order_number = f"ORD-{random.randint(1000, 9999)}"
    total = sum(item.price * item.quantity for item in context.order_items)
    items_str = ", ".join(f"{item.dish_name} x{item.quantity}" for item in context.order_items)

    return f"""🎉 주문이 확정되었습니다!

주문번호: {order_number}
주문 내역: {items_str}
총 금액: {total:,}원
예상 준비 시간: 20~30분

맛있게 드세요! 😊"""


# =============================================================================
# PAYMENT TOOLS
# =============================================================================


@function_tool
def process_payment(
    wrapper: RunContextWrapper[RestaurantContext],
    payment_method: str,
) -> str:
    """
    Process payment for the confirmed order.

    Args:
        payment_method: Payment method (e.g. '카드', '현금', '카카오페이')
    """
    context = wrapper.context

    if not context.order_items:
        return "결제할 주문 내역이 없습니다."

    if not context.order_confirmed:
        return "아직 주문이 확정되지 않았습니다. 먼저 주문을 확정해 주세요."

    total = sum(item.price * item.quantity for item in context.order_items)
    items_str = ", ".join(f"{item.dish_name} x{item.quantity}" for item in context.order_items)
    receipt_number = f"PAY-{random.randint(10000, 99999)}"

    return f"""💳 결제가 완료되었습니다!

영수증 번호: {receipt_number}
결제 수단: {payment_method}
주문 내역: {items_str}
결제 금액: {total:,}원

이용해 주셔서 감사합니다! 😊"""


# =============================================================================
# RESERVATION TOOLS
# =============================================================================


@function_tool
def check_availability(
    wrapper: RunContextWrapper[RestaurantContext],
    date: str,
    time: str,
    party_size: int,
) -> str:
    """
    Check table availability for a given date, time, and party size.

    Args:
        date: Reservation date in YYYY-MM-DD format (e.g. '2026-03-15')
        time: Reservation time in HH:MM format (e.g. '18:00')
        party_size: Number of people in the party
    """
    is_available = random.random() > 0.2

    if is_available:
        return f"✅ {date} {time}, {party_size}명 예약 가능합니다."

    all_times = ["17:00", "17:30", "18:30", "19:00", "19:30", "20:00"]
    suggestions = ", ".join(random.sample(all_times, 3))
    return f"❌ {date} {time}에는 자리가 없습니다.\n대안 시간대: {suggestions}"


@function_tool
def make_reservation(
    wrapper: RunContextWrapper[RestaurantContext],
    name: str,
    date: str,
    time: str,
    party_size: int,
) -> str:
    """
    Make a table reservation after confirming availability.

    Args:
        name: Name for the reservation
        date: Reservation date in YYYY-MM-DD format (e.g. '2026-03-15')
        time: Reservation time in HH:MM format (e.g. '18:00')
        party_size: Number of people in the party
    """
    confirmation = f"RSV-{random.randint(10000, 99999)}"
    RESERVATIONS[confirmation] = {
        "name": name,
        "date": date,
        "time": time,
        "party_size": party_size,
    }

    return f"""🎉 예약이 완료되었습니다!

확인번호: {confirmation}
예약자명: {name}
날짜: {date} {time}
인원: {party_size}명

확인번호를 꼭 메모해 두세요.
변경/취소는 방문 2시간 전까지 가능합니다."""


@function_tool
def get_reservation(
    wrapper: RunContextWrapper[RestaurantContext], confirmation_number: str
) -> str:
    """
    Look up an existing reservation by confirmation number.

    Args:
        confirmation_number: Reservation confirmation number (e.g. 'RSV-12345')
    """
    reservation = RESERVATIONS.get(confirmation_number)
    if not reservation:
        return f"'{confirmation_number}' 확인번호로 예약을 찾을 수 없습니다."

    return f"""📋 예약 정보

확인번호: {confirmation_number}
예약자명: {reservation['name']}
날짜: {reservation['date']} {reservation['time']}
인원: {reservation['party_size']}명"""


# =============================================================================
# HOOKS
# =============================================================================


class AgentToolUsageLoggingHooks(AgentHooks):

    async def on_tool_start(
        self,
        context: RunContextWrapper[Any],
        agent: Agent,
        tool: Tool,
    ):
        with st.sidebar:
            st.write(f"🔧 **{agent.name}** 도구 실행 중: `{tool.name}`")

    async def on_tool_end(
        self,
        context: RunContextWrapper[Any],
        agent: Agent,
        tool: Tool,
        result: str,
    ):
        with st.sidebar:
            st.write(f"✅ **{agent.name}** 도구 완료: `{tool.name}`")
            st.code(result)

    async def on_handoff(
        self,
        context: RunContextWrapper[Any],
        agent: Agent,
        source: Agent,
    ):
        with st.sidebar:
            st.write(f"🔄 Handoff: **{source.name}** → **{agent.name}**")

    async def on_start(
        self,
        context: RunContextWrapper[Any],
        agent: Agent,
    ):
        with st.sidebar:
            st.write(f"🚀 **{agent.name}** 시작")

    async def on_end(
        self,
        context: RunContextWrapper[Any],
        agent: Agent,
        output,
    ):
        with st.sidebar:
            st.write(f"🏁 **{agent.name}** 완료")
