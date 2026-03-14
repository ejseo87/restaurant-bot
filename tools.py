import json
import random
import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import streamlit as st

from agents import function_tool, AgentHooks, Agent, Tool, RunContextWrapper
from models import RestaurantContext, OrderItem

KST = ZoneInfo("Asia/Seoul")


# =============================================================================
# PERSISTENCE
# =============================================================================

DB_PATH = Path("restaurant-memory.db")
CONFIRMATION_PATTERN = re.compile(r"^RSV-\d{5}$", re.IGNORECASE)


def _get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _init_db():
    with _get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS reservations (
                confirmation TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                date TEXT NOT NULL,
                time TEXT NOT NULL,
                party_size INTEGER NOT NULL,
                phone_number TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """,
        )
        # phone_number 컬럼이 없는 구 버전 DB 마이그레이션
        existing = {row[1] for row in conn.execute("PRAGMA table_info(reservations)")}
        if "phone_number" not in existing:
            conn.execute("ALTER TABLE reservations ADD COLUMN phone_number TEXT NOT NULL DEFAULT ''")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS orders (
                order_number TEXT PRIMARY KEY,
                items_json TEXT NOT NULL,
                total REAL NOT NULL,
                confirmed_at TEXT NOT NULL
            )
            """,
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS payments (
                payment_number TEXT PRIMARY KEY,
                order_number   TEXT NOT NULL,
                payment_method TEXT NOT NULL,
                amount         REAL NOT NULL,
                paid_at        TEXT NOT NULL
            )
            """,
        )


def _store_reservation(confirmation: str, name: str, date: str, time: str, party_size: int, phone_number: str,):
    with _get_conn() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO reservations
            (confirmation, name, date, time, party_size, phone_number, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (confirmation, name, date, time, party_size, phone_number, datetime.now(KST).isoformat()),
        )


def _fetch_reservation(confirmation: str) -> dict | None:
    with _get_conn() as conn:
        row = conn.execute(
            """
            SELECT confirmation, name, date, time, party_size, phone_number
            FROM reservations
            WHERE confirmation = ?
            """,
            (confirmation,),
        ).fetchone()
    return dict(row) if row else None


def _store_order(order_number: str, context: RestaurantContext):
    items_payload = [
        {"dish_name": item.dish_name, "quantity": item.quantity, "price": item.price}
        for item in context.order_items
    ]
    total = sum(item["price"] * item["quantity"] for item in items_payload)
    with _get_conn() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO orders
            (order_number, items_json, total, confirmed_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                order_number,
                json.dumps(items_payload, ensure_ascii=False),
                total,
                datetime.now(KST).isoformat(),
            ),
        )


def _store_payment(payment_number: str, order_number: str, payment_method: str, amount: float):
    with _get_conn() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO payments
            (payment_number, order_number, payment_method, amount, paid_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (payment_number, order_number, payment_method, amount, datetime.now(KST).isoformat()),
        )


def reset_db_data():
    """예약/주문/결제 데이터를 모두 삭제합니다."""
    with _get_conn() as conn:
        conn.execute("DELETE FROM reservations")
        conn.execute("DELETE FROM orders")
        conn.execute("DELETE FROM payments")


_init_db()


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
    reopened = False
    if context.order_confirmed:
        context.order_confirmed = False
        context.order_number = None
        reopened = True

    dish = MENU.get(dish_name)
    if not dish:
        available = ", ".join(MENU.keys())
        return f"'{dish_name}'을(를) 찾을 수 없습니다.\n전체 메뉴: {available}"

    reopen_notice = "\n⚠️ 확정된 주문이 수정되어 재확정이 필요합니다." if reopened else ""

    for item in context.order_items:
        if item.dish_name == dish_name:
            item.quantity += quantity
            subtotal = item.quantity * dish["price"]
            return f"✅ {dish_name} {quantity}개 추가 (총 {item.quantity}개, {subtotal:,}원){reopen_notice}"

    context.order_items.append(
        OrderItem(dish_name=dish_name, quantity=quantity, price=dish["price"])
    )
    return f"✅ {dish_name} {quantity}개를 주문에 추가했습니다. ({dish['price']:,}원){reopen_notice}"


@function_tool
def remove_from_order(
    wrapper: RunContextWrapper[RestaurantContext],
    dish_name: str,
) -> str:
    """
    Remove a dish completely from the current order.

    Args:
        dish_name: Name of the dish to remove
    """
    context = wrapper.context
    for i, item in enumerate(context.order_items):
        if item.dish_name == dish_name:
            context.order_items.pop(i)
            if context.order_confirmed:
                context.order_confirmed = False
                context.order_number = None
                return f"✅ {dish_name}을(를) 주문에서 제거했습니다.\n⚠️ 주문 내역이 변경되어 재확정이 필요합니다."
            return f"✅ {dish_name}을(를) 주문에서 제거했습니다."
    return f"'{dish_name}'은(는) 현재 주문에 없습니다."


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
    context.order_number = order_number
    total = sum(item.price * item.quantity for item in context.order_items)
    items_str = ", ".join(f"{item.dish_name} x{item.quantity}" for item in context.order_items)
    _store_order(order_number, context)

    return f"""🎉 주문이 확정되었습니다!

주문번호: {order_number}
주문 내역: {items_str}
총 금액: {total:,}원
예상 준비 시간: 20~30분

맛있게 드세요! 😊
"""


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
    order_number = context.order_number or f"ORD-{random.randint(1000, 9999)}"

    _store_payment(receipt_number, order_number, payment_method, total)

    # Reset order state after successful payment
    context.order_items.clear()
    context.order_confirmed = False
    context.order_number = None

    return f"""💳 결제가 완료되었습니다!

영수증 번호: {receipt_number}
주문 번호: {order_number}
결제 수단: {payment_method}
주문 내역: {items_str}
결제 금액: {total:,}원

이용해 주셔서 감사합니다! 😊"""


# =============================================================================
# REFUND TOOL (Complaints Agent용)
# =============================================================================


@function_tool
def process_refund(
    wrapper: RunContextWrapper[RestaurantContext],
    reason: str,
    compensation: str,
) -> str:
    """
    Process a refund and log compensation for a customer complaint.
    Use this when a customer complaint requires a refund or compensation.

    Args:
        reason: Reason for the refund (e.g., '음식 위생 문제 - 벌레 발견')
        compensation: Compensation provided (e.g., '식사비 전액 환불 + 다음 방문 50% 할인권')
    """
    context = wrapper.context
    refund_number = f"REF-{random.randint(10000, 99999)}"
    total = sum(item.price * item.quantity for item in context.order_items) if context.order_items else 0

    context.order_items.clear()
    context.order_confirmed = False
    context.order_number = None

    with _get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS refunds (
                refund_number  TEXT PRIMARY KEY,
                reason         TEXT NOT NULL,
                compensation   TEXT NOT NULL,
                amount         REAL NOT NULL,
                processed_at   TEXT NOT NULL
            )
            """,
        )
        conn.execute(
            "INSERT OR REPLACE INTO refunds (refund_number, reason, compensation, amount, processed_at) VALUES (?, ?, ?, ?, ?)",
            (refund_number, reason, compensation, total, datetime.now(KST).isoformat()),
        )

    return f"""✅ 환불 처리가 완료되었습니다.

환불 번호: {refund_number}
환불 사유: {reason}
환불 금액: {total:,}원
제공 혜택: {compensation}

담당 매니저가 24시간 내에 연락드릴 예정입니다.
불편을 드려 진심으로 사과드립니다."""


