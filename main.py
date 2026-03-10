import asyncio

import dotenv
import streamlit as st

from agents import InputGuardrailTripwireTriggered, Runner, SQLiteSession
from models import RestaurantContext
from my_agents.triage_agent import triage_agent

dotenv.load_dotenv()

st.title("🍽️ Restaurant Bot")

HANDOFF_MESSAGES = {
    "Menu Agent":        "🍽️ 메뉴 전문가에게 연결합니다...",
    "Order Agent":       "🛒 주문 담당자에게 연결합니다...",
    "Reservation Agent": "📅 예약 담당자에게 연결합니다...",
}

if "session" not in st.session_state:
    st.session_state["session"] = SQLiteSession(
        "chat-history",
        "restaurant-memory.db",
    )
session = st.session_state["session"]


if "agent" not in st.session_state:
    st.session_state["agent"] = triage_agent

if "restaurant_ctx" not in st.session_state:
    st.session_state["restaurant_ctx"] = RestaurantContext()
restaurant_ctx: RestaurantContext = st.session_state["restaurant_ctx"]


async def paint_history():
    messages = await session.get_items()
    for message in messages:
        if "role" in message:
            with st.chat_message(message["role"]):
                if message["role"] == "user":
                    st.write(message["content"])
                else:
                    if message["type"] == "message":
                        st.write(message["content"][0]["text"].replace("$", r"\$"))


asyncio.run(paint_history())


async def run_agent(message):
    with st.chat_message("ai"):
        text_placeholder = st.empty()
        response = ""

        st.session_state["text_placeholder"] = text_placeholder

        try:
            stream = Runner.run_streamed(
                st.session_state["agent"],
                message,
                session=session,
                context=restaurant_ctx,
            )

            async for event in stream.stream_events():
                if event.type == "raw_response_event":
                    if event.data.type == "response.output_text.delta":
                        response += event.data.delta
                        text_placeholder.write(response.replace("$", r"\$"))

                elif event.type == "agent_updated_stream_event":
                    if st.session_state["agent"].name != event.new_agent.name:
                        msg = HANDOFF_MESSAGES.get(
                            event.new_agent.name,
                            f"{event.new_agent.name}에 연결됨",
                        )
                        st.write(msg)
                        st.session_state["agent"] = event.new_agent
                        text_placeholder = st.empty()
                        response = ""

        except InputGuardrailTripwireTriggered:
            st.write("죄송합니다, 레스토랑 관련 문의만 도와드릴 수 있습니다.")


message = st.chat_input("무엇을 도와드릴까요?")

if message:
    if "text_placeholder" in st.session_state:
        st.session_state["text_placeholder"].empty()

    with st.chat_message("human"):
        st.write(message)
    asyncio.run(run_agent(message))


# Sidebar
with st.sidebar:
    st.subheader("🛒 현재 주문")
    if restaurant_ctx.order_items:
        for item in restaurant_ctx.order_items:
            st.write(f"• {item.dish_name} x{item.quantity} — {item.price * item.quantity:,.0f}원")
        total = sum(i.price * i.quantity for i in restaurant_ctx.order_items)
        st.write(f"**총합계: {total:,.0f}원**")
        if restaurant_ctx.order_confirmed:
            st.success("✅ 주문 확정됨")
    else:
        st.write("주문 내역 없음")

    st.divider()

    if st.session_state.get("handoff_logs"):
        st.subheader("🔀 핸드오프 기록")
        for log in st.session_state["handoff_logs"]:
            st.info(f"{log['msg']}\n\n사유: {log['reason']}")
        st.divider()

    reset = st.button("대화 초기화")
    if reset:
        asyncio.run(session.clear_session())
        del st.session_state["session"]
        st.session_state["agent"] = triage_agent
        st.session_state["restaurant_ctx"] = RestaurantContext()
        st.session_state["handoff_logs"] = []
        st.rerun()
    st.write(asyncio.run(session.get_items()))