# =============================================================================
# RESERVATION TOOLS
# =============================================================================


ALL_RESERVATION_TIMES = ["17:00", "17:30", "18:00", "18:30", "19:00", "19:30", "20:00", "20:30", "21:00"]
MAX_TABLES_PER_SLOT = 10  # 시간대별 최대 예약 팀 수


def _validate_reservation_datetime(date: str, time: str) -> str | None:
    """날짜/시간이 현재 이후인지 검증. 문제 있으면 에러 메시지 반환, 없으면 None."""
    try:
        requested = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
    except ValueError:
        return "❌ 날짜/시간 형식이 올바르지 않습니다.\n날짜는 YYYY-MM-DD (예: 2026-03-15), 시간은 HH:MM (예: 18:00) 형식으로 입력해 주세요."

    now = datetime.now(KST).replace(tzinfo=None)
    if requested <= now:
        today = now.strftime("%Y-%m-%d")
        current_time = now.strftime("%H:%M")
        available_times = [t for t in ALL_RESERVATION_TIMES if t > current_time]
        if available_times:
            time_guide = ", ".join(available_times)
            return (
                f"❌ 이미 지난 날짜/시간입니다. 현재 시각 이후로만 예약 가능합니다.\n\n"
                f"오늘({today}) 예약 가능한 시간대: {time_guide}\n"
                f"또는 내일 이후 날짜로 예약해 주세요."
            )
        else:
            tomorrow = (now.replace(hour=0, minute=0, second=0) + timedelta(days=1)).strftime("%Y-%m-%d")
            time_guide = ", ".join(ALL_RESERVATION_TIMES)
            return (
                f"❌ 오늘은 더 이상 예약 가능한 시간이 없습니다.\n\n"
                f"내일({tomorrow}) 이후로 예약해 주세요.\n"
                f"예약 가능 시간대: {time_guide}"
            )
    return None


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
    error = _validate_reservation_datetime(date, time)
    if error:
        return error

    with _get_conn() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM reservations WHERE date=? AND time=?",
            (date, time),
        ).fetchone()[0]

    if count >= MAX_TABLES_PER_SLOT:
        other_times = [t for t in ALL_RESERVATION_TIMES if t != time]
        suggestions = ", ".join(random.sample(other_times, min(3, len(other_times))))
        return (
            f"❌ {date} {time}에는 예약이 모두 찼습니다. (만석: {MAX_TABLES_PER_SLOT}팀)\n"
            f"대안 시간대: {suggestions}"
        )

    remaining = MAX_TABLES_PER_SLOT - count
    return f"✅ {date} {time}, {party_size}명 예약 가능합니다. (잔여 {remaining}팀)"


@function_tool
def make_reservation(
    wrapper: RunContextWrapper[RestaurantContext],
    name: str,
    date: str,
    time: str,
    party_size: int,
    phone_number: str,
) -> str:
    """
    Make a table reservation after confirming availability.

    Args:
        name: Name for the reservation
        date: Reservation date in YYYY-MM-DD format (e.g. '2026-03-15')
        time: Reservation time in HH:MM format (e.g. '18:00')
        party_size: Number of people in the party
        phone_number: Phone number to call the reservation holder
    """
    error = _validate_reservation_datetime(date, time)
    if error:
        return error

    with _get_conn() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM reservations WHERE date=? AND time=?",
            (date, time),
        ).fetchone()[0]
    if count >= MAX_TABLES_PER_SLOT:
        return f"❌ 죄송합니다. {date} {time}에 방금 예약이 마감되었습니다. 다른 시간대를 선택해 주세요."

    confirmation = f"RSV-{random.randint(10000, 99999)}"
    _store_reservation(confirmation, name, date, time, party_size, phone_number)

    return f"""🎉 예약이 완료되었습니다!

확인번호: {confirmation}
예약자명: {name}
날짜: {date} {time}
인원: {party_size}명
예약자 연락처: {phone_number}

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
    cleaned_confirmation = confirmation_number.strip().upper()
    if not CONFIRMATION_PATTERN.match(cleaned_confirmation):
        return "예약을 조회하려면 확인번호(RSV-12345 형식)를 먼저 알려주세요."

    reservation = _fetch_reservation(cleaned_confirmation)
    if not reservation:
        return f"'{cleaned_confirmation}' 확인번호로 예약을 찾을 수 없습니다."

    return f"""📋 예약 정보

확인번호: {cleaned_confirmation}
예약자명: {reservation['name']}
날짜: {reservation['date']} {reservation['time']}
인원: {reservation['party_size']}명
연락처: {reservation['phone_number']}"""


@function_tool
def update_reservation(
    wrapper: RunContextWrapper[RestaurantContext],
    confirmation_number: str,
    name: str | None = None,
    date: str | None = None,
    time: str | None = None,
    party_size: int | None = None,
    phone_number: str | None = None,
) -> str:
    """
    Update an existing reservation. Only provide the fields to change.

    Args:
        confirmation_number: Reservation confirmation number (e.g. 'RSV-12345')
        name: New name (optional)
        date: New date in YYYY-MM-DD format (optional)
        time: New time in HH:MM format (optional)
        party_size: New number of people (optional)
        phone_number: New phone number (optional)
    """
    cleaned = confirmation_number.strip().upper()
    if not CONFIRMATION_PATTERN.match(cleaned):
        return "변경하려면 확인번호(RSV-12345 형식)를 알려주세요."

    existing = _fetch_reservation(cleaned)
    if not existing:
        return f"'{cleaned}' 확인번호로 예약을 찾을 수 없습니다."

    new_date = date or existing["date"]
    new_time = time or existing["time"]

    if date or time:
        error = _validate_reservation_datetime(new_date, new_time)
        if error:
            return error

    new_name = name or existing["name"]
    new_party_size = party_size or existing["party_size"]
    new_phone = phone_number or existing["phone_number"]

    with _get_conn() as conn:
        conn.execute(
            """
            UPDATE reservations
            SET name=?, date=?, time=?, party_size=?, phone_number=?
            WHERE confirmation=?
            """,
            (new_name, new_date, new_time, new_party_size, new_phone, cleaned),
        )

    return f"""✅ 예약이 변경되었습니다.

확인번호: {cleaned}
예약자명: {new_name}
날짜: {new_date} {new_time}
인원: {new_party_size}명
연락처: {new_phone}"""


@function_tool
def cancel_reservation(
    wrapper: RunContextWrapper[RestaurantContext],
    confirmation_number: str,
) -> str:
    """
    Cancel an existing reservation.

    Args:
        confirmation_number: Reservation confirmation number (e.g. 'RSV-12345')
    """
    cleaned = confirmation_number.strip().upper()
    if not CONFIRMATION_PATTERN.match(cleaned):
        return "취소하려면 확인번호(RSV-12345 형식)를 알려주세요."

    existing = _fetch_reservation(cleaned)
    if not existing:
        return f"'{cleaned}' 확인번호로 예약을 찾을 수 없습니다."

    with _get_conn() as conn:
        conn.execute("DELETE FROM reservations WHERE confirmation = ?", (cleaned,))

    return f"""✅ 예약이 취소되었습니다.

취소된 예약:
확인번호: {cleaned}
예약자명: {existing['name']}
날짜: {existing['date']} {existing['time']}
인원: {existing['party_size']}명"""


# =============================================================================
# ORDER INQUIRY TOOL
# =============================================================================

ORDER_PATTERN = re.compile(r"^ORD-\d{4}$", re.IGNORECASE)


@function_tool
def get_order(
    wrapper: RunContextWrapper[RestaurantContext],
    order_number: str,
) -> str:
    """
    Look up a confirmed order by order number.

    Args:
        order_number: Order number (e.g. 'ORD-1234')
    """
    cleaned = order_number.strip().upper()
    if not ORDER_PATTERN.match(cleaned):
        return "주문을 조회하려면 주문번호(ORD-1234 형식)를 알려주세요."

    with _get_conn() as conn:
        row = conn.execute(
            "SELECT order_number, items_json, total, confirmed_at FROM orders WHERE order_number = ?",
            (cleaned,),
        ).fetchone()

    if not row:
        return f"'{cleaned}' 주문번호를 찾을 수 없습니다."

    items = json.loads(row["items_json"])
    items_str = "\n".join(
        f"• {i['dish_name']} x{i['quantity']} = {i['price'] * i['quantity']:,}원"
        for i in items
    )

    return f"""🛒 주문 내역

주문번호: {row['order_number']}
{items_str}
총 금액: {row['total']:,.0f}원
주문 시각: {row['confirmed_at']}"""


# =============================================================================
# HOOKS
# =============================================================================


def _append_hook_log(entry: dict):
    if "hook_logs" not in st.session_state:
        st.session_state["hook_logs"] = []
    st.session_state["hook_logs"].append(entry)


class AgentToolUsageLoggingHooks(AgentHooks):

    async def on_tool_start(
        self,
        context: RunContextWrapper[Any],
        agent: Agent,
        tool: Tool,
    ):
        _append_hook_log({"type": "tool_start", "agent": agent.name, "tool": tool.name})

    async def on_tool_end(
        self,
        context: RunContextWrapper[Any],
        agent: Agent,
        tool: Tool,
        result: str,
    ):
        _append_hook_log({"type": "tool_end", "agent": agent.name, "tool": tool.name, "result": result})

    async def on_handoff(
        self,
        context: RunContextWrapper[Any],
        agent: Agent,
        source: Agent,
    ):
        _append_hook_log({"type": "handoff", "from": source.name, "to": agent.name})

    async def on_start(
        self,
        context: RunContextWrapper[Any],
        agent: Agent,
    ):
        _append_hook_log({"type": "start", "agent": agent.name})

    async def on_end(
        self,
        context: RunContextWrapper[Any],
        agent: Agent,
        output,
    ):
        _append_hook_log({"type": "end", "agent": agent.name})
